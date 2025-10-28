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
from pxr import Gf, Usd, Sdf, UsdGeom
from isaaclab.assets import RigidObject, RigidObjectCfg, Articulation, ArticulationCfg, DeformableObject, DeformableObjectCfg
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

def store_deformable_properties(usd_file, youngs_modulus_pa, poissons_ratio, rigidity_type):
    """Store deformable material properties as custom USD attributes."""
    from pxr import Usd, Sdf

    stage = Usd.Stage.Open(usd_file)
    root_prim = stage.GetDefaultPrim()

    if not root_prim:
        logger.warning("No default prim found, using first prim")
        root_prim = stage.GetPrimAtPath(stage.GetPseudoRoot().GetChildren()[0].GetPath())

    root_prim.CreateAttribute("deformable:rigidityType", Sdf.ValueTypeNames.String).Set(rigidity_type)
    root_prim.CreateAttribute("deformable:youngsModulus", Sdf.ValueTypeNames.Double).Set(youngs_modulus_pa)
    root_prim.CreateAttribute("deformable:poissonsRatio", Sdf.ValueTypeNames.Double).Set(poissons_ratio)

    stage.Save()
    logger.info(f"Stored deformable properties: E={youngs_modulus_pa/1e9:.4f} GPa, ν={poissons_ratio}")

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

        mass = properties['weight_kg']['value']
        static_friction = properties['friction_coefficients']['static']
        dynamic_friction = properties['friction_coefficients']['dynamic']
        restitution = properties['restitution']['value']

        lvals = [properties['dimensions_m'][k]['value'] for k in properties['dimensions_m']]
        maxdim = np.max(lvals)

        rigidity_type = properties['rigidity']['type']
        youngs_modulus = properties['rigidity']['youngs_modulus_gpa']
        poissons_ratio = properties['rigidity']['poissons_ratio']

        object_type = properties.get('object_type', None)
        scene_description = properties.get('scene_description', None)

        # Step 1: Convert with appropriate collision
        if rigidity_type == "rigid":
            collision_approx = "convexHull"
        elif rigidity_type == "deformable":
            collision_approx = "meshSimplification"  # or "triangleMesh"
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

        # Load object
        scene_builder.load_usdz_object(stage, usd_path, position=(0.0, 0.0, 0.5))

        # Create rigid object
        rigid_cfg = RigidObjectCfg(
            prim_path="/World/Objects/custom_obj",
            spawn=None,
            init_state=RigidObjectCfg.InitialStateCfg(
                pos=(0.0, 0.0, 0.5),
                rot=(1.0, 0.0, 0.0, 0.0)
            )
        )
        rigid_obj = RigidObject(cfg=rigid_cfg)

        # Reset simulation to initialize physics
        sim_context.reset()

        # Create/reset cameras
        if camera_state['camera'] is None:
            camera_state['camera'] = create_static_camera("/World/RenderCamera")
        if camera_state['follow_camera'] is None:
            camera_state['follow_camera'] = create_follow_camera("/World/FollowCamera")

        # Apply throwing velocity
        dt = sim_context.get_physics_dt()
        velocity_tensor = torch.tensor([[0.0, 13.0, 6.0, 0.0, 0.0, 0.0]], device=rigid_obj.device)
        rigid_obj.write_root_velocity_to_sim(velocity_tensor)

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

        # Warmup: Run simulation steps to let renderer stabilize
        print(f"🔥 Warming up renderer (50 frames)...", flush=True)
        for i in range(50):
            rigid_obj.write_data_to_sim()
            sim_context.step(render=True)
            rigid_obj.update(dt)
            camera_state['camera'].update(dt)
            camera_state['follow_camera'].update(dt)

            if i % 10 == 0:
                print(f"  Warmup frame {i}/50", flush=True)

        # Run simulation and capture frames
        print(f"🎬 Running {video_length} simulation steps at {fps} FPS", flush=True)
        frames_static = []
        frames_follow = []

        for step in range(video_length):
            # Write data, step physics, update buffers (Isaac Lab pattern)
            rigid_obj.write_data_to_sim()
            sim_context.step(render=True)  # Must render to update camera textures!
            rigid_obj.update(dt)

            # Update follow camera position
            obj_pos = rigid_obj.data.root_state_w[0, :3].cpu().numpy()
            update_follow_camera_position(stage, obj_pos, camera_path="/World/FollowCamera")

            # Update cameras and capture frames
            camera_state['camera'].update(dt)
            camera_state['follow_camera'].update(dt)

            frame_static = camera_state['camera'].data.output["rgb"][0].clone()
            frame_follow = camera_state['follow_camera'].data.output["rgb"][0].clone()

            # Debug: Save first frame to check if textures are visible
            if step == 0:
                import numpy as np
                from PIL import Image as PILImage
                debug_img = (frame_static.cpu().numpy() * 255).astype(np.uint8)
                PILImage.fromarray(debug_img).save(f"{out_dir}/debug_frame0_{request_job_id}.png")
                print(f"  💾 Saved debug frame: debug_frame0_{request_job_id}.png", flush=True)
                print(f"  📊 Frame stats: min={debug_img.min()}, max={debug_img.max()}, mean={debug_img.mean():.1f}", flush=True)

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
