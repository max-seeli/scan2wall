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


class JobLogger:
    """Simple logger that writes to a per-job log file."""

    def __init__(self, job_dir: Path, job_id: str):
        self.log_file = job_dir / "job.log"
        self.job_id = job_id

    def log(self, message: str):
        """Write a timestamped message to the log file."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}\n"
        with open(self.log_file, 'a') as f:
            f.write(log_line)
        # Also print to console
        print(f"[{self.job_id}] {message}")


def to_container(path):
    """Convert host path to container path."""
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    host_data = str(project_root / "data")
    return str(path).replace(host_data, "/workspace/s2w-data")


def to_host(path):
    """Convert container path to host path."""
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    return str(path).replace("/workspace/s2w-data", str(project_root / "data"))


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
    print(f"  SAM validation: {sam_validation.get('decision')} (score: {sam_validation.get('score', 'N/A')}) - {sam_validation.get('description')}")
    print(f"  Inspyre validation: {inspyre_validation.get('decision')} (score: {inspyre_validation.get('score', 'N/A')}) - {inspyre_validation.get('description')}")

    total_elapsed = time.time() - start_time

    # Stage 3: Pick the best result using scores
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

    # Extract decisions and scores
    sam_decision = sam_validation.get('decision')
    inspyre_decision = inspyre_validation.get('decision')
    sam_score = sam_validation.get('score', 0)  # Default to 0 if None
    inspyre_score = inspyre_validation.get('score', 0)

    # Decision logic based on ACCEPT/REJECT and scores
    sam_accepted = sam_decision == "ACCEPT"
    inspyre_accepted = inspyre_decision == "ACCEPT"

    if sam_accepted and inspyre_accepted:
        # Both accepted - choose higher score
        if sam_score >= inspyre_score:
            print(f"✓ Both segmentations ACCEPTED - SAM score {sam_score} >= Inspyre score {inspyre_score} (using SAM)")
            chosen_method = 'SAM'
            chosen_result = sam_result
            chosen_props = sam_props
        else:
            print(f"✓ Both segmentations ACCEPTED - Inspyre score {inspyre_score} > SAM score {sam_score} (using Inspyre)")
            chosen_method = 'Inspyre'
            chosen_result = inspyre_result
            chosen_props = inspyre_props
    elif sam_accepted:
        # Only SAM accepted
        print(f"✓ SAM segmentation ACCEPTED (score: {sam_score}), Inspyre REJECTED (score: {inspyre_score}) - using SAM")
        chosen_method = 'SAM'
        chosen_result = sam_result
        chosen_props = sam_props
    elif inspyre_accepted:
        # Only Inspyre accepted
        print(f"✓ Inspyre segmentation ACCEPTED (score: {inspyre_score}), SAM REJECTED (score: {sam_score}) - using Inspyre")
        chosen_method = 'Inspyre'
        chosen_result = inspyre_result
        chosen_props = inspyre_props
    else:
        # Both rejected - report scores for diagnostics
        print(f"❌ Both SAM and Inspyre segmentations REJECTED (SAM score: {sam_score}, Inspyre score: {inspyre_score})")
        result.update({
            'status': 'rejected',
            'method': None,
            'cropped': None,
            'concatenated': None,
            'properties': None
        })
        return result

    # Update result with chosen segmentation
    result.update({
        'status': 'accepted',
        'method': chosen_method,
        'cropped': chosen_result['cropped'],
        'concatenated': chosen_result['concatenated'],
        'properties': chosen_props
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
    # Extract with safe defaults (simplified schema - no nested ["value"])
    mass = props.get("weight_kg", 1.0)
    df = props.get("friction_coefficients", {}).get("dynamic", 0.5)
    ds = props.get("friction_coefficients", {}).get("static", 0.6)
    restitution = props.get("restitution", 0.5)

    # Compute scaling from dimensions if available
    scaling = 1.0  # Default
    if use_scaling and props and "error" not in props:
        dims = props.get("dimensions_m", {})
        length = dims.get("length", 0)
        width = dims.get("width", 0)
        height = dims.get("height", 0)

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

    # Find the uploaded image (exclude log files)
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    img = None
    for file in Path(image_path).iterdir():
        if file.suffix.lower() in image_extensions:
            img = file
            break

    if img is None:
        raise FileNotFoundError(f"No image found in {image_path}")

    # Create job logger AFTER finding the image
    logger = JobLogger(Path(image_path), job_id)
    logger.log("=== Job Started ===")
    logger.log(f"Image path: {image_path}")
    logger.log(f"Found image: {img}")

    # Run parallel segmentation and validation (shared production code path)
    logger.log("STAGE 1: Starting segmentation and validation")
    status.start("STAGE:1:Segmentation & Validation - Running parallel segmentation...")
    print("=" * 60)
    print("Starting parallel segmentation pipeline...")
    print("=" * 60)

    seg_result = run_parallel_segmentation_and_validation(str(img), job_id)

    logger.log(f"STAGE 1: Complete ({seg_result['total_time']:.1f}s) - Method: {seg_result.get('method', 'N/A')}")
    status.stop(f"STAGE:1:Segmentation & Validation - Complete ({seg_result['total_time']:.1f}s)")

    # Check if segmentation was accepted
    if seg_result['status'] != 'accepted':
        # Both segmentations failed
        logger.log("ERROR: Both SAM and Inspyre segmentations REJECTED")
        logger.log(f"  SAM: {seg_result['sam_validation'].get('description')}")
        logger.log(f"  Inspyre: {seg_result['inspyre_validation'].get('description')}")
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
            "with your occluding fingers/hands"
        )
        raise ValueError(error_msg)

    # Extract accepted results
    accepted_cropped_image = seg_result['cropped']
    accepted_concatenated_image = seg_result['concatenated']
    accepted_props = seg_result['properties']

    # Save a copy of the final validated image for preview
    final_preview_path = Path(image_path) / f"{job_id}_final_segmented.png"
    shutil.copy2(accepted_cropped_image, final_preview_path)
    print(f"✓ Saved final segmented image: {final_preview_path}")

    # Generate 3D mesh via ComfyUI API using the accepted CROPPED image
    logger.log("STAGE 2: Starting 3D mesh generation (Hunyuan 3D)")
    status.start("STAGE:2:3D Mesh Generation - Creating mesh with Hunyuan 3D...")
    print("=" * 60)
    print("Starting 3D mesh generation via ComfyUI...")
    print(f"Using cropped image: {accepted_cropped_image}")
    print("=" * 60)

    glb_path = generate_mesh_via_comfyui(accepted_cropped_image, job_id)

    logger.log(f"STAGE 2: Complete - GLB generated: {glb_path}")
    print(f"✓ 3D mesh generated: {glb_path}")
    status.stop("STAGE:2:3D Mesh Generation - Complete")

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
    logger.log(f"STAGE 3: Starting mesh conversion to USD (mass: {mass}kg, friction: {df}/{ds})")
    status.start("STAGE:3:Mesh Conversion - Converting to USD with physics...")
    print("\nConverting mesh to USD format...")
    usd_file = convert_mesh(Path(glb_path), props_file)
    logger.log(f"STAGE 3: Complete - USD file: {usd_file}")
    print(f"✓ Mesh converted to USD: {usd_file}")
    status.stop("STAGE:3:Mesh Conversion - Complete")

    # Trigger Isaac Sim simulation and wait for completion
    logger.log("STAGE 4: Starting physics simulation in Isaac Sim")
    status.start("STAGE:4:Physics Simulation - Running in Isaac Sim...")
    print("\nTriggering Isaac Sim simulation...")
    video_path = make_throwing_anim(usd_file, job_id, status)
    logger.log(f"STAGE 4: Complete - Videos generated")
    logger.log(f"=== Job Complete - Total pipeline finished ===")
    print(f"✓ Simulation complete! Video: {video_path}")
    status.stop("STAGE:5:Complete - Videos generated!")

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


def repair_mesh_for_deformable(glb_path: Path) -> Path:
    """
    Repair mesh to make it watertight for deformable body simulation.

    PhysX requires closed meshes for voxelization. This function:
    - Fills holes
    - Removes degenerate faces
    - Fixes normals

    Returns path to repaired mesh (in-place modification).
    """
    import trimesh
    import numpy as np

    print(f"  🔧 Repairing mesh for deformable simulation: {glb_path.name}")

    # Load mesh
    mesh = trimesh.load(str(glb_path), force='mesh')

    # Get initial stats
    initial_verts = len(mesh.vertices)
    initial_faces = len(mesh.faces)
    initial_watertight = mesh.is_watertight

    print(f"     Initial: {initial_verts} verts, {initial_faces} faces, watertight={initial_watertight}")

    # Step 1: Remove degenerate faces
    mesh.remove_degenerate_faces()

    # Step 2: Remove duplicate vertices
    mesh.merge_vertices()

    # Step 3: Fill holes
    mesh.fill_holes()

    # Step 4: Fix normals
    mesh.fix_normals()

    # Step 5: Check for multiple disconnected components (PhysX can't handle this)
    components = mesh.split(only_watertight=False)
    if len(components) > 1:
        print(f"     ⚠️  Mesh has {len(components)} disconnected components")
        # Keep only the largest component
        largest = max(components, key=lambda m: len(m.vertices))
        mesh = largest
        print(f"     → Keeping largest component ({len(mesh.vertices)} verts)")

    # Step 6: Try to make watertight if still not (aggressive fill_holes)
    if not mesh.is_watertight:
        print(f"     ⚠️  Mesh still not watertight, attempting aggressive hole filling...")
        # Try multiple fill passes
        for i in range(3):
            mesh.fill_holes()
            if mesh.is_watertight:
                print(f"     ✓ Watertight after {i+1} fill pass(es)")
                break

        # If STILL not watertight, ONLY THEN use convex hull
        if not mesh.is_watertight:
            print(f"     ⚠️  Aggressive hole filling failed, using convex hull as last resort")
            mesh = mesh.convex_hull

    # Get final stats
    final_verts = len(mesh.vertices)
    final_faces = len(mesh.faces)
    final_watertight = mesh.is_watertight
    final_components = len(mesh.split(only_watertight=False))

    print(f"     Final: {final_verts} verts, {final_faces} faces, watertight={final_watertight}, components={final_components}")

    if not final_watertight:
        print(f"     ✗ WARNING: Could not make mesh watertight! Deformable simulation may fail.")
    else:
        print(f"     ✓ Mesh is now watertight")

    # Save repaired mesh (overwrite original)
    mesh.export(str(glb_path))

    return glb_path


def convert_mesh(glb_file: Path, json_file: Path, output_dir=None) -> str:
    """Convert GLB to USDZ via Isaac worker."""
    import json

    usd_dir = output_dir if output_dir else glb_file.parent

    # Check if this is a deformable object that needs mesh repair
    if json_file.exists():
        with open(json_file, 'r') as f:
            properties = json.load(f)
            rigidity_type = properties.get('rigidity', {}).get('type', 'rigid')

            # NOTE: Mesh repair now handled by ComfyUI's make_watertight option (PyMeshLab)
            # This avoids redundant I/O and prevents convex hull fallback from destroying detail
            # if rigidity_type == "deformable":
            #     print(f"  Deformable object detected - repairing mesh...")
            #     glb_file = repair_mesh_for_deformable(glb_file)

    payload = {
        "glb_path": to_container(glb_file),
        "json_path": to_container(json_file),
        "usd_dir": to_container(usd_dir),
    }

    r = requests.post("http://localhost:8090/convert", json=payload, timeout=600)
    r.raise_for_status()

    return to_container(glb_file.with_suffix(".usdz"))


def make_throwing_anim(file: str, job_id: str = None, status_updater=None):
    """Run throwing simulation via Isaac worker."""
    container_path = to_container(file)

    payload = {
        "usd_path": container_path,
        "out_dir": str(Path(container_path).parent),
        "video": True,
        "video_length": 200,
        "fps": 50,
        "job_id": job_id,
    }

    r = requests.post("http://localhost:8090/run_simulation", json=payload, timeout=1800)
    r.raise_for_status()
    result = r.json()

    return {
        "static": to_host(result.get("video_path_static")),
        "follow": to_host(result.get("video_path_follow"))
    }

if __name__ == "__main__":
    # Test/debug code
    pass
