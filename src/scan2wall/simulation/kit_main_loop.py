"""
Isaac Kit Main Loop Module

Processes jobs from the queue on Isaac Kit's main thread.
Separated from HTTP handling for clarity and testability.
"""
from pathlib import Path
import os
import time
import numpy as np
import logging

logger = logging.getLogger(__name__)

# Isaac stuff
import torch
from pxr import Gf, Usd, Sdf, UsdGeom, UsdPhysics, PhysxSchema
from isaaclab.assets import RigidObject, RigidObjectCfg, Articulation, ArticulationCfg
# NOTE: Not importing DeformableObject - deformable physics is currently disabled
# (Isaac Sim has a limitation where deformable visual meshes don't update during simulation)
import isaaclab.sim as sim_utils

# scan2wall stuff
from scan2wall.simulation import mesh_converter, material_handler, usdz_packager, scene_builder, usd_diagnostics
from scan2wall.simulation.physics_runner import (
    create_static_camera,
    create_follow_camera,
    update_follow_camera_position,
    apply_throwing_velocity,
    convert_frames_to_uint8,
    ffmpeg_encode_from_memory
)
from scan2wall.simulation.rendering_utils import (
    linear_to_srgb_gpu,
    inspect_pixel_values,
    save_color_comparison,
    create_watermark_tensor
)

def _first_mesh_under(stage, root_path: str) -> str | None:
    """Find the first Mesh prim under a given root path."""
    root = stage.GetPrimAtPath(root_path)
    if not root.IsValid():
        return None
    for p in Usd.PrimRange(root):
        if p.GetTypeName() == "Mesh":
            return p.GetPath().pathString
    return None

def store_deformable_properties(usd_file, youngs_modulus_pa, poissons_ratio, rigidity_type):
    """Store deformable material properties as custom USD attributes (metadata only).

    The PhysX deformable schema will be applied at runtime by Isaac Lab's
    schemas.define_deformable_body_properties() function, which properly finds
    the mesh prim and applies the schema with correct tetrahedral mesh generation.
    """
    from pxr import Usd, Sdf

    stage = Usd.Stage.Open(usd_file)
    root_prim = stage.GetDefaultPrim()

    if not root_prim:
        logger.warning("No default prim found, using first prim")
        root_prim = stage.GetPrimAtPath(stage.GetPseudoRoot().GetChildren()[0].GetPath())

    # Store metadata as custom attributes (read at runtime)
    root_prim.CreateAttribute("deformable:rigidityType", Sdf.ValueTypeNames.String).Set(rigidity_type)
    root_prim.CreateAttribute("deformable:youngsModulus", Sdf.ValueTypeNames.Double).Set(youngs_modulus_pa)
    root_prim.CreateAttribute("deformable:poissonsRatio", Sdf.ValueTypeNames.Double).Set(poissons_ratio)

    stage.Save()
    logger.info(f"✓ Stored deformable metadata: E={youngs_modulus_pa/1e9:.4f} GPa, ν={poissons_ratio}")
    logger.info(f"   (PhysX schema will be applied at runtime)")

def process_convert_job(job_id, data, job_results):
    """
    Process GLB → USDZ conversion job.

    Args:
        job_id: Job identifier
        data: Job data containing glb_path, json_path, usd_dir
        job_results: Shared results dictionary
    """
    try:
        glb_path = data['glb_path']
        json_path = data['json_path']
        usd_dir = data['usd_dir']

        # Read JSON properties file
        import json
        with open(json_path, 'r') as f:
            properties = json.load(f)

        print('📋 Raw properties:', json.dumps(properties, indent=2))
        # Handle both old nested structure and new flat structure
        def get_value(obj, key, default=None):
            """Get value from either nested {'value': x} or direct value."""
            val = obj.get(key, default)
            if isinstance(val, dict) and 'value' in val:
                return val['value']  # Old nested structure
            return val  # New flat structure

        mass = get_value(properties, 'weight_kg', 1.0)
        static_friction = properties.get('friction_coefficients', {}).get('static', 0.6)
        dynamic_friction = properties.get('friction_coefficients', {}).get('dynamic', 0.5)
        restitution = get_value(properties, 'restitution', 0.5)

        # Extract dimensions with backward compatibility
        dims = properties.get('dimensions_m', {})
        print(f'📐 Dimensions dict: {dims}')
        lvals = []
        for k in ['length', 'width', 'height']:
            if k in dims:
                val = dims[k]
                if isinstance(val, dict) and 'value' in val:
                    lvals.append(val['value'])  # Old nested structure
                elif isinstance(val, (int, float)):
                    lvals.append(val)  # New flat structure

        print(f'📏 Extracted dimension values: {lvals}')
        maxdim = np.max(lvals) if lvals else 1.0

        if not lvals:
            logger.warning(f"⚠️  NO DIMENSIONS FOUND! Defaulting to maxdim=1.0m. Check Gemini inference.")
            logger.warning(f"    Properties had dimensions_m: {dims}")
        else:
            logger.info(f"✓ Dimensions extracted: length={lvals[0] if len(lvals) > 0 else 'N/A'}m, "
                       f"width={lvals[1] if len(lvals) > 1 else 'N/A'}m, "
                       f"height={lvals[2] if len(lvals) > 2 else 'N/A'}m → maxdim={maxdim}m")

        # Handle rigidity with defaults (default to rigid if not specified)
        rigidity = properties.get('rigidity', {})
        rigidity_type = rigidity.get('type', 'rigid')
        youngs_modulus = rigidity.get('youngs_modulus_gpa', None)
        poissons_ratio = rigidity.get('poissons_ratio', None)

        object_type = properties.get('object_type', None)
        scene_description = properties.get('scene_description', None)

        # Step 1: Convert with appropriate collision
        if rigidity_type == "rigid":
            collision_approx = "convexHull"
        elif rigidity_type == "deformable":
            # For Flex deformables, skip collision during conversion
            # Isaac Sim 5.0 Flex system will generate particle-based collision at runtime
            # NOTE: The mesh should be watertight (repaired in coordinator before conversion)
            collision_approx = "none"
        else:
            collision_approx = "none"
        
        usd_file = mesh_converter.convert_glb_to_usd(
            asset_path=glb_path,
            usd_dir=usd_dir,
            mass=mass,
            collision_approximation=collision_approx
        )

        mesh_converter.store_metadata(
            usd_file=usd_file,
            object_type=object_type,
            scene_description=scene_description
        )

        mesh_converter.scale_mesh_to_real_size(
            usd_file=usd_file,
            target_size_meters=maxdim
        )

        mesh_converter.apply_physics_properties(
            usd_file=usd_file,
            static_friction=static_friction,
            dynamic_friction=dynamic_friction,
            restitution=restitution
        )

        if rigidity_type == "deformable" and youngs_modulus and poissons_ratio:
            store_deformable_properties(
                usd_file=usd_file,
                youngs_modulus_pa=youngs_modulus * 1e9,
                poissons_ratio=poissons_ratio,
                rigidity_type=rigidity_type
            )

        material_handler.convert_gltf_materials_to_preview_surface(usd_file)

        textures_dir = os.path.join(usd_dir, 'textures')
        usdz_packager.fix_texture_permissions(textures_dir, usd_dir)

        usdz_file = usdz_packager.package_usd_to_usdz(usd_file, fix_permissions=True)
        usdz_packager.fix_usdz_archive_texture_paths(usdz_file)

        job_results[job_id] = {"status": "completed", "usdz_path": usdz_file}
        logger.info(f"Conversion complete: {job_id}")
    except Exception as e:
        logger.error(f"Conversion failed: {job_id} - {e}", exc_info=True)
        job_results[job_id] = {"status": "failed", "error": str(e)}


def process_create_base_scene_job(job_id, data, job_results, sim_context):
    """
    Process base scene creation job.

    Args:
        job_id: Job identifier
        data: Job data dictionary containing:
            - output_path: Where to save scene USD
        job_results: Shared results dictionary
        sim_context: Isaac Sim simulation context
    """
    try:
        output_path = data['output_path']
        result_path = scene_builder.create_base_scene_usd(output_path, sim_context)
        job_results[job_id] = {
            "status": "completed",
            "output_path": result_path
        }
        logger.info(f"Base scene created: {job_id}")
    except Exception as e:
        logger.error(f"Base scene creation failed: {job_id} - {e}", exc_info=True)
        job_results[job_id] = {"status": "failed", "error": str(e)}


def process_simulation_job(job_id, data, job_results, sim_context, camera_state):
    """Process physics simulation job."""
    try:
        from pxr import Usd  # Import at function level to avoid UnboundLocalError
        start_time = time.time()

        # Extract parameters
        usd_path = data['usd_path']
        out_dir = data.get('out_dir', '/workspace/s2w-data/recordings')
        video_length = data.get('video_length', 200)
        fps = data.get('fps', 50)
        skip_first = data.get('skip_first', 0)  # Don't skip frames, show full throw
        request_job_id = data.get('job_id', 'unknown')

        stage = sim_context.stage

        # Clean up old scene
        for path in ["/World/Objects", "/World/StaticObjects"]:
            if stage.GetPrimAtPath(path).IsValid():
                stage.RemovePrim(path)

        # Load base scene with wall
        base_scene_path = "/workspace/s2w-scripts/scenes/throw_against_brick_wall.usd"
        if not os.path.exists(base_scene_path):
            scene_builder.create_base_scene_usd(base_scene_path, sim_context)
        scene_builder.load_base_scene(base_scene_path, stage)

        # Pre-settle phase: Let wall stabilize before spawning object (PhysX best practice)
        # This allows contacts to stabilize and friction cones to align
        print(f"🧱 Pre-settling wall (150 steps)...", flush=True)
        sim_context.reset()
        dt = sim_context.get_physics_dt()
        settle_steps = 150  # 1.5 seconds at 100Hz physics timestep
        for step in range(settle_steps):
            sim_context.step(render=False)
        print(f"✅ Wall pre-settled", flush=True)

        # Load object temporarily to check rigidity type
        scene_builder.load_usdz_object(stage, usd_path, position=(0.0, 0.0, 0.5))
        obj_prim = stage.GetPrimAtPath("/World/Objects/custom_obj")
        rigidity_attr = obj_prim.GetAttribute("deformable:rigidityType")
        rigidity_type = rigidity_attr.Get() if rigidity_attr else "rigid"

        # Get deformable parameters if present
        youngs_modulus_attr = obj_prim.GetAttribute("deformable:youngsModulus")
        poissons_ratio_attr = obj_prim.GetAttribute("deformable:poissonsRatio")
        youngs_modulus = youngs_modulus_attr.Get() if youngs_modulus_attr else None
        poissons_ratio = poissons_ratio_attr.Get() if poissons_ratio_attr else None

        # Get bounding box from temp object
        from pxr import UsdGeom, Gf
        bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default"])
        bbox = bbox_cache.ComputeWorldBound(obj_prim)
        bbox_range = bbox.ComputeAlignedRange()
        size = bbox_range.GetSize()
        bbox_min = bbox_range.GetMin()
        bbox_max = bbox_range.GetMax()

        # Phase B: Calculate spawn height with proper clearance
        # Rule: 5cm minimum clearance OR 20% of largest dimension
        clearance = max(0.05, 0.2 * max(size[0], size[1], size[2]))
        # Spawn so the bottom of the object is at clearance height above ground (z=0)
        # bbox_min[2] is the lowest point in current position, size[2] is height
        spawn_z = size[2] / 2.0 + clearance

        print(f"📏 Object bbox: min={[f'{x:.3f}' for x in bbox_min]}, max={[f'{x:.3f}' for x in bbox_max]}", flush=True)
        print(f"📏 Object size: {size[0]:.2f}m x {size[1]:.2f}m x {size[2]:.2f}m", flush=True)
        print(f"📍 Spawn height: {spawn_z:.3f}m (clearance: {clearance:.3f}m)", flush=True)
        print(f"🔬 Rigidity type: {rigidity_type}", flush=True)

        # Phase B: Reposition root Xform to spawn height (preserve existing scale!)
        print(f"🔧 Phase B: Positioning root Xform at spawn height...", flush=True)
        xformable = UsdGeom.Xformable(obj_prim)

        # Check if object already has a scale op (from conversion)
        existing_scale_op = None
        for op in xformable.GetOrderedXformOps():
            if op.GetOpType() == UsdGeom.XformOp.TypeScale:
                existing_scale_op = op
                existing_scale = op.Get()
                print(f"   📐 Preserving existing scale: {existing_scale}", flush=True)
                break

        # Clear and rebuild transforms, preserving scale
        xformable.ClearXformOpOrder()

        # Re-add scale first if it existed
        if existing_scale_op:
            scale_op = xformable.AddScaleOp(UsdGeom.XformOp.PrecisionFloat)
            scale_op.Set(existing_scale)

        # Add translation
        xformable.AddTranslateOp().Set((0.0, 0.0, spawn_z))
        print(f"   ✓ Root Xform positioned at (0, 0, {spawn_z:.3f})", flush=True)

        # DEFORMABLE PHYSICS DISABLED
        # Isaac Sim has a fundamental limitation where deformable body visual meshes
        # don't update during simulation (they remain frozen). This affects both
        # Isaac Lab's DeformableObject wrapper and native deformableUtils API.
        # For now, treating all objects as rigid bodies.

        if False:  # rigidity_type == "deformable":
            # Deformable code disabled - see comment above
            pass
        else:
            print(f"🪨 Creating rigid object...", flush=True)
            # Create rigid object
            rigid_cfg = RigidObjectCfg(
                prim_path="/World/Objects/custom_obj",
                spawn=None,
                init_state=RigidObjectCfg.InitialStateCfg(
                    pos=(0.0, 0.0, spawn_z),
                    rot=(1.0, 0.0, 0.0, 0.0)
                )
            )
            physics_obj = RigidObject(cfg=rigid_cfg)
            print(f"✅ Rigid object created", flush=True)

        # Reset simulation to initialize physics
        sim_context.reset()

        # Get physics timestep
        dt = sim_context.get_physics_dt()

        # Create/reset cameras
        if camera_state['camera'] is None:
            camera_state['camera'] = create_static_camera("/World/RenderCamera")
        if camera_state['follow_camera'] is None:
            camera_state['follow_camera'] = create_follow_camera("/World/FollowCamera")

        # Apply throwing velocity
        velocity_tensor = torch.tensor([[0.0, 13.0, 6.0, 0.0, 0.0, 0.0]], device=physics_obj.device)
        physics_obj.write_root_velocity_to_sim(velocity_tensor)

        # Force texture loading by touching all materials
        print(f"🎨 Pre-loading textures...", flush=True)
        import omni.usd
        from pxr import UsdShade

        # Force material system to load all textures
        for prim in stage.Traverse():
            if prim.IsA(UsdShade.Shader):
                shader = UsdShade.Shader(prim)
                for input in shader.GetInputs():
                    # Touch each input to trigger loading
                    _ = input.Get()

        # Run simulation and capture frames
        print(f"🎬 Running {video_length} simulation steps at {fps} FPS", flush=True)
        frames_static = []
        frames_follow = []

        for step in range(video_length):
            physics_obj.write_data_to_sim()
            sim_context.step(render=True)
            physics_obj.update(dt)

            # Update follow camera position
            obj_pos = physics_obj.data.root_state_w[0, :3].cpu().numpy()

            update_follow_camera_position(stage, obj_pos, camera_path="/World/FollowCamera")

            # Update cameras and capture frames
            camera_state['camera'].update(dt)
            camera_state['follow_camera'].update(dt)

            frame_static = camera_state['camera'].data.output["rgb"][0].clone()
            frame_follow = camera_state['follow_camera'].data.output["rgb"][0].clone()

            frames_static.append(frame_static)
            frames_follow.append(frame_follow)

        # Encode videos
        frames_static_numpy, _ = convert_frames_to_uint8(frames_static)
        frames_follow_numpy, _ = convert_frames_to_uint8(frames_follow)

        static_video = os.path.join(out_dir, f"{request_job_id}_static.mp4")
        follow_video = os.path.join(out_dir, f"{request_job_id}_follow.mp4")

        ffmpeg_encode_from_memory(frames_static_numpy, static_video, fps, skip_first=skip_first, job_id=request_job_id)
        ffmpeg_encode_from_memory(frames_follow_numpy, follow_video, fps, skip_first=skip_first, job_id=request_job_id)

        elapsed = time.time() - start_time
        logger.info(f"Simulation complete in {elapsed:.2f}s: {job_id}")

        job_results[job_id] = {
            "status": "completed",
            "static_video": static_video,
            "follow_video": follow_video,
            "frames": video_length
        }

    except Exception as e:
        logger.error(f"Simulation failed: {job_id} - {e}", exc_info=True)
        job_results[job_id] = {"status": "failed", "error": str(e)}
