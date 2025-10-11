from pathlib import Path
import cv2
import numpy as np
from scan2wall.material_properties import get_object_properties
import requests
import re

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

    # generate glb mesh file
    # 1. make a post request to
    url = "https://8012-hah9c53y9.brevlab.com/process"
    files = {"file": open(p, "rb")}
    data = {"output_path": "/tmp/output.png", "timeout": "300.0"}

    response = requests.post(url, files=files, data=data)
    print(response.status_code)
    with open(p, "rb") as f:
        resp = requests.post(
            url,
            files={"file": (p.name, f, "application/octet-stream")},
            data={"timeout": "300"},
            timeout=(10, 600),
        )
    resp.raise_for_status()

    cd = resp.headers.get("content-disposition", "")
    m = re.search(r'filename="([^"]+)"', cd)
    fname = m.group(1) if m else f"{p.stem}.glb"
    out_file = out_dir / fname
    out_file.write_bytes(resp.content)
    return str(out_file)

# url = "https://8188-hah9c53y9.brevlab.com/upload/image" # todo: remove hardcoding

# with open(p, "rb") as f:
#     files = {"file": f}  # or use the correct key your endpoint expects
#     response = requests.post(url, files=files)
# print(response.status_code)
# # Infer object properties
# properties = get_object_properties(str(p))
# out = out_dir / f"{p.stem}_properties.json"
# out.write_text(str(properties))

# process
# img = cv2.imread(str(p), cv2.IMREAD_COLOR)
# if img is None:
#     fail = out_dir / f"{p.stem}_FAILED.txt"
#     fail.write_text("Could not read uploaded image.")
#     return str(fail)

# # Example processing: resize to thumbnail and save
# h, w = img.shape[:2]
# scale = 256 / max(h, w)
# new_size = (int(w * scale), int(h * scale))
# thumb = cv2.resize(img, new_size, interpolation=cv2.INTER_AREA)
# out = out_dir / f"{p.stem}_thumb.jpg"
# cv2.imwrite(str(out), thumb)

# return str(out)
