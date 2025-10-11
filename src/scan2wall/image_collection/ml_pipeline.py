from pathlib import Path
import cv2
import numpy as np

# Put your image ML pipeline here.
# This stub reads the image, converts to RGB, and writes a thumbnail next to it.


def process_image(image_path: str) -> str:
    """
    Args:
        image_path: path to uploaded image
    Returns:
        Path to a processed artifact (e.g., a thumbnail or JSON result)
    """
    p = Path(image_path)
    out_dir = p.parent.parent / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    img = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if img is None:
        fail = out_dir / f"{p.stem}_FAILED.txt"
        fail.write_text("Could not read uploaded image.")
        return str(fail)

    # Example processing: resize to thumbnail and save
    h, w = img.shape[:2]
    scale = 256 / max(h, w)
    new_size = (int(w * scale), int(h * scale))
    thumb = cv2.resize(img, new_size, interpolation=cv2.INTER_AREA)
    out = out_dir / f"{p.stem}_thumb.jpg"
    cv2.imwrite(str(out), thumb)

    return str(out)
