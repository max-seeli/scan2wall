from pathlib import Path
import cv2
import numpy as np
from scan2wall.inference.get_object_properties import get_object_properties, validate_segmentation
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
from concurrent.futures import ThreadPoolExecutor, as_completed

USE_LLM = True
USE_SCALING = True


def run_parallel_segmentation_and_validation(image_path: str, job_id: str) -> dict:
    """
    Run both SAM and Inspyre segmentations in parallel, then validate both with Gemini.

    This is the production code path used by both the server and test CLI.

    Args:
        image_path: Path to input image
        job_id: Unique job identifier

    Returns:
        dict with keys:
            - 'status': 'accepted' or 'rejected'
            - 'method': 'SAM' or 'Inspyre' or None (if rejected)
            - 'cropped': Path to accepted cropped image (if accepted)
            - 'concatenated': Path to accepted concatenated image (if accepted)
            - 'properties': Physical properties dict (if accepted)
            - 'sam_validation': SAM validation result
            - 'inspyre_validation': Inspyre validation result
            - 'sam_time': SAM segmentation time
            - 'inspyre_time': Inspyre segmentation time
            - 'gemini_time': Total Gemini inference time
            - 'total_time': Total time
    """
    import time

    start_time = time.time()

    # Stage 1: Run BOTH segmentations in parallel
    print("Running both segmentations in parallel (SAM + Inspyre)...")
    seg_start = time.time()
    with ThreadPoolExecutor(max_workers=2) as executor:
        sam_future = executor.submit(run_segmentation_workflow, "SAM_seg_cropped.json", image_path, job_id)
        inspyre_future = executor.submit(run_segmentation_workflow, "inspyre_seg_cropped.json", image_path, job_id)

        sam_result = sam_future.result()
        inspyre_result = inspyre_future.result()
    seg_elapsed = time.time() - seg_start

    print(f"✓ Both segmentations complete in {seg_elapsed:.2f}s")

    # Stage 2: Run 4 Gemini calls in parallel (validation + properties for each method)
    print("Running 4 parallel Gemini inferences (validation + properties)...")
    gemini_start = time.time()
    with ThreadPoolExecutor(max_workers=4) as executor:
        # Submit all 4 tasks
        sam_val_future = executor.submit(validate_segmentation, sam_result['concatenated'])
        sam_props_future = executor.submit(get_object_properties, sam_result['concatenated'])
        inspyre_val_future = executor.submit(validate_segmentation, inspyre_result['concatenated'])
        inspyre_props_future = executor.submit(get_object_properties, inspyre_result['concatenated'])

        # Wait for all to complete
        sam_validation = sam_val_future.result()
        sam_props = sam_props_future.result()
        inspyre_validation = inspyre_val_future.result()
        inspyre_props = inspyre_props_future.result()
    gemini_elapsed = time.time() - gemini_start

    print(f"✓ All Gemini inferences complete in {gemini_elapsed:.2f}s (4 calls in parallel)")
    print(f"  SAM validation: {sam_validation.get('decision')} - {sam_validation.get('description')}")
    print(f"  Inspyre validation: {inspyre_validation.get('decision')} - {inspyre_validation.get('description')}")

    total_elapsed = time.time() - start_time

    # Stage 3: Pick the best result (prefer SAM, fallback to Inspyre)
    result = {
        'sam_result': sam_result,
        'inspyre_result': inspyre_result,
        'sam_validation': sam_validation,
        'inspyre_validation': inspyre_validation,
        'sam_props': sam_props,
        'inspyre_props': inspyre_props,
        'sam_time': seg_elapsed,  # Both run in parallel, so time is same
        'inspyre_time': seg_elapsed,
        'gemini_time': gemini_elapsed,
        'total_time': total_elapsed
    }

    if sam_validation.get('decision') == "ACCEPT":
        print("✓ SAM segmentation ACCEPTED (using SAM result)")
        result.update({
            'status': 'accepted',
            'method': 'SAM',
            'cropped': sam_result['cropped'],
            'concatenated': sam_result['concatenated'],
            'properties': sam_props
        })
    elif inspyre_validation.get('decision') == "ACCEPT":
        print("✓ Inspyre segmentation ACCEPTED (using Inspyre result)")
        result.update({
            'status': 'accepted',
            'method': 'Inspyre',
            'cropped': inspyre_result['cropped'],
            'concatenated': inspyre_result['concatenated'],
            'properties': inspyre_props
        })
    else:
        print("❌ Both SAM and Inspyre segmentations REJECTED")
        result.update({
            'status': 'rejected',
            'method': None,
            'cropped': None,
            'concatenated': None,
            'properties': None
        })

    return result


def extract_physics_properties(props: dict, use_scaling: bool = True) -> tuple:
    """
    Extract physics properties from Gemini inference result.

    Handles missing fields gracefully with defaults.

    Args:
        props: Properties dict from get_object_properties() or loaded from cache
        use_scaling: Whether to compute real-world scaling from dimensions

    Returns:
        tuple: (mass, dynamic_friction, static_friction, restitution, scaling)
               All values are floats. Returns defaults if properties missing.

               Default values:
               - mass: 1.0 kg
               - dynamic_friction: 0.5
               - static_friction: 0.6
               - restitution: 0.5
               - scaling: 1.0 meters (max dimension)
    """
    # Extract with safe defaults
    mass = props.get("weight_kg", {}).get("value", 1.0)
    df = props.get("friction_coefficients", {}).get("dynamic", 0.5)
    ds = props.get("friction_coefficients", {}).get("static", 0.6)
    restitution = props.get("restitution", {}).get("value", 0.5)

    # Compute scaling from dimensions if available
    scaling = 1.0  # Default
    if use_scaling and props and "error" not in props:
        dims = props.get("dimensions_m", {})
        length = dims.get("length", {}).get("value", 0)
        width = dims.get("width", {}).get("value", 0)
        height = dims.get("height", {}).get("value", 0)

        if length > 0 or width > 0 or height > 0:
            scaling = max(length, width, height)

    return mass, df, ds, restitution, scaling


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

    # Run parallel segmentation and validation (shared production code path)
    status.start("🔍 Running parallel segmentation and validation...")
    print("=" * 60)
    print("Starting parallel segmentation pipeline...")
    print("=" * 60)

    seg_result = run_parallel_segmentation_and_validation(str(img), job_id)

    status.stop(f"✓ Segmentation complete ({seg_result['total_time']:.1f}s)")

    # Check if segmentation was accepted
    if seg_result['status'] != 'accepted':
        # Both segmentations failed
        print("=" * 60)
        print("❌ Both SAM and Inspyre segmentations REJECTED")
        print(f"  SAM: {seg_result['sam_validation'].get('description')}")
        print(f"  Inspyre: {seg_result['inspyre_validation'].get('description')}")
        print("=" * 60)
        if jobs_dict and job_id in jobs_dict:
            jobs_dict[job_id]["status"] = "rejected"
        error_msg = (
            "Unfortunately, a clear mask could not be extracted from your picture! "
            "Please go ahead and take another photo. Tips: make sure that the object is "
            "FULLY visible, in focus, on a clear surface and that you are not holding it "
            "with your finger occluding hands"
        )
        raise ValueError(error_msg)

    # Extract accepted results
    accepted_cropped_image = seg_result['cropped']
    accepted_concatenated_image = seg_result['concatenated']
    accepted_props = seg_result['properties']

    # Generate 3D mesh via ComfyUI API using the accepted CROPPED image
    status.start("🎨 Creating 3D mesh with ComfyUI (Hunyuan 3D)...")
    print("=" * 60)
    print("Starting 3D mesh generation via ComfyUI...")
    print(f"Using cropped image: {accepted_cropped_image}")
    print("=" * 60)

    glb_path = generate_mesh_via_comfyui(accepted_cropped_image, job_id)

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
    object_type = None  # object type from Gemini
    scene_description = None  # scene description from Gemini

    # Extract material properties (already inferred during validation!)
    if USE_LLM and accepted_props:
        print("\n✓ Using properties from validation step (already inferred)")
        props = accepted_props

        # Save properties to file
        props_file = Path(image_path) / "properties.json"
        with open(str(props_file), 'w') as f:
            json.dump(props, f, indent=2)
        print(f"✓ Saved properties to {props_file}")

        # Update jobs dict to indicate properties are available
        if jobs_dict and job_id in jobs_dict:
            jobs_dict[job_id]["properties_generated"] = True

        print(f"✓ Material properties: {props}")
        mass, df, ds, restitution, scaling = extract_physics_properties(props, use_scaling=USE_SCALING)
        object_type = props.get("object_type", "unknown")  # Extract object type
        scene_description = props.get("scene_description", None)  # Extract scene description
        print(f"✓ Physical properties extracted (mass: {mass}kg, restitution: {restitution})")

    # Convert GLB mesh to USD with physics properties
    status.start("🔧 Converting mesh to USD format...")
    print("\nConverting mesh to USD format...")
    usd_file = convert_mesh(Path(glb_path), f"{job_id}.glb", mass=mass, df=df, ds=ds, restitution=restitution, scaling=scaling, object_type=object_type, scene_description=scene_description)
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


def run_segmentation_workflow(workflow_name: str, image_path: str, job_id: str) -> str:
    """
    Run a segmentation workflow (SAM_seg or inspyre_seg) via ComfyUI API.

    Args:
        workflow_name: Name of workflow JSON file (e.g., "SAM_seg.json")
        image_path: Path to input image
        job_id: Unique job identifier

    Returns:
        Path to concatenated output image (original LEFT, masked RIGHT)
    """
    # Configuration
    comfy_url = os.getenv("COMFY_URL", "http://127.0.0.1:8188")
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    comfy_input_dir = Path(os.getenv("COMFY_INPUT_DIR", project_root / "3d_gen" / "ComfyUI" / "input"))
    comfy_output_dir = Path(os.getenv("COMFY_OUTPUT_DIR", project_root / "3d_gen" / "ComfyUI" / "output"))
    workflow_path = project_root / "src" / "scan2wall" / "workflows" / workflow_name

    # Ensure directories exist
    comfy_input_dir.mkdir(parents=True, exist_ok=True)
    comfy_output_dir.mkdir(parents=True, exist_ok=True)

    # Copy image to ComfyUI input directory with unique name
    image_filename = f"{job_id}_seg_{Path(image_path).name}"
    dest_image_path = comfy_input_dir / image_filename
    shutil.copy2(image_path, dest_image_path)
    print(f"✓ Image copied to ComfyUI input: {dest_image_path}")

    # Load workflow template
    with open(workflow_path, "r") as f:
        workflow = json.load(f)

    # Update workflow with image filename (node 44 is LoadImage for segmentation workflows)
    workflow["44"]["inputs"]["image"] = image_filename

    # Update filename prefixes for BOTH outputs
    # SAM workflow: node 43 (concatenated), node 50 (cropped)
    # Inspyre workflow: node 39 (concatenated), node 40 (cropped) - adjust as needed
    workflow_type = "sam" if "SAM_seg" in workflow_name else "inspyre"

    if "SAM_seg" in workflow_name:
        # SAM workflow: node 43 (concatenated), node 50 (cropped)
        workflow["43"]["inputs"]["filename_prefix"] = f"{job_id}_{workflow_type}_seg"
        workflow["50"]["inputs"]["filename_prefix"] = f"{job_id}_{workflow_type}_seg_cropped"
    else:
        # Inspyre workflow: node 39 (concatenated), node 51 (cropped)
        workflow["39"]["inputs"]["filename_prefix"] = f"{job_id}_{workflow_type}_seg"
        workflow["51"]["inputs"]["filename_prefix"] = f"{job_id}_{workflow_type}_seg_cropped"

    print(f"✓ Segmentation workflow configured: {workflow_name}")

    # Queue the prompt to ComfyUI
    print("Queueing segmentation workflow to ComfyUI...")
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
    print(f"✓ Segmentation workflow queued with prompt_id: {prompt_id}")

    # Poll for completion
    print("Waiting for segmentation to complete...")
    max_wait = 300  # 5 minutes max for segmentation
    start_time = time.time()
    processed_dir = Path(image_path).parent

    while time.time() - start_time < max_wait:
        # Check if workflow is complete
        history_response = requests.get(f"{comfy_url}/history/{prompt_id}")

        if history_response.status_code == 200:
            history = history_response.json()

            if prompt_id in history:
                prompt_history = history[prompt_id]

                # Check if completed
                if "outputs" in prompt_history:
                    print("\n✓ Segmentation complete!")

                    # Find and copy BOTH output images (concatenated + cropped)
                    # Use workflow-specific pattern to avoid conflicts
                    workflow_type = "sam" if "SAM_seg" in workflow_name else "inspyre"

                    # Find concatenated (without _cropped) and cropped (with _cropped)
                    all_files = list(comfy_output_dir.glob(f"{job_id}_{workflow_type}_seg*"))
                    concatenated_files = [f for f in all_files if "_cropped" not in f.name]
                    cropped_files = [f for f in all_files if "_cropped" in f.name]

                    if not concatenated_files or not cropped_files:
                        raise FileNotFoundError(
                            f"Expected concatenated and cropped outputs for job {job_id}. "
                            f"Found {len(concatenated_files)} concatenated, {len(cropped_files)} cropped"
                        )

                    concatenated_file = concatenated_files[0]
                    cropped_file = cropped_files[0]

                    # Copy both to job directory
                    concatenated_path = processed_dir / concatenated_file.name
                    cropped_path = processed_dir / cropped_file.name
                    shutil.copy2(concatenated_file, concatenated_path)
                    shutil.copy2(cropped_file, cropped_path)

                    print(f"✓ Concatenated output: {concatenated_path}")
                    print(f"✓ Cropped output: {cropped_path}")

                    # Return both paths as a dict
                    return {
                        "concatenated": str(concatenated_path),
                        "cropped": str(cropped_path)
                    }

        # Wait before polling again
        time.sleep(2)
        print(".", end="", flush=True)

    raise TimeoutError(f"Segmentation workflow timed out after {max_wait}s")


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
    workflow_path = project_root / "src" / "scan2wall" / "workflows" / "image2mesh-api.json"

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

    # Update workflow with image filename (node 240 is LoadImage)
    workflow["240"]["inputs"]["image"] = image_filename

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


def convert_mesh(out_file: Path, fname: str, mass=None, df=None, ds=None, restitution=None, scaling=None, output_dir=None, object_type=None, scene_description=None) -> str:
    """
    Convert GLB mesh to USD format via the persistent Isaac worker API.

    Args:
        out_file: Path to GLB file
        fname: Filename
        mass: Mass in kg
        df: Dynamic friction
        ds: Static friction
        restitution: Restitution coefficient
        scaling: Real-world size in meters (max dimension). If provided, mesh will be normalized
                 to 1x1x1 box then scaled to this size.
        output_dir: Optional directory for USD output. If not provided, uses out_file.parent
        object_type: Object type string from Gemini inference (e.g., "basketball", "mug")
        scene_description: Scene description from Gemini (max 200 chars)
    """
    fname_new = fname.replace(".glb", ".usd")
    print(f"Converting {fname} → {fname_new} via Isaac worker...")

    usd_dir = output_dir if output_dir else out_file.parent

    # Convert host paths to container paths
    # Get the actual project root dynamically
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    host_data_dir = str(project_root / "data")

    container_glb_path = str(out_file).replace(
        host_data_dir, "/workspace/s2w-data"
    )
    container_usd_dir = str(usd_dir).replace(
        host_data_dir, "/workspace/s2w-data"
    )

    payload = {
        "asset_path": container_glb_path,
        "usd_dir": container_usd_dir,
        "mass": mass,
        "static_friction": ds,
        "dynamic_friction": df,
        "restitution": restitution,
        "scaling": scaling,  # Real-world size in meters
        "object_type": object_type,  # Object type from Gemini inference
        "scene_description": scene_description,  # Scene description from Gemini
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

    # Convert host paths to container paths dynamically
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    host_data_dir = str(project_root / "data")

    container_usd_path = file.replace(host_data_dir, "/workspace/s2w-data")
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

        # Get container paths and convert to host paths
        # Two videos: static and follow camera
        container_video_static = result.get("video_path_static", f"{out_dir}/{job_id}_static.mp4")
        container_video_follow = result.get("video_path_follow", f"{out_dir}/{job_id}_follow.mp4")

        host_video_static = container_video_static.replace("/workspace/s2w-data", host_data_dir)
        host_video_follow = container_video_follow.replace("/workspace/s2w-data", host_data_dir)

        print(f"✅ Videos ready:")
        print(f"   Static view: {host_video_static}")
        print(f"   Follow view: {host_video_follow}")

        return {"static": host_video_static, "follow": host_video_follow}
    except Exception as e:
        raise RuntimeError(f"Simulation failed: {e}")

if __name__ == "__main__":
    # Test/debug code
    pass
