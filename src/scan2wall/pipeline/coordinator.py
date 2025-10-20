from pathlib import Path
import cv2
import numpy as np
from scan2wall.inference.get_object_properties import get_object_properties
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

    img = next(Path(image_path).glob("*"), None)
    if img is None:
        raise FileNotFoundError(f"No image found in {image_path}")

    # Generate 3D mesh via ComfyUI API
    status.start("🎨 Creating 3D mesh with ComfyUI (Hunyuan 3D)...")
    print("=" * 60)
    print("Starting 3D mesh generation via ComfyUI...")
    print("=" * 60)

    glb_path = generate_mesh_via_comfyui(img, job_id)

    print(f"✓ 3D mesh generated: {glb_path}")
    status.stop("✓ 3D mesh created successfully (all assets ready)")

    # Update jobs dict to indicate assets are available
    if jobs_dict and job_id in jobs_dict:
        jobs_dict[job_id]["assets_generated"] = True

    # Initialize material properties with defaults
    mass = 1.0
    df = None  # dynamic friction
    ds = None  # static friction
    scaling = 1.0

    # Infer material properties using Gemini if enabled
    if USE_LLM:
        status.start("🧠 Inferring physical properties with Gemini AI...")
        print("\nInferring material properties with Gemini...")
        props = get_object_properties(img)
        
        props_file = Path(image_path) / "properties.json"
        with open(str(props_file), 'w') as f:
            json.dump(props, f, indent=2)

        print(f"✓ Saved properties to {props_file}")

        # Update jobs dict to indicate properties are available
        if jobs_dict and job_id in jobs_dict:
            jobs_dict[job_id]["properties_generated"] = True

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
    # Navigate to project root, then to 3d_gen/
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    comfy_input_dir = Path(os.getenv("COMFY_INPUT_DIR", project_root / "3d_gen" / "ComfyUI" / "input"))
    comfy_output_dir = Path(os.getenv("COMFY_OUTPUT_DIR", project_root / "3d_gen" / "ComfyUI" / "output"))
    workflow_path = project_root / "3d_gen" / "ComfyUI" / "custom_nodes" / "ComfyUI-MeshCraft" / "workflows" / "image-to-texture-mesh-api.json"

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

    # Poll for completion with progressive file copying
    print("Waiting for ComfyUI to generate mesh...")
    print("(Files will appear progressively as they're created...)")

    max_wait = 600  # 10 minutes max
    start_time = time.time()
    copied_files = set()
    processed_dir = Path(image_path).parent

    while time.time() - start_time < max_wait:
        # Check for new files in ComfyUI output directory
        new_files = list(comfy_output_dir.glob(f"{job_id}*"))

        for file_path in new_files:
            if file_path.name not in copied_files and file_path.exists():
                # Copy immediately to job directory
                final_path = processed_dir / file_path.name
                try:
                    shutil.copy2(file_path, final_path)
                    copied_files.add(file_path.name)
                    print(f"\n✓ Copied: {file_path.name}")
                except Exception as e:
                    print(f"\n⚠ Failed to copy {file_path.name}: {e}")

        # Check if workflow is complete
        history_response = requests.get(f"{comfy_url}/history/{prompt_id}")

        if history_response.status_code == 200:
            history = history_response.json()

            if prompt_id in history:
                prompt_history = history[prompt_id]

                # Check if completed
                if "outputs" in prompt_history:
                    print("\n✓ ComfyUI generation complete!")

                    # Final sweep for any remaining files
                    for file_path in comfy_output_dir.glob(f"{job_id}*"):
                        if file_path.name not in copied_files and file_path.exists():
                            final_path = processed_dir / file_path.name
                            try:
                                shutil.copy2(file_path, final_path)
                                print(f"✓ Final copy: {file_path.name}")
                            except Exception as e:
                                print(f"⚠ Failed final copy {file_path.name}: {e}")

                    glb_filename = job_id+'.glb'
                    glb_path = processed_dir / glb_filename
                    return str(glb_path)

        # Wait before polling again (shorter interval for faster response)
        time.sleep(2)
        print(".", end="", flush=True)

    raise TimeoutError(f"ComfyUI mesh generation timed out after {max_wait}s")


def convert_mesh(out_file: Path, fname: str, mass=None, df=None, ds=None) -> str:
    """
    Convert GLB mesh to USD format via the persistent Isaac worker API.
    """
    fname_new = fname.replace(".glb", ".usd")
    print(f"Converting {fname} → {fname_new} via Isaac worker...")

    usd_dir = out_file.parent
    
    container_glb_path = str(out_file).replace(
        "/home/ubuntu/scan2wall/data", "/workspace/s2w-data"
    )
    container_usd_dir = str(usd_dir).replace(
        "/home/ubuntu/scan2wall/data", "/workspace/s2w-data"
    )

    payload = {
        "asset_path": container_glb_path,
        "usd_dir": container_usd_dir,
        "mass": mass,
        "static_friction": ds,
        "dynamic_friction": df,
    }

    # Send the conversion request to the persistent worker
    try:
        r = requests.post("http://localhost:8090/convert", json=payload, timeout=600)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Mesh conversion failed: {e}")

    print("✅ Mesh conversion complete.")
    return container_usd_dir + '/' + fname_new


def make_throwing_anim(file: str, scaling: float = 1.0, job_id: str = None, status_updater=None):
    """
    Trigger Isaac worker to run the throwing simulation and generate a video.
    """
    print("🎬 Creating throwing animation via Isaac worker...")

    container_usd_path = file.replace("/home/ubuntu/scan2wall", "/workspace")
    out_dir = str(Path(container_usd_path).parent)

    payload = {
        "usd_path": container_usd_path,
        "out_dir": out_dir,
        "video": True,
        "video_length": 200,
        "fps": 50,
        "scaling_factor": scaling,
        "job_id": job_id,  # Pass job_id for video naming
    }
    
    try:
        r = requests.post("http://localhost:8090/run_simulation", json=payload, timeout=1800)
        r.raise_for_status()
        result = r.json()

        # Get container path and convert to host path
        # Video should be saved as {job_id}_sim.mp4 in the job directory
        container_video = result.get("video_path", f"{out_dir}/{job_id}_sim.mp4")
        host_video = container_video.replace("/workspace/s2w-data", "/home/ubuntu/scan2wall/data")

        print(f"✅ Video ready: {host_video}")
        return host_video
    except Exception as e:
        raise RuntimeError(f"Simulation failed: {e}")

if __name__ == "__main__":
    # Test/debug code
    pass
