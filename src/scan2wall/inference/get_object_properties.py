import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from PIL import Image
import json
import os
import argparse
import time
import re
from dotenv import load_dotenv

# Configure Gemini
load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
# Use 2.0 Flash - might be faster than 2.5
model = genai.GenerativeModel("gemini-2.0-flash")

# Prompt text enforcing JSON schema
prompt = """LEFT: Original image/photo
RIGHT: Extraction mask of principal object from segmentation of the original image.

You are a metrology assistant asked to estimate the physical properties and size of the principal object.
Return ONLY valid JSON in this exact schema:

{
  "scene_description": "string (max 200 chars)",
  "object_type": "string",
  "use_case": "string",
  "rigidity": {
    "type": "rigid" | "deformable"
  },
  "dimensions_m": {
    "length": float,
    "width": float,
    "height": float
  },
  "weight_kg": float,
  "friction_coefficients": {
    "static": float,
    "dynamic": float
  },
  "restitution": float,
  "restitution_description": "string",
  "assumptions": ["string"]
}

Guidelines:
- scene_description: Briefly describe what you see in the scene on the left (max 200 characters). Focus on the main object, its appearance, and surrounding context. 

- dimensions_m: Use background objects (visible on the left side) to estimate the scale and dimensions of the target object. Common reference objects include: hands, tables, floors, furniture, people, doorways, windows, etc.

- friction_coefficients: Estimate static and dynamic friction coefficients between the object and a generic smooth horizontal surface (e.g., steel or wood table).

- restitution: estimate coefficient of restitution (bounciness) for the object:
  0.0-0.1 = no/minimal bounce (clay, pillow, sandbag)
  0.2-0.4 = low bounce (wood block, book, ceramic plate)
  0.5-0.7 = moderate bounce (plastic toys, tennis ball, soccer ball)
  0.75-0.85 = high bounce (basketball, rubber ball, golf ball)
  0.9+ = very high bounce (superball, steel ball bearing)

- rigidity:
  * type: "rigid" for hard objects (metal, wood, hard plastic), "deformable" for soft/flexible objects (fabric, foam, rubber)
  
- Be physically accurate - if an object is clearly rigid (like metal tools, wooden furniture), use high Young's modulus.
- Return ONLY the JSON, no prose.
"""

def get_object_properties(image_path):
    prep_start = time.time()
    img = Image.open(image_path)
    original_size = img.size

    # Resize image more aggressively for faster Gemini inference
    # Testing with smaller sizes to reduce API latency
    max_dimension = 768  # Trying smaller size for speed
    if max(img.size) > max_dimension:
        # Calculate new size maintaining aspect ratio
        ratio = max_dimension / max(img.size)
        new_size = tuple(int(dim * ratio) for dim in img.size)
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        print(f"  📐 Resized property inference image: {image_path.split('/')[-1]} → {new_size[0]}x{new_size[1]}")

    # Convert to RGB if needed (JPEG doesn't support alpha channel)
    if img.mode in ('RGBA', 'LA', 'P'):
        rgb_img = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
        img = rgb_img

    # Estimate image size in KB for correlation with upload time
    import io
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=85)  # JPEG at 85% quality for smaller size
    img_size_kb = len(buf.getvalue()) / 1024
    prep_elapsed = time.time() - prep_start
    print(f"  📦 Image prep: {prep_elapsed:.3f}s, size: {img_size_kb:.1f}KB JPEG ({original_size[0]}x{original_size[1]} → {img.size[0]}x{img.size[1]})")

    # Configure safety settings to be more permissive for technical analysis
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    # Call the model
    try:
        start_time = time.time()
        response = model.generate_content(
            [prompt, img],
            generation_config={
                "temperature": 0.0,  # Lower for faster sampling
                "max_output_tokens": 2048,
                "response_mime_type": "application/json",
            },
            safety_settings=safety_settings,
        )
        api_elapsed = time.time() - start_time
        print(f"  ⏱️  Gemini API call: {api_elapsed:.2f}s")

        # Check if response has valid content
        parse_start = time.time()
        if not response.candidates:
            print(f"⚠ Gemini returned no candidates for property inference")
            return {"error": "No response from Gemini", "raw": "No candidates returned"}

        candidate = response.candidates[0]
        finish_reason_value = int(candidate.finish_reason)

        if finish_reason_value != 1:  # 1 = STOP (successful completion)
            print(f"⚠ Gemini stopped with finish_reason: {candidate.finish_reason} (value={finish_reason_value})")
            if finish_reason_value == 3:  # SAFETY
                print("⚠ Content blocked by safety filters")
            return {
                "error": f"Gemini API error (finish_reason={candidate.finish_reason})",
                "raw": f"finish_reason={candidate.finish_reason}"
            }

        # Parse response JSON
        try:
            result = json.loads(response.text)

            # Validate that result is a dict (not a list or other type)
            if not isinstance(result, dict):
                print(f"⚠ Gemini returned non-dict JSON type: {type(result).__name__}")
                print(f"   Raw response: {response.text[:200]}")
                return {
                    "error": "Invalid JSON structure (expected dict, got list or other type)",
                    "raw": response.text
                }

            parse_elapsed = time.time() - parse_start
            print(f"  📄 Response parsing: {parse_elapsed:.3f}s, response size: {len(response.text)} chars")
        except json.JSONDecodeError:
            result = {"error": "Invalid JSON returned", "raw": response.text}

        return result

    except Exception as e:
        print(f"⚠ Gemini property inference error: {e}")
        return {"error": str(e), "raw": str(e)}


# Validation prompt for segmentation quality check
validation_prompt = """LEFT: Original image/photo
RIGHT: Extraction mask of principal object from segmentation of the original image.

Look at the right image on the white background.
Describe what you can see/what has been extracted from the left scene in ~100 characters.

Then answer each of the following questions with max 50 characters each.
1 - Is it a single complete object (80%+ present)?
2 - Is the background clean solid white (no surfaces/tables/floors visible on the edges or through cracks?)?
3 - Do 95%+ of non-white pixels represent the actual object surface? It's fine if we see a reflection/refraction on the surface, it's still surface. But if we see something through the object, that's not good.
4 - Is it multiple instances of the same object class?
5 - Can you see through holes in the object?
6 - Is a hand holding the object visible?

Then provide a quality score 0-100 based on:
- 100 = Perfect extraction, clean single object
- 80-99 = Good, minor issues
- 50-79 = Acceptable, some problems
- 0-49 = Poor, major issues

Then finish your message with either "ACCEPT" or "REJECT" based on the following criteria:

ACCEPT the extracted object if:
- Single complete object (80%+ present)
- Background is solid white (soft edges/gradients are OK!)
- NO extra objects visible
- The non white pixels in the right show the actual object in a clear way

REJECT the extracted object if:
- Object incomplete or unrecognizable in RIGHT image
- Hands visible in RIGHT image
- A 3D reconstruction algorithm being showed the right image without the scene would be confused as to the object's shape
- Multiple objects of same class (example: 3 apples)
- You can see THROUGH holes in the object to background elements
- The hand/fingers holding the object is part of the mask

Important: Soft fading at edges = OK.

Format:
Description: <your description>
1 - <answer>
2 - <answer>
3 - <answer>
4 - <answer>
5 - <answer>
Quality: <score>/100

**Example responses:**

Description: Clean wooden chair floating on white, complete and clear
1 - Yes, complete chair ~95% present
2 - Yes, pure white background
3 - Yes, all pixels show chair
4 - Yes, single chair only
5 - No
6 - No
Quality: 95/100

Description: Sunglasses on glossy surface, reflection visible below
1 - Yes, sunglasses ~99% complete
2 - No, mirror surface visible below
3 - No, ~20% pixels show reflection
4 - Yes, single pair only
5 - No
6 - No
Quality: 45/100
"""

def validate_segmentation(image_path):
    """
    Validate segmentation quality using Gemini 2.5 Flash.

    Args:
        image_path: Path to concatenated image (original LEFT, masked RIGHT)

    Returns:
        dict: {"decision": "ACCEPT" or "REJECT", "description": str}
    """
    prep_start = time.time()
    img = Image.open(image_path)
    original_size = img.size

    # Resize image aggressively for faster Gemini inference
    # (validation doesn't need full resolution)
    max_dimension = 640  # Trying smaller for speed
    if max(img.size) > max_dimension:
        # Calculate new size maintaining aspect ratio
        ratio = max_dimension / max(img.size)
        new_size = tuple(int(dim * ratio) for dim in img.size)
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        print(f"  📐 Resized validation image: {image_path.split('/')[-1]} → {new_size[0]}x{new_size[1]}")

    # Convert to RGB if needed (for consistency with property inference)
    if img.mode in ('RGBA', 'LA', 'P'):
        rgb_img = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
        img = rgb_img

    # Estimate image size in KB
    import io
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=85)
    img_size_kb = len(buf.getvalue()) / 1024
    prep_elapsed = time.time() - prep_start
    print(f"  📦 Image prep: {prep_elapsed:.3f}s, size: {img_size_kb:.1f}KB JPEG ({original_size[0]}x{original_size[1]} → {img.size[0]}x{img.size[1]})")

    # Call the model
    try:
        # Configure safety settings to be more permissive for technical analysis
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }

        start_time = time.time()
        response = model.generate_content(
            [validation_prompt, img],
            generation_config={
                "temperature": 0.0,  # Very low for fast, deterministic validation
                "max_output_tokens": 4096,
            },
            safety_settings=safety_settings,
        )
        api_elapsed = time.time() - start_time
        print(f"  ⏱️  Gemini API call: {api_elapsed:.2f}s")

        # Check if response has valid content
        parse_start = time.time()
        if not response.candidates:
            print(f"⚠ Gemini returned no candidates")
            return {
                "decision": "REJECT",
                "description": "Gemini API returned no response",
                "raw_response": "No candidates returned",
                "score": None
            }

        candidate = response.candidates[0]
        print(f"Gemini finish_reason: {candidate.finish_reason}")
        print(f"Gemini safety_ratings: {candidate.safety_ratings}")

        # Check finish reason - should be STOP for successful completion
        # FinishReason enum: STOP=1, MAX_TOKENS=2, SAFETY=3, RECITATION=4, OTHER=5
        finish_reason_value = int(candidate.finish_reason)
        if finish_reason_value != 1:
            print(f"⚠ Gemini stopped with finish_reason: {candidate.finish_reason} (value={finish_reason_value})")
            if finish_reason_value == 3:
                print("⚠ Content blocked by safety filters")
            return {
                "decision": "REJECT",
                "description": f"Gemini API error (finish_reason={candidate.finish_reason})",
                "raw_response": f"finish_reason={candidate.finish_reason}",
                "score": None
            }

        lines = response.text.strip().split('\n')
        if not lines:  # Edge case: empty response
            return {"decision": "REJECT", "description": "Empty response", "raw_response": "", "score": None}

        decision_line = lines[-1]
        description = '\n'.join(lines[:-1]) if len(lines) > 1 else "No description"


        # Extract decision
        decision = "REJECT"
        if "ACCEPT" in decision_line.upper():
            decision = "ACCEPT"

        # Extract quality score using regex pattern "Quality: X/100"
        score = None
        score_match = re.search(r'Quality:\s*(\d+)/100', response.text)
        if score_match:
            score = int(score_match.group(1))

        parse_elapsed = time.time() - parse_start
        print(f"  📄 Response parsing: {parse_elapsed:.3f}s, response size: {len(response.text)} chars, decision: {decision}, score: {score}")

        return {
            "decision": decision,
            "description": description,
            "raw_response": response.text,
            "score": score
        }

    except Exception as e:
        print(f"⚠ Gemini validation error: {e}")
        return {
            "decision": "REJECT",
            "description": f"Validation error: {str(e)}",
            "raw_response": str(e),
            "score": None
        }