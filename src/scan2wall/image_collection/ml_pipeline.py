from pathlib import Path
import cv2
import numpy as np
from scan2wall.material_properties.get_object_properties import get_object_properties
import requests
import re
import subprocess
import os

IS_DEMO = False
USE_LLM = True

def get_3d_model(image_path, job_id, is_demo=False):
    url = "https://8012-hah9c53y9.brevlab.com/process"
    with open(image_path, "rb") as f:
        resp = requests.post(
            url,
            files={"file": (image_path.name, f, "application/octet-stream")},
            data={"timeout": "300", "job_id": job_id},
            timeout=(10, 600)
        )
    resp.raise_for_status()
    return resp

def process_image(job_id: str, image_path: str) -> str:
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
    resp = get_3d_model(p, job_id, IS_DEMO)
    out_file = out_dir / f"{job_id}.glb"
    out_file.write_bytes(resp.content)

    mass = 1.0
    df = None
    ds = None
    scaling = 1.0
    if USE_LLM:
        props = get_object_properties(image_path)
        print(props)
        mass = props["weight_kg"]["value"]
        df = props["friction_coefficients"]["dynamic"]
        ds = props["friction_coefficients"]["static"]
        scaling = max(props["length"]["value"], props["width"]["value"], props["height"]["value"])

    usd_file = convert_mesh(out_file, f"{job_id}.glb", mass=1.0, df=None, ds=None)
    make_throwing_anim(usd_file, scaling)
    return str(out_file)

def convert_mesh(out_file, fname, mass=None, df=None, ds=None):
    fname_new = fname.replace(".glb", ".usd")
    print(fname_new)
    m = f"--mass {mass}" if mass else ""
    ds = f"--static-friction {ds}" if ds else ""
    df = f"--dynamic-friction {df}" if df else ""
    
    os.system(f"/bin/bash -lic 'python /workspace/isaaclab/scripts/convert_mesh_custom.py {out_file} /workspace/isaaclab/{fname_new} --kit_args='--headless' {m} {df} {ds}'")
    print("Conversion done")
    return f"/workspace/isaaclab/{fname_new}"
    
    # other options
    #    --collision-approximation convexHull   --mass 0.35   --com 0 0 0   --inertia 0.00195 0.00195 0.000246   --principal-axes 1 0 0 0   --static-friction 0.6   --dynamic-friction 0.5   --restitution 0.2   --friction-combine average   --restitution-combine min")

def make_throwing_anim(file, scaling=1.0):
    command = f"/bin/bash -lic \"python /workspace/isaaclab/scripts/test_place_obj_video.py --video --usd_path_abs '{file}' --kit_args='--no-window' --scaling_factor {scaling} \""
    os.system(command)

if __name__ == "__main__":
    pass 
    # debugging stuff
    # dir = "/workspace/scan2wall/src/scan2wall/image_collection/processed/"
    # fname = "job_83e55f3895054f8cbd92cb979029a82e.glb"
    # convert_mesh(dir + fname, fname)
    # process_image("4b3df0f54ab641a7826b609fea240902", "uploads/20251011-230601-4f7bd7-0.png")
    # make_throwing_anim("/workspace/isaaclab/sample.usd")
