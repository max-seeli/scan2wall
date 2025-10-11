import google.generativeai as genai
from PIL import Image
import json
import os
import argparse
from dotenv import load_dotenv

# Configure Gemini
load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel("gemini-2.0-flash")

# Prompt text enforcing JSON schema
prompt = """
You are a metrology assistant. From the image, infer likely real-world physical properties.
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
  "assumptions": ["string"],
  "confidence_overall": 0..1
}

Guidelines:
- Estimate static and dynamic friction coefficients between the object and a generic smooth horizontal surface (e.g., steel or wood table).
- Use typical values from physics data for the predicted material(s).
- Return only the JSON, no prose.
"""

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "image_path", type=str, help="Path to the input image file"
    )
    args = parser.parse_args()
    # Load your image
    image_path = args.image_path
    img = Image.open(image_path)

    # Call the model
    response = model.generate_content(
        [prompt, img],
        generation_config={
            "temperature": 0.2,
            "max_output_tokens": 512,
            "response_mime_type": "application/json",
        },
    )

    # Parse response JSON
    try:
        result = json.loads(response.text)
    except json.JSONDecodeError:
        result = {"error": "Invalid JSON returned", "raw": response.text}

    print(json.dumps(result, indent=2))