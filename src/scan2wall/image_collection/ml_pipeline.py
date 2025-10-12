from pathlib import Path
import cv2
import numpy as np
from scan2wall.material_properties.get_object_properties import get_object_properties
import requests
import re
import subprocess
import os

USE_LLM = True
USE_SCALING = False

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
    url = "https://8012-hah9c53y9.brevlab.com/process" # TODO: un-hardcode
    with open(p, "rb") as f:
        resp = requests.post(
            url,
            files={"file": (p.name, f, "application/octet-stream")},
            data={"timeout": "300", "job_id": job_id},
            timeout=(10, 600),
        )
    print("Request done.")
    resp.raise_for_status()
    out_file = out_dir / f"{job_id}.glb"
    print(out_file)
    out_file.write_bytes(resp.content)

    mass = 1.0
    df = None
    ds = None
    scaling = 1.0
    print("1")

    if USE_LLM:
        props = get_object_properties(image_path)
        print(props)
        mass = props["weight_kg"]["value"]
        df = props["friction_coefficients"]["dynamic"]
        ds = props["friction_coefficients"]["static"]
        scaling = max(props["dimensions_m"]["length"]["value"], props["dimensions_m"]["width"]["value"], props["dimensions_m"]["height"]["value"])
    if not USE_SCALING:
        scaling = 1.0
    usd_file = convert_mesh(out_file, f"{job_id}.glb", mass=mass, df=df, ds=ds)
    make_throwing_anim(usd_file)
    return str(out_file)

def convert_mesh(out_file, fname, mass=None, df=None, ds=None):
    fname_new = fname.replace(".glb", ".usd")
    print(fname_new)
    m = f"--mass {mass}" if mass else ""
    ds = f"--static-friction {ds}" if ds else ""
    df = f"--dynamic-friction {df}" if df else ""

    cmd = (
        f"python /workspace/scan2wall/isaac_scripts/convert_mesh.py "
        f"{out_file} /workspace/isaaclab/{fname_new} "
        f"--kit_args='--headless' {m} {df} {ds}"
    )

    # Spawn in a new process group (detached), but keep a handle to wait later
    proc = subprocess.Popen(
        ["/bin/bash", "-lic", cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # detaches from parent session
        text=True
    )

    for line in proc.stdout:
        print(line, end="")  # stream live output

    proc.wait()

    print("conversion done :)")
    return f"/workspace/isaaclab/{fname_new}"
    #    --collision-approximation convexHull   --mass 0.35   --com 0 0 0   --inertia 0.00195 0.00195 0.000246   --principal-axes 1 0 0 0   --static-friction 0.6   --dynamic-friction 0.5   --restitution 0.2   --friction-combine average   --restitution-combine min")

def make_throwing_anim(file, scaling=1.0):
    print("Creating throwing anim")
    cmd = (
        f"python /workspace/scan2wall/isaac_scripts/test_place_obj_video.py "
        f"--video --usd_path_abs '{file}' --scaling_factor {scaling} --kit_args='--no-window'"
    )
    subprocess.Popen(
        ["/bin/bash", "-lic", cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True  # fully detached from parent
    )
    print("DONE! :)")

if __name__ == "__main__":
    # dir = "/workspace/scan2wall/src/scan2wall/image_collection/processed/"
    # fname = "job_83e55f3895054f8cbd92cb979029a82e.glb"
    # convert_mesh(dir + fname, fname)
    process_image("4b3df0f54ab641a7826b609fea240902", "uploads/20251011-222124-4562cb-IMG_0451.png")
    # make_throwing_anim("/workspace/isaaclab/ab015dc2cdcd4a44a647952fc9a854bb.usd")
