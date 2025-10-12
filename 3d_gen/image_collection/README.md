# Phone → Python Image Drop (Seamless capture, no streaming)

**One-tap** on your phone: open a page, take a photo, and the upload **auto-starts**. The Python server saves the image and immediately runs your ML pipeline.

## Run
```bash
python -m venv .venv && source .venv/bin/activate    # optional but recommended
pip install -r requirements.txt
python run.py
```
Scan `upload_page_qr.png` or use the printed URL. Ensure that port 8000 is exposed, or your phone and the server machine are on the **same Wi‑Fi**.

## Customize your ML
Edit `ml_pipeline.py`:
```python
def process_image(image_path: str) -> str:
    # Load with OpenCV / Pillow, run inference, write outputs, and return the path.
    return out_path
```

## Endpoints
- `/` – Mobile capture/upload page (auto-upload after capture)
- `/upload` – Receives a single image (multipart form)

## Notes
- The file input uses `accept="image/*" capture="environment"`, prompting the rear camera by default.
- To capture multiple, you can add `multiple` to the `<input>` and extend `/upload` to loop over files.
- If you want EXIF orientation handled for JPEGs, read via Pillow and rotate before saving or inference.
```python
from PIL import Image, ImageOps
img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
```
- For on-the-go privacy, you can run this locally and process entirely on your machine.
