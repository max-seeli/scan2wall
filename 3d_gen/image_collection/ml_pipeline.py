from pathlib import Path
import cv2
import numpy as np
import sys
from pathlib import Path as PathLib
# Add parent directory to path to import from 3d_gen
sys.path.insert(0, str(PathLib(__file__).parent.parent))
from material_properties.get_object_properties import get_object_properties
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
import threading
import glob

USE_LLM = True
USE_SCALING = True


class StatusUpdater:
    """Helper class to update status with elapsed time counter."""

    def __init__(self, jobs_dict, job_id):
        self.jobs_dict = jobs_dict
        self.job_id = job_id
        self.start_time = None
        self.base_message = ""
        self.running = False
        self.thread = None

    def start(self, message):
        """Start updating status with time counter."""
        self.base_message = message
        self.start_time = time.time()
        self.running = True

        # Immediately set the initial message
        self._update_status()

        # Start background thread to update every second
        self.thread = threading.Thread(target=self._update_loop, daemon=True)
        self.thread.start()

    def stop(self, final_message=None):
        """Stop the time counter and optionally set final message."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)

        if final_message:
            if self.jobs_dict and self.job_id in self.jobs_dict:
                self.jobs_dict[self.job_id]["status_detail"] = final_message
            print(final_message)

    def _update_loop(self):
        """Background loop to update status every second."""
        while self.running:
            time.sleep(1)
            if self.running:
                self._update_status()

    def _update_status(self):
        """Update status with elapsed time."""
        if self.start_time:
            elapsed = int(time.time() - self.start_time)
            message = f"{self.base_message} ({elapsed}s)"
            if self.jobs_dict and self.job_id in self.jobs_dict:
                self.jobs_dict[self.job_id]["status_detail"] = message
            # Don't print every update to avoid spam


def process_image(job_id: str, image_path: str, jobs_dict: dict = None) -> str:
    """
    Process uploaded image through the full pipeline:
    1. Generate 3D mesh via ComfyUI API
    2. Infer material properties via Gemini
    3. Convert mesh to USD with physics properties
    4. Trigger Isaac Sim simulation

    Args:
        job_id: Unique identifier for this job
        image_path: Path to uploaded image
        jobs_dict: Reference to JOBS dict for status updates

    Returns:
        Path to generated GLB file
    """
    # Create status updater
    status = StatusUpdater(jobs_dict, job_id)

    p = Path(image_path)
    out_dir = p.parent.parent / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Generate 3D mesh via ComfyUI API
    status.start("🎨 Creating 3D mesh with ComfyUI (Hunyuan 3D)...")
    print("=" * 60)
    print("Starting 3D mesh generation via ComfyUI...")
    print("=" * 60)

    glb_path = generate_mesh_via_comfyui(image_path, job_id)
    print(f"✓ 3D mesh generated: {glb_path}")
    status.stop("✓ 3D mesh created successfully")

    # Initialize material properties with defaults
    mass = 1.0
    df = None  # dynamic friction
    ds = None  # static friction
    scaling = 1.0

    # Infer material properties using Gemini if enabled
    if USE_LLM:
        status.start("🧠 Inferring physical properties with Gemini AI...")
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
        status.stop(f"✓ Physical properties inferred (mass: {mass}kg)")

    if not USE_SCALING:
        scaling = 1.0

    # Convert GLB mesh to USD with physics properties
    status.start("🔧 Converting mesh to USD format...")
    print("\nConverting mesh to USD format...")
    usd_file = convert_mesh(Path(glb_path), f"{job_id}.glb", mass=mass, df=df, ds=ds)
    print(f"✓ Mesh converted to USD: {usd_file}")
    status.stop("✓ Mesh converted to USD with physics properties")

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

    # Trigger Isaac Sim simulation and wait for completion
    status.start("🎮 Running simulation in Isaac Sim...")
    print("\nTriggering Isaac Sim simulation...")
    video_path = make_throwing_anim(usd_file, scaling, job_id, status)
    print(f"✓ Simulation complete! Video: {video_path}")
    status.stop("✅ Done!")

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
    comfy_input_dir = Path(os.getenv("COMFY_INPUT_DIR", Path(__file__).parent.parent / "ComfyUI" / "input"))
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
    if response.status_code != 200:
        print(f"[ERROR] Status: {response.status_code}")
        print(f"[ERROR] Response: {response.text}")
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

    # Convert host paths to container paths
    # Host: /home/ubuntu/scan2wall/... → Container: /workspace/scan2wall/...
    container_glb_path = str(out_file).replace("/home/ubuntu/scan2wall", "/workspace/scan2wall")
    container_output_path = str(output_path).replace("/home/ubuntu/scan2wall", "/workspace")
    container_convert_script = "/workspace/scan2wall/scan2wall/isaac_scripts/convert_mesh.py"

    # Use isaaclab.sh wrapper to properly initialize Isaac Sim environment (in Docker)
    cmd = (
        f"docker exec vscode bash -c '"
        f"cd /workspace/isaaclab && "
        f"./isaaclab.sh -p {container_convert_script} "
        f"{container_glb_path} {container_output_path} "
        f"--kit_args=\"--headless\" {m} {df_arg} {ds_arg}"
        f"'"
    )

    print(f"Running command: {cmd}")

    # Spawn conversion process (don't capture output to avoid pipe deadlock)
    # Isaac Sim produces massive amounts of output that can fill the pipe buffer
    proc = subprocess.Popen(
        ["/bin/bash", "-c", cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Wait for completion
    proc.wait()

    if proc.returncode != 0:
        raise RuntimeError(f"Mesh conversion failed with return code {proc.returncode}")

    # Verify USD file was created
    if not output_path.exists():
        raise RuntimeError(f"USD file was not created: {output_path}")

    print("Mesh conversion complete!")
    return str(output_path)


def make_throwing_anim(file: str, scaling: float = 1.0, job_id: str = None, status_updater: StatusUpdater = None):
    """
    Trigger Isaac Sim throwing animation simulation and wait for completion.

    Args:
        file: Path to USD file
        scaling: Scaling factor for the object
        job_id: Job ID for video filename
        status_updater: StatusUpdater instance for progress updates

    Returns:
        Path to generated video file
    """
    print("Creating throwing animation simulation...")

    # Generate video filename with job ID and timestamp
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    video_name = f"sim_{job_id}_{timestamp}.mp4" if job_id else "sim_run.mp4"

    # Convert host paths to container paths
    container_usd_path = file.replace("/home/ubuntu/scan2wall", "/workspace")
    container_sim_script = "/workspace/scan2wall/scan2wall/isaac_scripts/test_place_obj_video.py"

    # Use isaaclab.sh wrapper to properly initialize Isaac Sim environment (in Docker)
    cmd = (
        f"docker exec vscode bash -c '"
        f"cd /workspace/isaaclab && "
        f"./isaaclab.sh -p {container_sim_script} "
        f"--video "
        f"--video_name {video_name} "
        f"--out_dir /workspace/recordings "
        f"--usd_path_abs \"{container_usd_path}\" "
        f"--scaling_factor {scaling} "
        f"--kit_args=\"--no-window --no-rendering\""
        f"'"
    )

    print(f"Running command: {cmd}")

    # Spawn simulation in background
    subprocess.Popen(
        ["/bin/bash", "-c", cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    print("Simulation triggered in background!")

    # Wait for video file to appear
    recordings_dir = Path("/home/ubuntu/scan2wall/recordings")
    video_pattern = f"sim_{job_id}_*.mp4" if job_id else "sim_run.mp4"
    max_wait = 300  # 5 minutes max
    poll_interval = 2  # Check every 2 seconds

    print(f"Waiting for video file: {video_pattern}")
    start_time = time.time()

    while time.time() - start_time < max_wait:
        # Look for the video file
        video_files = list(recordings_dir.glob(video_pattern))
        if video_files:
            video_path = video_files[0]
            # Check that file is not empty and not being written to
            if video_path.stat().st_size > 0:
                # Wait a bit more to ensure file write is complete
                time.sleep(2)
                print(f"✓ Video file found: {video_path}")
                return str(video_path)

        time.sleep(poll_interval)

    # Timeout
    raise TimeoutError(f"Video file did not appear within {max_wait} seconds")


if __name__ == "__main__":
    # Test/debug code
    pass
