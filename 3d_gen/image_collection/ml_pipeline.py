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
import json
import time
import shutil
import uuid

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
    print("=" * 60)
    print("Starting 3D mesh generation via ComfyUI...")
    print("=" * 60)

    glb_path = generate_mesh_via_comfyui(image_path, job_id)
    print(f"✓ 3D mesh generated: {glb_path}")

    # Initialize material properties with defaults
    mass = 1.0
    df = None  # dynamic friction
    ds = None  # static friction
    scaling = 1.0

    # Infer material properties using Gemini if enabled
    if USE_LLM:
        print("\nInferring material properties with Gemini...")
        props = get_object_properties(image_path)
        print(f"✓ Material properties: {props}")
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
    print("\nConverting mesh to USD format...")
    usd_file = convert_mesh(Path(glb_path), f"{job_id}.glb", mass=mass, df=df, ds=ds)
    print(f"✓ Mesh converted to USD: {usd_file}")

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
    print("\nTriggering Isaac Sim simulation...")
    make_throwing_anim(usd_file, scaling)
    print("✓ Simulation started!")

    print("=" * 60)
    print("Pipeline complete!")
    print("=" * 60)

    return str(glb_path)


def generate_mesh_via_comfyui(image_path: str, job_id: str) -> str:
    """
    Generate 3D mesh using ComfyUI's API directly.

    Args:
        image_path: Path to input image
        job_id: Unique job identifier

    Returns:
        Path to generated GLB file
    """
    # Configuration
    comfy_url = os.getenv("COMFY_URL", "http://127.0.0.1:8188")
    comfy_input_dir = Path(os.getenv("COMFY_INPUT_DIR", Path(__file__).parent.parent / "input"))
    comfy_output_dir = Path(os.getenv("COMFY_OUTPUT_DIR", Path(__file__).parent.parent / "ComfyUI" / "output"))
    workflow_path = Path(__file__).parent.parent / "workflows" / "api_prompt_strcnst.json"

    # Ensure directories exist
    comfy_input_dir.mkdir(parents=True, exist_ok=True)
    comfy_output_dir.mkdir(parents=True, exist_ok=True)

    # Copy image to ComfyUI input directory with unique name
    image_filename = f"{job_id}_{Path(image_path).name}"
    dest_image_path = comfy_input_dir / image_filename
    shutil.copy2(image_path, dest_image_path)
    print(f"✓ Image copied to ComfyUI input: {dest_image_path}")

    # Load workflow template
    with open(workflow_path, "r") as f:
        workflow = json.load(f)

    # Update workflow with image filename (node 112 is LoadImage)
    workflow["112"]["inputs"]["image"] = image_filename

    # Update filename prefix for output (node 89 is the output filename)
    workflow["89"]["inputs"]["string"] = job_id

    print(f"✓ Workflow configured for job {job_id}")

    # Queue the prompt to ComfyUI
    print("Queueing workflow to ComfyUI...")
    prompt_data = {
        "prompt": workflow,
        "client_id": job_id
    }

    response = requests.post(f"{comfy_url}/prompt", json=prompt_data)
    response.raise_for_status()

    result = response.json()
    prompt_id = result["prompt_id"]
    print(f"✓ Workflow queued with prompt_id: {prompt_id}")

    # Poll for completion
    print("Waiting for ComfyUI to generate mesh...")
    print("(This may take 30-60 seconds...)")

    max_wait = 600  # 10 minutes max
    start_time = time.time()

    while time.time() - start_time < max_wait:
        # Check history for this prompt
        history_response = requests.get(f"{comfy_url}/history/{prompt_id}")

        if history_response.status_code == 200:
            history = history_response.json()

            if prompt_id in history:
                prompt_history = history[prompt_id]

                # Check if completed
                if "outputs" in prompt_history:
                    print("✓ ComfyUI generation complete!")

                    # Find the output GLB file
                    # Look for node 89 (SaveModel) outputs
                    for node_id, node_output in prompt_history["outputs"].items():
                        if "glb" in node_output or "meshes" in node_output:
                            # The output structure varies, try to find the GLB filename
                            if "meshes" in node_output:
                                files = node_output["meshes"]
                                if files and len(files) > 0:
                                    glb_filename = files[0].get("filename", "")
                                    if glb_filename:
                                        glb_path = comfy_output_dir / glb_filename
                                        if glb_path.exists():
                                            # Move to processed directory
                                            processed_dir = Path(image_path).parent.parent / "processed"
                                            processed_dir.mkdir(parents=True, exist_ok=True)
                                            final_path = processed_dir / f"{job_id}.glb"
                                            shutil.copy2(glb_path, final_path)
                                            return str(final_path)

                    # Fallback: search output directory for recent GLB files
                    print("Searching output directory for GLB file...")
                    glb_files = list(comfy_output_dir.glob(f"*{job_id}*.glb"))

                    if not glb_files:
                        # Try finding any recent GLB
                        glb_files = sorted(
                            comfy_output_dir.glob("*.glb"),
                            key=lambda p: p.stat().st_mtime,
                            reverse=True
                        )

                    if glb_files:
                        glb_path = glb_files[0]
                        processed_dir = Path(image_path).parent.parent / "processed"
                        processed_dir.mkdir(parents=True, exist_ok=True)
                        final_path = processed_dir / f"{job_id}.glb"
                        shutil.copy2(glb_path, final_path)
                        return str(final_path)

                    raise RuntimeError(f"ComfyUI completed but no GLB file found in {comfy_output_dir}")

        # Wait before polling again
        time.sleep(5)
        print(".", end="", flush=True)

    raise TimeoutError(f"ComfyUI mesh generation timed out after {max_wait}s")


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
