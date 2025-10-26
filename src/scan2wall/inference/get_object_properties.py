import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from PIL import Image
import json
import os
import argparse
from dotenv import load_dotenv

# Configure Gemini
load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash")

# Prompt text enforcing JSON schema
prompt = """
You are a metrology assistant. From the image uploaded, infer likely real-world physical properties for the identified object.
These will be used in a scientific simulation.
Return ONLY valid JSON in this exact schema:

{
  "object_type": "string",
  "use_case": "string",
  "materials": [{"name":"string","prob":0..1}],
  "rigidity": "rigid" | "deformable",
  "dimensions_m": {
    "length": {"value": float},
    "width": {"value": float},
    "height": {"value": float}
  },
  "weight_kg": {"value": float},
  "friction_coefficients": {
    "static": float,
    "dynamic": float
  },
  "restitution": {
    "value": float,
    "description": "string"
  },
  "assumptions": ["string"],
  "confidence_overall": 0..1
}

Guidelines:
- Estimate static and dynamic friction coefficients between the object and a generic smooth horizontal surface (e.g., steel or wood table).
- Estimate coefficient of restitution (bounciness) for the object:
  * 0.0 = no bounce (clay, soft fabric, pillow)
  * 0.1-0.3 = low bounce (wood block, ceramic plate)
  * 0.4-0.6 = moderate bounce (plastic, tennis racket, basketball)
  * 0.7-0.8 = high bounce (rubber ball, bouncy ball)
  * 0.9+ = very high bounce (superball, steel on steel)
- Use typical values from physics data for the predicted material(s).
- Return only the JSON, no prose.
"""

def get_object_properties(image_path):
    img = Image.open(image_path)

    # Configure safety settings to be more permissive for technical analysis
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    # Call the model
    try:
        response = model.generate_content(
            [prompt, img],
            generation_config={
                "temperature": 0.2,
                "max_output_tokens": 2048,
                "response_mime_type": "application/json",
            },
            safety_settings=safety_settings,
        )

        # Check if response has valid content
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
        except json.JSONDecodeError:
            result = {"error": "Invalid JSON returned", "raw": response.text}

        return result

    except Exception as e:
        print(f"⚠ Gemini property inference error: {e}")
        return {"error": str(e), "raw": str(e)}


# Validation prompt for segmentation quality check
validation_prompt = """LEFT: Original image/photo
RIGHT: Extraction mask from segmentation of the original image.

Look at the right image on the white background.

Is it a single complete object (80%+ present)?
Can you see other extra objects in the background? For example, if it was laying on a table and you can still see the table, that's an extra object.
If there is a plug, that's an extra object. If there is just a a
Do surfaces/walls/floors/extra objects show at the edges?
Is it multiple instances of the same object class?

~200 characters.

ACCEPT the extracted object if:
- Single complete object (80%+ present)
- Background is solid white(soft edges/gradients OK)
- NO extra objects appear in the background/at the edges

REJECT the extracted object if:
- Background surfaces visible in RIGHT image (walls, floors, tables, ground)
- Cast shadows on visible ground surfaces
- Hands visible in RIGHT image
- Object incomplete or unrecognizable in RIGHT image
- Several objects of the same class (example: 3 apples)

Important: Soft fading = OK. Visible surface details = REJECT.

Reply format:
Line 1: Description (~200 chars)
Line 2: 'ACCEPT' or 'REJECT'"""


def validate_segmentation(image_path):
    """
    Validate segmentation quality using Gemini 2.5 Flash.

    Args:
        image_path: Path to concatenated image (original LEFT, masked RIGHT)

    Returns:
        dict: {"decision": "ACCEPT" or "REJECT", "description": str}
    """
    img = Image.open(image_path)

    # Resize image to max 1024px for faster Gemini inference
    # (validation doesn't need full resolution)
    max_dimension = 1024
    if max(img.size) > max_dimension:
        # Calculate new size maintaining aspect ratio
        ratio = max_dimension / max(img.size)
        new_size = tuple(int(dim * ratio) for dim in img.size)
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        print(f"  📐 Resized validation image: {image_path.split('/')[-1]} → {new_size[0]}x{new_size[1]}")

    # Call the model
    try:
        # Configure safety settings to be more permissive for technical analysis
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }

        response = model.generate_content(
            [validation_prompt, img],
            generation_config={
                "temperature": 0.1,
                "max_output_tokens": 1024,
            },
            safety_settings=safety_settings,
        )

        # Check if response has valid content
        if not response.candidates:
            print(f"⚠ Gemini returned no candidates")
            return {
                "decision": "REJECT",
                "description": "Gemini API returned no response",
                "raw_response": "No candidates returned"
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
                "raw_response": f"finish_reason={candidate.finish_reason}"
            }

        # Parse response - expecting 2 lines
        lines = response.text.strip().split('\n')

        description = lines[0] if len(lines) > 0 else "No description"
        decision_line = lines[1] if len(lines) > 1 else lines[0] if len(lines) > 0 else ""

        # Extract ACCEPT or REJECT
        decision = "REJECT"  # Default to REJECT for safety
        if "ACCEPT" in decision_line.upper():
            decision = "ACCEPT"
        elif "REJECT" in decision_line.upper():
            decision = "REJECT"

        return {
            "decision": decision,
            "description": description,
            "raw_response": response.text
        }

    except Exception as e:
        print(f"⚠ Gemini validation error: {e}")
        return {
            "decision": "REJECT",
            "description": f"Validation error: {str(e)}",
            "raw_response": str(e)
        }