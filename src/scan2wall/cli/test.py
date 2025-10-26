"""Test commands for scan2wall pipeline.

Pipeline stages (in order):
    images → segmented → meshes → texturedmeshes → usd → videos

Usage:
    scan2wall test -s START -e END

Examples:
    scan2wall test -s images -e segmented         # Only segmentation
    scan2wall test -s segmented -e videos         # 3D generation + simulation
    scan2wall test -s texturedmeshes -e videos    # Only simulation
"""

import click
import time
import uuid
import shutil
import json
import os
from pathlib import Path
from typing import List, Dict, Any
import imghdr
from PIL import Image
import io

from scan2wall.pipeline.coordinator import process_image


# Test directories
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
TEST_DIR = PROJECT_ROOT / "data" / "test"
TEST_IMAGES_DIR = TEST_DIR / "images"
TEST_SEGMENTED_DIR = TEST_DIR / "segmented"
TEST_MESHES_DIR = TEST_DIR / "meshes"
TEST_TEXTURED_DIR = TEST_DIR / "texturedmeshes"
TEST_USD_DIR = TEST_DIR / "usd"
TEST_VIDEOS_DIR = TEST_DIR / "videos"
JOBS_DIR = PROJECT_ROOT / "data" / "JOBS"

# Ensure all test directories exist
for test_dir in [TEST_DIR, TEST_IMAGES_DIR, TEST_SEGMENTED_DIR, TEST_MESHES_DIR,
                 TEST_TEXTURED_DIR, TEST_USD_DIR, TEST_VIDEOS_DIR, JOBS_DIR]:
    test_dir.mkdir(parents=True, exist_ok=True)

# Pipeline stages in order
PIPELINE_STAGES = ["images", "segmented", "meshes", "texturedmeshes", "usd", "videos"]


@click.group(invoke_without_command=True)
@click.option('-s', '--start', 'start_stage', type=str,
              help='Starting pipeline stage')
@click.option('-e', '--end', 'end_stage', type=str,
              help='Ending pipeline stage')
@click.pass_context
def test(ctx, start_stage, end_stage):
    """Run pipeline tests on specific stages.

    \b
    Pipeline stages (in order):
      images → segmented → meshes → texturedmeshes → usd → videos

    \b
    Examples:
      scan2wall test -s images -e segmented       # Only segmentation
      scan2wall test -s segmented -e videos       # 3D + simulation
      scan2wall test -s texturedmeshes -e videos  # Only simulation

    \b
    Other commands:
      scan2wall test clear  # Delete all test outputs
    """
    # If subcommand (like 'clear') is being invoked, don't run main logic
    if ctx.invoked_subcommand is not None:
        return

    # If no flags provided, show usage
    if not start_stage or not end_stage:
        click.echo("❌ Error: Invalid command format\n")
        click.echo("Expected: scan2wall test -s START -e END\n")
        click.echo("Valid stages (in order):")
        click.echo("  " + " → ".join(PIPELINE_STAGES) + "\n")
        click.echo("Examples:")
        click.echo("  scan2wall test -s images -e segmented")
        click.echo("  scan2wall test -s segmented -e videos")
        click.echo("  scan2wall test -s texturedmeshes -e videos")
        ctx.exit(1)

    # Validate stages
    if start_stage not in PIPELINE_STAGES:
        click.echo(f"❌ Error: Invalid start stage '{start_stage}'\n")
        click.echo("Valid stages (in order):")
        click.echo("  " + " → ".join(PIPELINE_STAGES))
        ctx.exit(1)

    if end_stage not in PIPELINE_STAGES:
        click.echo(f"❌ Error: Invalid end stage '{end_stage}'\n")
        click.echo("Valid stages (in order):")
        click.echo("  " + " → ".join(PIPELINE_STAGES))
        ctx.exit(1)

    start_idx = PIPELINE_STAGES.index(start_stage)
    end_idx = PIPELINE_STAGES.index(end_stage)

    if start_idx >= end_idx:
        click.echo(f"❌ Error: Start stage must come before end stage\n")
        click.echo(f"You specified: {start_stage} → {end_stage}")
        click.echo(f"Pipeline order: " + " → ".join(PIPELINE_STAGES))
        ctx.exit(1)

    # Run the pipeline for the specified stages
    run_pipeline_stages(start_stage, end_stage)


def find_test_images(directory: Path) -> List[Path]:
    """Find all valid image files in the test directory.

    Args:
        directory: Directory to search for images

    Returns:
        List of image file paths
    """
    if not directory.exists():
        return []

    images = []
    for ext in ['*.jpg', '*.jpeg', '*.png', '*.webp', '*.gif']:
        images.extend(directory.glob(ext))
        images.extend(directory.glob(ext.upper()))

    return sorted(images)


def validate_image(image_path: Path) -> bool:
    """Validate that file is a proper image.

    Args:
        image_path: Path to image file

    Returns:
        True if valid, False otherwise
    """
    try:
        with open(image_path, 'rb') as f:
            contents = f.read()

        # Signature check
        kind = imghdr.what(None, contents[:512])
        if kind not in {"jpeg", "png", "webp", "gif", "jpg"}:
            return False

        # Pillow validation
        Image.open(io.BytesIO(contents)).verify()
        return True
    except Exception:
        return False


def prepare_job(image_path: Path) -> Dict[str, Any]:
    """Prepare a job structure for testing.

    Args:
        image_path: Path to the test image

    Returns:
        Dictionary with job information
    """
    job_id = uuid.uuid4().hex[:8]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Copy image to job directory
    ts = time.strftime("%Y%m%d-%H%M%S")
    dest_filename = f"{ts}{image_path.suffix}"
    dest_path = job_dir / dest_filename

    shutil.copy2(image_path, dest_path)

    return {
        "id": job_id,
        "filename": image_path.name,
        "original_path": str(image_path),
        "path": str(dest_path),
        "job_dir": str(job_dir),
        "status": "queued",
        "status_detail": "Waiting...",
        "created_at": time.time(),
        "processed_path": None,
        "error": None,
    }


def organize_outputs(job_id: str, job_dir: Path, original_filename: str) -> Dict[str, List[Path]]:
    """Copy outputs from job directory to organized test folders.

    Args:
        job_id: Job identifier
        job_dir: Path to job directory
        original_filename: Original image filename (for naming outputs)

    Returns:
        Dictionary with lists of copied files by category
    """

    # Ensure output directories exist
    TEST_SEGMENTED_DIR.mkdir(parents=True, exist_ok=True)
    TEST_MESHES_DIR.mkdir(parents=True, exist_ok=True)
    TEST_TEXTURED_DIR.mkdir(parents=True, exist_ok=True)
    TEST_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

    copied = {
        'segmented': [],
        'meshes': [],
        'textured': [],
        'videos': []
    }

    # Copy segmented images (cropped PNGs)
    for seg_file in job_dir.glob(f"{job_id}_*_seg_cropped_*.png"):
        dest = TEST_SEGMENTED_DIR / seg_file.name
        shutil.copy2(seg_file, dest)
        copied['segmented'].append(dest)

    # Copy meshes (STL files)
    for mesh_file in job_dir.glob(f"{job_id}_*.stl"):
        dest = TEST_MESHES_DIR / mesh_file.name
        shutil.copy2(mesh_file, dest)
        copied['meshes'].append(dest)

    # Copy textured mesh (GLB)
    glb_file = job_dir / f"{job_id}.glb"
    if glb_file.exists():
        dest = TEST_TEXTURED_DIR / glb_file.name
        shutil.copy2(glb_file, dest)
        copied['textured'].append(dest)

    # Copy videos
    for video_file in job_dir.glob(f"{job_id}_*.mp4"):
        dest = TEST_VIDEOS_DIR / video_file.name
        shutil.copy2(video_file, dest)
        copied['videos'].append(dest)

    return copied


def run_pipeline_stages(start_stage: str, end_stage: str):
    """Run the pipeline from start_stage to end_stage.

    Args:
        start_stage: Starting pipeline stage
        end_stage: Ending pipeline stage
    """
    start_idx = PIPELINE_STAGES.index(start_stage)
    end_idx = PIPELINE_STAGES.index(end_stage)
    stages = PIPELINE_STAGES[start_idx:end_idx + 1]

    click.echo(f"🧪 Running pipeline: {' → '.join(stages)}")
    click.echo()

    # Determine input directory based on start stage
    stage_dirs = {
        "images": TEST_IMAGES_DIR,
        "segmented": TEST_SEGMENTED_DIR,
        "meshes": TEST_MESHES_DIR,
        "texturedmeshes": TEST_TEXTURED_DIR,
        "usd": TEST_USD_DIR,
    }

    input_dir = stage_dirs.get(start_stage)
    if not input_dir or not input_dir.exists():
        click.echo(f"❌ Error: Input directory not found: {input_dir}")
        click.echo(f"Create it with: mkdir -p {input_dir}")
        return

    # Find input files
    if start_stage == "images":
        input_files = find_test_images(input_dir)
    elif start_stage == "segmented":
        # Only process PNG files, skip JSON files
        input_files = list(input_dir.glob("*.png"))
    elif start_stage == "texturedmeshes":
        # Only process GLB files
        input_files = list(input_dir.glob("*.glb"))
    elif start_stage == "usd":
        # Only process USD files
        input_files = list(input_dir.glob("*.usd"))
    else:
        # For other stages, find relevant files
        input_files = list(input_dir.glob("*.*"))

    if not input_files:
        click.echo(f"❌ No files found in {input_dir}")
        return

    click.echo(f"Found {len(input_files)} file(s) in {input_dir}")
    click.echo()

    # Route to appropriate pipeline function based on start/end stages
    if start_stage == "images" and end_stage == "segmented":
        run_segmentation_stage(input_files)
    elif start_stage == "segmented" and end_stage in ["meshes", "texturedmeshes"]:
        run_3d_generation_stage(input_files, end_stage)
    elif start_stage == "texturedmeshes" and end_stage == "usd":
        run_usd_conversion_stage(input_files)
    elif start_stage == "usd" and end_stage == "videos":
        run_simulation_stage(input_files)
    elif start_stage == "segmented" and end_stage in ["usd", "videos"]:
        # Multi-stage: segmented → texturedmeshes → usd → videos
        run_multi_stage_pipeline(input_files, start_stage, end_stage)
    elif start_stage == "images" and end_stage in ["meshes", "texturedmeshes", "usd", "videos"]:
        # Multi-stage: images → ... → end
        run_multi_stage_pipeline(input_files, start_stage, end_stage)
    else:
        click.echo(f"⚠️  Pipeline {start_stage} → {end_stage} not yet implemented")
        click.echo(f"\nCurrently supported:")
        click.echo(f"  - images → segmented")
        click.echo(f"  - segmented → texturedmeshes")
        click.echo(f"  - texturedmeshes → usd")
        click.echo(f"  - usd → videos")
        click.echo(f"  - Multi-stage combinations")


def run_segmentation_stage(image_files: List[Path]):
    """Run only segmentation stage (images → segmented).

    Args:
        image_files: List of input image paths
    """
    from scan2wall.pipeline.coordinator import run_segmentation_workflow
    from scan2wall.inference.get_object_properties import validate_segmentation

    results = []

    for idx, image_path in enumerate(image_files, 1):
        click.echo(f"[{idx}/{len(image_files)}] {image_path.name}")

        # Validate image
        if not validate_image(image_path):
            click.echo("  ❌ Invalid image file (skipping)\n")
            results.append({
                'filename': image_path.name,
                'status': 'invalid',
                'method': None
            })
            continue

        job_id = uuid.uuid4().hex[:8]
        start_time = time.time()

        try:
            # Try SAM first
            sam_start = time.time()
            click.echo("  🔍 Running SAM segmentation...")
            sam_result = run_segmentation_workflow("SAM_seg_cropped.json", str(image_path), job_id)
            sam_time = time.time() - sam_start
            click.echo(f"     ⏱️  SAM segmentation: {sam_time:.2f}s")

            # Validate SAM
            val_start = time.time()
            validation_result = validate_segmentation(sam_result['concatenated'])
            val_time = time.time() - val_start
            click.echo(f"     ⏱️  Gemini validation: {val_time:.2f}s")

            if validation_result['decision'] == "ACCEPT":
                elapsed = time.time() - start_time
                click.echo(f"  ✅ SAM ACCEPTED (total: {elapsed:.1f}s)")
                click.echo(f"     {validation_result['description'][:80]}")

                # Copy to test folder
                seg_file = Path(sam_result['cropped'])
                dest = TEST_SEGMENTED_DIR / f"{image_path.stem}_sam_seg.png"
                shutil.copy2(seg_file, dest)

                # Get and save physical properties
                click.echo("  📊 Inferring physical properties...")
                props_start = time.time()
                try:
                    from scan2wall.inference.get_object_properties import get_object_properties
                    props = get_object_properties(str(seg_file))

                    # Check if inference failed, use defaults
                    if "error" in props:
                        click.echo(f"     ⚠️  Property inference failed: {props['error']}")
                        props = {
                            "object_type": "unknown",
                            "weight_kg": {"value": 1.0},
                            "friction_coefficients": {"static": 0.6, "dynamic": 0.5},
                            "restitution": {"value": 0.5}
                        }
                        click.echo(f"     Using defaults (mass: 1.0kg)")
                    else:
                        props_time = time.time() - props_start
                        mass = props.get("weight_kg", {}).get("value", 1.0)
                        click.echo(f"     Properties inferred (mass: {mass:.2f}kg, {props_time:.1f}s)")

                    # Always save properties (either inferred or defaults)
                    props_file = TEST_SEGMENTED_DIR / f"{image_path.stem}_sam_seg_properties.json"
                    with open(props_file, 'w') as f:
                        json.dump(props, f, indent=2)

                except Exception as e:
                    click.echo(f"     ⚠️  Property inference exception: {str(e)[:50]}")

                # Clean up intermediate files from images directory
                Path(sam_result['concatenated']).unlink(missing_ok=True)
                Path(sam_result['cropped']).unlink(missing_ok=True)

                results.append({
                    'filename': image_path.name,
                    'status': 'accepted',
                    'method': 'SAM',
                    'time': elapsed,
                    'sam_time': sam_time,
                    'val_time': val_time
                })
            else:
                # Try Inspyre
                click.echo(f"  ⚠️  SAM REJECTED: {validation_result['description'][:80]}")
                click.echo("  🔄 Trying Inspyre segmentation...")

                inspyre_start = time.time()
                inspyre_result = run_segmentation_workflow("inspyre_seg_cropped.json", str(image_path), job_id)
                inspyre_time = time.time() - inspyre_start
                click.echo(f"     ⏱️  Inspyre segmentation: {inspyre_time:.2f}s")

                # Validate Inspyre
                val2_start = time.time()
                validation_result = validate_segmentation(inspyre_result['concatenated'])
                val2_time = time.time() - val2_start
                click.echo(f"     ⏱️  Gemini validation: {val2_time:.2f}s")

                elapsed = time.time() - start_time

                if validation_result['decision'] == "ACCEPT":
                    click.echo(f"  ✅ Inspyre ACCEPTED (total: {elapsed:.1f}s)")
                    click.echo(f"     {validation_result['description'][:80]}")

                    # Copy to test folder
                    seg_file = Path(inspyre_result['cropped'])
                    dest = TEST_SEGMENTED_DIR / f"{image_path.stem}_inspyre_seg.png"
                    shutil.copy2(seg_file, dest)

                    # Get and save physical properties
                    click.echo("  📊 Inferring physical properties...")
                    props_start = time.time()
                    try:
                        from scan2wall.inference.get_object_properties import get_object_properties
                        props = get_object_properties(str(seg_file))

                        # Check if inference failed, use defaults
                        if "error" in props:
                            click.echo(f"     ⚠️  Property inference failed: {props['error']}")
                            props = {
                                "object_type": "unknown",
                                "weight_kg": {"value": 1.0},
                                "friction_coefficients": {"static": 0.6, "dynamic": 0.5},
                                "restitution": {"value": 0.5}
                            }
                            click.echo(f"     Using defaults (mass: 1.0kg)")
                        else:
                            props_time = time.time() - props_start
                            mass = props.get("weight_kg", {}).get("value", 1.0)
                            click.echo(f"     Properties inferred (mass: {mass:.2f}kg, {props_time:.1f}s)")

                        # Always save properties (either inferred or defaults)
                        props_file = TEST_SEGMENTED_DIR / f"{image_path.stem}_inspyre_seg_properties.json"
                        with open(props_file, 'w') as f:
                            json.dump(props, f, indent=2)

                    except Exception as e:
                        click.echo(f"     ⚠️  Property inference exception: {str(e)[:50]}")

                    # Clean up intermediate files from images directory
                    Path(sam_result['concatenated']).unlink(missing_ok=True)
                    Path(sam_result['cropped']).unlink(missing_ok=True)
                    Path(inspyre_result['concatenated']).unlink(missing_ok=True)
                    Path(inspyre_result['cropped']).unlink(missing_ok=True)

                    results.append({
                        'filename': image_path.name,
                        'status': 'accepted',
                        'method': 'Inspyre',
                        'time': elapsed,
                        'sam_time': sam_time,
                        'inspyre_time': inspyre_time,
                        'val_time': val_time + val2_time
                    })
                else:
                    click.echo(f"  ❌ Both methods REJECTED (total: {elapsed:.1f}s)")
                    click.echo(f"     {validation_result['description'][:80]}")

                    # Clean up intermediate files from images directory (rejected case)
                    Path(sam_result['concatenated']).unlink(missing_ok=True)
                    Path(sam_result['cropped']).unlink(missing_ok=True)
                    Path(inspyre_result['concatenated']).unlink(missing_ok=True)
                    Path(inspyre_result['cropped']).unlink(missing_ok=True)

                    results.append({
                        'filename': image_path.name,
                        'status': 'rejected',
                        'method': None,
                        'time': elapsed,
                        'sam_time': sam_time,
                        'inspyre_time': inspyre_time,
                        'val_time': val_time + val2_time
                    })

        except Exception as e:
            elapsed = time.time() - start_time
            click.echo(f"  ❌ ERROR ({elapsed:.1f}s): {str(e)[:100]}")
            results.append({
                'filename': image_path.name,
                'status': 'error',
                'method': None,
                'time': elapsed,
                'error': str(e)
            })

        click.echo()

    # Print summary
    print_segmentation_summary(results)


def run_3d_generation_stage(image_files: List[Path], end_stage: str):
    """Run 3D generation stage (segmented → meshes/texturedmeshes).

    Args:
        image_files: List of segmented image paths
        end_stage: Either 'meshes' or 'texturedmeshes'
    """
    from scan2wall.pipeline.coordinator import generate_mesh_via_comfyui

    results = []
    click.echo(f"🎨 Generating 3D meshes...")
    click.echo()

    for idx, image_path in enumerate(image_files, 1):
        click.echo(f"[{idx}/{len(image_files)}] {image_path.name}")

        job_id = uuid.uuid4().hex[:8]
        start_time = time.time()

        try:
            # Generate 3D mesh
            click.echo("  🔨 Running 3D mesh generation (Hunyuan)...")
            gen_start = time.time()
            glb_path = generate_mesh_via_comfyui(str(image_path), job_id)
            gen_time = time.time() - gen_start

            elapsed = time.time() - start_time
            click.echo(f"  ✅ 3D generation complete ({elapsed:.1f}s)")
            click.echo(f"     Generation time: {gen_time:.1f}s")

            # Copy outputs to appropriate directories
            glb_file = Path(glb_path)
            output_dir = glb_file.parent

            # Verify GLB file exists
            if not glb_file.exists():
                raise FileNotFoundError(f"GLB file not generated: {glb_file}")

            # Copy GLB to texturedmeshes directory
            dest_glb = TEST_TEXTURED_DIR / f"{image_path.stem}.glb"
            TEST_TEXTURED_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(glb_file, dest_glb)
            click.echo(f"     Textured mesh: {dest_glb.name}")

            # Copy STL files to meshes directory (if they exist)
            TEST_MESHES_DIR.mkdir(parents=True, exist_ok=True)
            for stl_file in output_dir.glob(f"{job_id}*.stl"):
                dest_stl = TEST_MESHES_DIR / f"{image_path.stem}_{stl_file.stem.split('_')[-1]}.stl"
                shutil.copy2(stl_file, dest_stl)
                click.echo(f"     Untextured mesh: {dest_stl.name}")

            # Copy properties.json if it exists
            props_file = image_path.parent / f"{image_path.stem}_properties.json"

            if props_file.exists():
                dest_props = TEST_TEXTURED_DIR / f"{image_path.stem}_properties.json"
                shutil.copy2(props_file, dest_props)
                click.echo(f"     Properties: {dest_props.name}")
            else:
                click.echo(f"     ⚠️  No properties.json found for {image_path.name}")

            # Clean up ALL intermediate files from segmented directory
            for temp_file in output_dir.glob(f"{job_id}*"):
                temp_file.unlink(missing_ok=True)

            # Also clean up from ComfyUI directories
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            comfy_output_dir = Path(os.getenv("COMFY_OUTPUT_DIR", project_root / "3d_gen" / "ComfyUI" / "output"))
            comfy_input_dir = Path(os.getenv("COMFY_INPUT_DIR", project_root / "3d_gen" / "ComfyUI" / "input"))

            # Delete output files (GLB, STL, multiview PNGs, etc.)
            for temp_file in comfy_output_dir.glob(f"{job_id}*"):
                temp_file.unlink(missing_ok=True)

            # Delete input image
            for temp_file in comfy_input_dir.glob(f"{job_id}*"):
                temp_file.unlink(missing_ok=True)

            results.append({
                'filename': image_path.name,
                'status': 'success',
                'time': elapsed,
                'gen_time': gen_time
            })

        except Exception as e:
            elapsed = time.time() - start_time
            click.echo(f"  ❌ ERROR ({elapsed:.1f}s): {str(e)[:100]}")
            results.append({
                'filename': image_path.name,
                'status': 'error',
                'time': elapsed,
                'error': str(e)
            })

        click.echo()

    # Print summary
    print_3d_generation_summary(results)


def run_usd_conversion_stage(glb_files: List[Path]):
    """Run USD conversion stage (texturedmeshes → usd).

    Args:
        glb_files: List of GLB file paths
    """
    from scan2wall.pipeline.coordinator import convert_mesh
    from scan2wall.inference.get_object_properties import get_object_properties

    results = []
    click.echo(f"🔄 Converting GLB → USD...")
    click.echo()

    TEST_USD_DIR.mkdir(parents=True, exist_ok=True)

    for idx, glb_path in enumerate(glb_files, 1):
        if glb_path.suffix.lower() != '.glb':
            continue

        click.echo(f"[{idx}/{len(glb_files)}] {glb_path.name}")

        start_time = time.time()

        try:
            # Get physical properties with priority: cached JSON > fresh inference > defaults
            click.echo("  📊 Getting physical properties...")

            props = None
            props_source = None

            # Priority 1: Look for properties.json in texturedmeshes directory
            props_file = glb_path.parent / f"{glb_path.stem}_properties.json"

            if props_file.exists():
                try:
                    with open(props_file, 'r') as f:
                        props = json.load(f)
                    props_source = "cached (texturedmeshes)"
                except:
                    pass

            # Priority 2: Look in segmented directory
            # GLB files are named like: test_object_sam_seg.glb or test_object_inspyre_seg.glb
            # Properties files are named like: test_object_sam_seg_properties.json
            if not props:
                seg_props_file = TEST_SEGMENTED_DIR / f"{glb_path.stem}_properties.json"

                if seg_props_file.exists():
                    try:
                        with open(seg_props_file, 'r') as f:
                            props = json.load(f)
                        props_source = "cached (segmented)"
                    except:
                        pass

            # Priority 3: Fresh inference from segmented image
            # Segmented images have same stem as GLB: test_object_sam_seg.png
            if not props:
                seg_image = TEST_SEGMENTED_DIR / f"{glb_path.stem}.png"

                if seg_image.exists():
                    try:
                        props = get_object_properties(str(seg_image))
                        props_source = "fresh inference"
                    except:
                        pass

            # Extract properties or use defaults
            if props:
                mass = props.get("weight_kg", {}).get("value", 1.0)
                df = props.get("friction_coefficients", {}).get("dynamic", 0.5)
                ds = props.get("friction_coefficients", {}).get("static", 0.6)
                restitution = props.get("restitution", {}).get("value", 0.5)
                click.echo(f"     Using {props_source} (mass: {mass:.2f}kg)")
            else:
                mass, df, ds, restitution = 1.0, 0.5, 0.6, 0.5
                props_source = "defaults"
                click.echo(f"     Using {props_source} (no properties found)")

            # Get real-world scaling from dimensions
            scaling = max(
                props.get("dimensions_m", {}).get("length", {}).get("value", 1.0),
                props.get("dimensions_m", {}).get("width", {}).get("value", 1.0),
                props.get("dimensions_m", {}).get("height", {}).get("value", 1.0),
            ) if props and "error" not in props else None

            if scaling:
                click.echo(f"     Real-world size: {scaling:.3f}m (max dimension)")

            # Convert to USD
            click.echo("  🔄 Converting to USD...")
            conv_start = time.time()

            # Copy GLB to TEST_USD_DIR first (convert_mesh expects it there)
            temp_glb = TEST_USD_DIR / glb_path.name
            shutil.copy2(glb_path, temp_glb)

            usd_path = convert_mesh(temp_glb, glb_path.name, mass=mass, df=df, ds=ds, restitution=restitution, scaling=scaling)
            conv_time = time.time() - conv_start

            elapsed = time.time() - start_time
            click.echo(f"  ✅ Conversion complete ({elapsed:.1f}s)")
            click.echo(f"     Conversion time: {conv_time:.1f}s")

            results.append({
                'filename': glb_path.name,
                'status': 'success',
                'time': elapsed,
                'conv_time': conv_time
            })

        except Exception as e:
            elapsed = time.time() - start_time
            click.echo(f"  ❌ ERROR ({elapsed:.1f}s): {str(e)[:100]}")
            results.append({
                'filename': glb_path.name,
                'status': 'error',
                'time': elapsed,
                'error': str(e)
            })

        click.echo()

    # Print summary
    print_usd_conversion_summary(results)


def run_simulation_stage(usd_files: List[Path]):
    """Run simulation stage (usd → videos).

    Args:
        usd_files: List of USD file paths
    """
    from scan2wall.pipeline.coordinator import make_throwing_anim

    results = []
    click.echo(f"🎬 Running Isaac Sim simulations...")
    click.echo()

    TEST_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

    for idx, usd_path in enumerate(usd_files, 1):
        if usd_path.suffix.lower() != '.usd':
            continue

        click.echo(f"[{idx}/{len(usd_files)}] {usd_path.name}")

        job_id = usd_path.stem
        start_time = time.time()

        try:
            # USD file is already scaled to correct size during conversion
            # No need to apply scaling here
            click.echo("  🎮 Running physics simulation...")
            sim_start = time.time()

            make_throwing_anim(str(usd_path), scaling=1.0, job_id=job_id)

            sim_time = time.time() - sim_start
            elapsed = time.time() - start_time

            # Videos are created in the USD directory
            video_static = TEST_USD_DIR / f"{job_id}_static.mp4"
            video_follow = TEST_USD_DIR / f"{job_id}_follow.mp4"

            # Move videos to test videos directory
            if video_static.exists():
                dest = TEST_VIDEOS_DIR / video_static.name
                shutil.move(str(video_static), str(dest))
            if video_follow.exists():
                dest = TEST_VIDEOS_DIR / video_follow.name
                shutil.move(str(video_follow), str(dest))

            click.echo(f"  ✅ Simulation complete ({elapsed:.1f}s)")
            click.echo(f"     Simulation time: {sim_time:.1f}s")
            click.echo(f"     Videos: {job_id}_static.mp4, {job_id}_follow.mp4")

            results.append({
                'filename': usd_path.name,
                'status': 'success',
                'time': elapsed,
                'sim_time': sim_time
            })

        except Exception as e:
            elapsed = time.time() - start_time
            click.echo(f"  ❌ ERROR ({elapsed:.1f}s): {str(e)[:100]}")
            results.append({
                'filename': usd_path.name,
                'status': 'error',
                'time': elapsed,
                'error': str(e)
            })

        click.echo()

    # Print summary
    print_simulation_summary(results)


def run_multi_stage_pipeline(input_files: List[Path], start_stage: str, end_stage: str):
    """Run multi-stage pipeline.

    Args:
        input_files: List of input file paths
        start_stage: Starting stage
        end_stage: Ending stage
    """
    click.echo(f"⚠️  Multi-stage pipeline {start_stage} → {end_stage} not yet implemented")
    click.echo(f"Please run stages individually:")

    stages_map = {
        "images": "images",
        "segmented": "segmented",
        "meshes": "texturedmeshes",
        "texturedmeshes": "texturedmeshes",
        "usd": "usd",
        "videos": "videos"
    }

    current = start_stage
    while PIPELINE_STAGES.index(current) < PIPELINE_STAGES.index(end_stage):
        next_idx = PIPELINE_STAGES.index(current) + 1
        next_stage = PIPELINE_STAGES[next_idx]
        click.echo(f"  scan2wall test -s {current} -e {next_stage}")
        current = next_stage


def print_segmentation_summary(results: List[Dict]):
    """Print summary of segmentation results.

    Args:
        results: List of result dictionaries
    """
    click.echo("=" * 60)
    click.echo("SUMMARY")
    click.echo("=" * 60)

    accepted_sam = [r for r in results if r['status'] == 'accepted' and r.get('method') == 'SAM']
    accepted_inspyre = [r for r in results if r['status'] == 'accepted' and r.get('method') == 'Inspyre']
    rejected = [r for r in results if r['status'] == 'rejected']
    errors = [r for r in results if r['status'] == 'error']
    invalid = [r for r in results if r['status'] == 'invalid']

    click.echo(f"Total: {len(results)}")
    click.echo(f"  ✅ Accepted (SAM): {len(accepted_sam)}")
    click.echo(f"  ✅ Accepted (Inspyre): {len(accepted_inspyre)}")
    click.echo(f"  ❌ Rejected: {len(rejected)}")
    click.echo(f"  ⚠️  Errors: {len(errors)}")
    click.echo(f"  🚫 Invalid: {len(invalid)}")

    if accepted_sam or accepted_inspyre:
        all_accepted = accepted_sam + accepted_inspyre
        avg_time = sum(r['time'] for r in all_accepted) / len(all_accepted)
        click.echo(f"\nAverage processing time: {avg_time:.1f}s")

    click.echo(f"\nOutputs saved to: {TEST_SEGMENTED_DIR}")


def print_3d_generation_summary(results: List[Dict]):
    """Print summary of 3D generation results."""
    click.echo("=" * 60)
    click.echo("SUMMARY")
    click.echo("=" * 60)

    success = [r for r in results if r['status'] == 'success']
    errors = [r for r in results if r['status'] == 'error']

    click.echo(f"Total: {len(results)}")
    click.echo(f"  ✅ Success: {len(success)}")
    click.echo(f"  ❌ Errors: {len(errors)}")

    if success:
        avg_time = sum(r['time'] for r in success) / len(success)
        click.echo(f"\nAverage generation time: {avg_time:.1f}s")

    click.echo(f"\nOutputs saved to:")
    click.echo(f"  Textured meshes (GLB): {TEST_TEXTURED_DIR}")
    click.echo(f"  Untextured meshes (STL): {TEST_MESHES_DIR}")


def print_usd_conversion_summary(results: List[Dict]):
    """Print summary of USD conversion results."""
    click.echo("=" * 60)
    click.echo("SUMMARY")
    click.echo("=" * 60)

    success = [r for r in results if r['status'] == 'success']
    errors = [r for r in results if r['status'] == 'error']

    click.echo(f"Total: {len(results)}")
    click.echo(f"  ✅ Success: {len(success)}")
    click.echo(f"  ❌ Errors: {len(errors)}")

    if success:
        avg_time = sum(r['time'] for r in success) / len(success)
        click.echo(f"\nAverage conversion time: {avg_time:.1f}s")

    click.echo(f"\nOutputs saved to: {TEST_USD_DIR}")


def print_simulation_summary(results: List[Dict]):
    """Print summary of simulation results."""
    click.echo("=" * 60)
    click.echo("SUMMARY")
    click.echo("=" * 60)

    success = [r for r in results if r['status'] == 'success']
    errors = [r for r in results if r['status'] == 'error']

    click.echo(f"Total: {len(results)}")
    click.echo(f"  ✅ Success: {len(success)}")
    click.echo(f"  ❌ Errors: {len(errors)}")

    if success:
        avg_time = sum(r['time'] for r in success) / len(success)
        click.echo(f"\nAverage simulation time: {avg_time:.1f}s")

    click.echo(f"\nOutputs saved to: {TEST_VIDEOS_DIR}")


@test.command()
@click.confirmation_option(prompt='Are you sure you want to delete all test outputs?')
def clear():
    """Clear all test outputs (keeps test images intact).

    Deletes all files from segmented/, meshes/, texturedmeshes/, usd/, and videos/
    directories but preserves the images/ folder and its contents.
    """

    dirs_to_clear = [
        TEST_SEGMENTED_DIR,
        TEST_MESHES_DIR,
        TEST_TEXTURED_DIR,
        TEST_USD_DIR,
        TEST_VIDEOS_DIR
    ]

    click.echo("🧹 Clearing test outputs...")

    total_deleted = 0
    for directory in dirs_to_clear:
        if not directory.exists():
            continue

        # Count files before deletion
        files = list(directory.glob('*'))
        file_count = len([f for f in files if f.is_file()])

        if file_count > 0:
            click.echo(f"   Deleting {file_count} file(s) from {directory.name}/")

            # Delete all files in the directory
            for item in files:
                try:
                    if item.is_file():
                        item.unlink()
                        total_deleted += 1
                    elif item.is_dir():
                        shutil.rmtree(item)
                except Exception as e:
                    click.echo(f"   ⚠️  Failed to delete {item.name}: {e}")

    if total_deleted > 0:
        click.echo(f"\n✅ Deleted {total_deleted} file(s)")
        click.echo(f"📁 Test images preserved in: {TEST_IMAGES_DIR}")
    else:
        click.echo("\n✨ Already clean - no files to delete")


if __name__ == "__main__":
    test()
