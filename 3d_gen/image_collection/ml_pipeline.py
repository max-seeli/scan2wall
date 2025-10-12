from pathlib import Path
import cv2
import numpy as np
from scan2wall.material_properties.get_object_properties import get_object_properties
from scan2wall.utils.paths import (
    get_isaac_scripts_dir,
    get_assets_csv,
    get_usd_output_dir,
)
import requests
import re
import subprocess
import os

USE_LLM = True
USE_SCALING = True


def process_image(job_id: str, image_path: str) -> str:
    """
    Process uploaded image through the full pipeline:
    1. Generate 3D mesh via ComfyUI API
    2. Infer material properties via Gemini
    3. Convert mesh to USD with physics properties
    4. Trigger Isaac Sim simulation

    Args:
        job_id: Unique identifier for this job
        image_path: Path to uploaded image

    Returns:
        Path to generated GLB file
    """
    p = Path(image_path)
    out_dir = p.parent.parent / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Generate 3D mesh via ComfyUI API
    ISAAC_INSTANCE_ADDRESS = os.getenv("ISAAC_INSTANCE_ADDRESS")

    if ISAAC_INSTANCE_ADDRESS is None:
        raise ValueError("ISAAC_INSTANCE_ADDRESS environment variable not set!")

    url = ISAAC_INSTANCE_ADDRESS
    with open(p, "rb") as f:
        resp = requests.post(
            url,
            files={"file": (p.name, f, "application/octet-stream")},
            data={"timeout": "300", "job_id": job_id},
            timeout=(10, 600),
        )
    print("3D mesh generation request done.")
    resp.raise_for_status()

    out_file = out_dir / f"{job_id}.glb"
    out_file.write_bytes(resp.content)

    # Initialize material properties with defaults
    mass = 1.0
    df = None  # dynamic friction
    ds = None  # static friction
    scaling = 1.0

    # Infer material properties using Gemini if enabled
    if USE_LLM:
        props = get_object_properties(image_path)
        print(f"Material properties inferred: {props}")
        mass = props["weight_kg"]["value"]
        df = props["friction_coefficients"]["dynamic"]
        ds = props["friction_coefficients"]["static"]
        scaling = max(
            props["dimensions_m"]["length"]["value"],
            props["dimensions_m"]["width"]["value"],
            props["dimensions_m"]["height"]["value"],
        )

    if not USE_SCALING:
        scaling = 1.0

    # Convert GLB mesh to USD with physics properties
    usd_file = convert_mesh(out_file, f"{job_id}.glb", mass=mass, df=df, ds=ds)
    print(f"Mesh converted to USD: {usd_file}")

    # Log properties to CSV
    if USE_LLM:
        assets_csv = get_assets_csv()
        # Create CSV with header if it doesn't exist
        if not assets_csv.exists():
            assets_csv.parent.mkdir(parents=True, exist_ok=True)
            with open(assets_csv, "w") as f:
                f.write("object_type,scaling,mass,usd_path\n")

        with open(assets_csv, "a") as f:
            f.write(f"{props['object_type']},{scaling},{mass},{usd_file}\n")

    # Trigger Isaac Sim simulation
    make_throwing_anim(usd_file, scaling)

    return str(out_file)


def convert_mesh(out_file: Path, fname: str, mass=None, df=None, ds=None) -> str:
    """
    Convert GLB mesh to USD format with physics properties.

    Args:
        out_file: Path to input GLB file
        fname: Output filename
        mass: Mass in kg
        df: Dynamic friction coefficient
        ds: Static friction coefficient

    Returns:
        Path to generated USD file
    """
    fname_new = fname.replace(".glb", ".usd")
    print(f"Converting {fname} to {fname_new}...")

    # Build command arguments
    m = f"--mass {mass}" if mass else ""
    ds_arg = f"--static-friction {ds}" if ds else ""
    df_arg = f"--dynamic-friction {df}" if df else ""

    # Get paths from configuration
    isaac_scripts = get_isaac_scripts_dir()
    usd_output = get_usd_output_dir()
    convert_script = isaac_scripts / "convert_mesh.py"
    output_path = usd_output / fname_new

    # Ensure output directory exists
    usd_output.mkdir(parents=True, exist_ok=True)

    cmd = (
        f"python {convert_script} "
        f"{out_file} {output_path} "
        f"--kit_args='--headless' {m} {df_arg} {ds_arg}"
    )

    # Spawn conversion process
    proc = subprocess.Popen(
        ["/bin/bash", "-lic", cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=True,
    )

    # Stream output in real-time
    for line in proc.stdout:
        print(line, end="")

    proc.wait()

    if proc.returncode != 0:
        raise RuntimeError(f"Mesh conversion failed with return code {proc.returncode}")

    print("Mesh conversion complete!")
    return str(output_path)


def make_throwing_anim(file: str, scaling: float = 1.0):
    """
    Trigger Isaac Sim throwing animation simulation.

    Args:
        file: Path to USD file
        scaling: Scaling factor for the object
    """
    print("Creating throwing animation simulation...")

    isaac_scripts = get_isaac_scripts_dir()
    sim_script = isaac_scripts / "test_place_obj_video.py"

    cmd = (
        f"python {sim_script} "
        f"--video --usd_path_abs '{file}' --scaling_factor {scaling} --kit_args='--no-window'"
    )

    # Spawn simulation in background (fire-and-forget)
    subprocess.Popen(
        ["/bin/bash", "-lic", cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    print("Simulation triggered in background!")


if __name__ == "__main__":
    # Test/debug code
    pass
