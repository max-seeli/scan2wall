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

        # Track the actual render prim path (may differ for deformables)
        deformable_render_path = None

        # Nuke stray spawner container if present (defensive)
        if stage.GetPrimAtPath("/World/Objects/deformable_obj").IsValid():
            stage.RemovePrim("/World/Objects/deformable_obj")

        # Phase B: Reposition root Xform for BOTH rigid and deformable
        # This ensures the visual and physics meshes are at the correct spawn position
        print(f"🔧 Phase B: Positioning root Xform at spawn height...", flush=True)
        xformable = UsdGeom.Xformable(obj_prim)
        xformable.ClearXformOpOrder()
        xformable.AddTranslateOp().Set((0.0, 0.0, spawn_z))
        print(f"   ✓ Root Xform positioned at (0, 0, {spawn_z:.3f})", flush=True)

        if rigidity_type == "deformable":
            print("🧬 Setting up deformable (mesh-anchored)…", flush=True)
            print(f"   Young's modulus: {youngs_modulus/1e9:.4f} GPa", flush=True)
            print(f"   Poisson's ratio: {poissons_ratio}", flush=True)

            # Find the actual mesh we imported under the loaded object
            mesh_prim_path = _first_mesh_under(stage, "/World/Objects/custom_obj")
            if not mesh_prim_path:
                raise RuntimeError("No Mesh prim found under /World/Objects/custom_obj")

            mesh_prim = stage.GetPrimAtPath(mesh_prim_path)
            print(f"   🎯 Target mesh prim: {mesh_prim_path}", flush=True)

            # Diagnostic: Check mesh geometry
            mesh_geom = UsdGeom.Mesh(mesh_prim)
            mesh_points = mesh_geom.GetPointsAttr().Get()
            if mesh_points:
                print(f"   📊 Mesh has {len(mesh_points)} vertices", flush=True)
                mesh_points_array = np.array(mesh_points)
                mesh_local_min = mesh_points_array.min(axis=0)
                mesh_local_max = mesh_points_array.max(axis=0)
                print(f"   📐 Mesh local bounds: min=[{mesh_local_min[0]:.3f}, {mesh_local_min[1]:.3f}, {mesh_local_min[2]:.3f}], max=[{mesh_local_max[0]:.3f}, {mesh_local_max[1]:.3f}, {mesh_local_max[2]:.3f}]", flush=True)
            else:
                print(f"   ⚠️  Warning: Mesh has no points!", flush=True)

            # Clean ALL rigid body APIs that conflict with deformables (leftover from conversion)
            # Deformables use a completely different physics system
            apis_removed = []

            # Collision APIs
            if mesh_prim.HasAPI(UsdPhysics.CollisionAPI):
                mesh_prim.RemoveAPI(UsdPhysics.CollisionAPI)
                apis_removed.append("CollisionAPI")
            if mesh_prim.HasAPI(UsdPhysics.MeshCollisionAPI):
                mesh_prim.RemoveAPI(UsdPhysics.MeshCollisionAPI)
                apis_removed.append("MeshCollisionAPI")
            if mesh_prim.HasAPI(PhysxSchema.PhysxCollisionAPI):
                mesh_prim.RemoveAPI(PhysxSchema.PhysxCollisionAPI)
                apis_removed.append("PhysxCollisionAPI")

            # Rigid body APIs (these MUST be removed for deformables)
            if mesh_prim.HasAPI(UsdPhysics.RigidBodyAPI):
                mesh_prim.RemoveAPI(UsdPhysics.RigidBodyAPI)
                apis_removed.append("RigidBodyAPI")
            if mesh_prim.HasAPI(UsdPhysics.MassAPI):
                mesh_prim.RemoveAPI(UsdPhysics.MassAPI)
                apis_removed.append("MassAPI")

            # Also check parent prim for rigid body artifacts
            parent_prim = obj_prim
            parent_apis_removed = []
            if parent_prim.HasAPI(UsdPhysics.RigidBodyAPI):
                parent_prim.RemoveAPI(UsdPhysics.RigidBodyAPI)
                parent_apis_removed.append("RigidBodyAPI")
            if parent_prim.HasAPI(UsdPhysics.MassAPI):
                parent_prim.RemoveAPI(UsdPhysics.MassAPI)
                parent_apis_removed.append("MassAPI")
            if parent_prim.HasAPI(UsdPhysics.CollisionAPI):
                parent_prim.RemoveAPI(UsdPhysics.CollisionAPI)
                parent_apis_removed.append("CollisionAPI")

            if apis_removed:
                print(f"   🧹 Removed mesh APIs: {', '.join(apis_removed)}", flush=True)
            else:
                print(f"   ✓ No stale mesh APIs found", flush=True)

            if parent_apis_removed:
                print(f"   🧹 Removed parent APIs: {', '.join(parent_apis_removed)}", flush=True)

            # Create & bind deformable **material** using Isaac Lab's spawner
            from isaaclab.sim.spawners.materials import DeformableBodyMaterialCfg
            material_path = mesh_prim_path + "/DeformableMaterial"
            deform_mat_cfg = DeformableBodyMaterialCfg(
                youngs_modulus=youngs_modulus,
                poissons_ratio=poissons_ratio,
                dynamic_friction=0.4,
            )
            deform_mat_cfg.func(material_path, deform_mat_cfg)
            sim_utils.bind_physics_material(mesh_prim_path, material_path, stage=stage)
            print("   🔗 Bound deformable material to mesh", flush=True)

            # Apply the **body** API to the mesh
            body_api = PhysxSchema.PhysxDeformableBodyAPI.Apply(mesh_prim)
            print("   ✓ Applied PhysxDeformableBodyAPI", flush=True)

            # NOTE: Deformables do NOT use UsdPhysics.CollisionAPI (that's for rigid bodies)
            # Deformable collision is handled by the voxelization system via define_deformable_body_properties
            # The PhysxDeformableBodyAPI creates its own collision representation from the tetrahedral mesh

            # Define PhysX deformable properties via Isaac Lab helper (does voxelization/cooking)
            from isaaclab.sim.schemas import schemas_cfg, schemas

            # CRITICAL: Set kinematic enabled to False for dynamic deformables
            # Collision simplification disabled to avoid cooking conflicts
            deformable_cfg = schemas_cfg.DeformableBodyPropertiesCfg(
                kinematic_enabled=False,  # Must be False for dynamic deformables
                solver_position_iteration_count=20,  # Increased for stability
                vertex_velocity_damping=0.01,  # Slightly higher damping
                simulation_hexahedral_resolution=3,  # Lower resolution for robustness
                collision_simplification=False,  # Disable to avoid mesh conflicts
                self_collision=False,
            )

            print("   🔨 Starting deformable voxelization...", flush=True)
            schemas.define_deformable_body_properties(mesh_prim_path, deformable_cfg, stage)
            print("   ✅ Deformable voxelization complete (resolution: 3)", flush=True)

            stage.Save()

            # Instantiate the runtime wrapper **on the mesh** (no spawning!)
            # NOTE: init_state is applied to the mesh, but the root Xform has already been positioned
            deform_cfg = DeformableObjectCfg(
                prim_path=mesh_prim_path,
                spawn=None,
                init_state=DeformableObjectCfg.InitialStateCfg(
                    pos=(0.0, 0.0, 0.0),  # Relative to parent, which is already at spawn_z
                    rot=(1.0, 0.0, 0.0, 0.0),
                ),
            )
            physics_obj = DeformableObject(cfg=deform_cfg)
            print("✅ Deformable object created (mesh-anchored)", flush=True)

            # Track render path for camera
            deformable_render_path = mesh_prim_path
            print(f"   📹 Tracking mesh: {deformable_render_path}", flush=True)
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

        # Diagnostic: Verify deformable initialization after reset
        if rigidity_type == "deformable":
            print("🔍 Verifying deformable initialization...", flush=True)
            if hasattr(physics_obj.data, 'nodal_pos_w') and physics_obj.data.nodal_pos_w is not None:
                nodal_pos = physics_obj.data.nodal_pos_w[0].cpu().numpy()
                nodal_min = nodal_pos.min(axis=0)
                nodal_max = nodal_pos.max(axis=0)
                nodal_centroid = nodal_pos.mean(axis=0)
                print(f"   📊 Nodal positions: {nodal_pos.shape[0]} nodes", flush=True)
                print(f"   📐 Nodal bounds: min=[{nodal_min[0]:.3f}, {nodal_min[1]:.3f}, {nodal_min[2]:.3f}], max=[{nodal_max[0]:.3f}, {nodal_max[1]:.3f}, {nodal_max[2]:.3f}]", flush=True)
                print(f"   📍 Nodal centroid: [{nodal_centroid[0]:.3f}, {nodal_centroid[1]:.3f}, {nodal_centroid[2]:.3f}]", flush=True)

                # Check if object is above ground
                if nodal_min[2] < -0.01:  # Allow 1cm tolerance
                    print(f"   ⚠️  WARNING: Object is below ground! Lowest point: {nodal_min[2]:.3f}m", flush=True)
                elif nodal_min[2] < clearance * 0.5:
                    print(f"   ⚠️  WARNING: Object is very close to ground! Lowest point: {nodal_min[2]:.3f}m (expected >{clearance:.3f}m)", flush=True)
                else:
                    print(f"   ✓ Object is properly positioned above ground", flush=True)
            else:
                print(f"   ⚠️  WARNING: Nodal positions not available after reset!", flush=True)

        # Create/reset cameras
        if camera_state['camera'] is None:
            camera_state['camera'] = create_static_camera("/World/RenderCamera")
        if camera_state['follow_camera'] is None:
            camera_state['follow_camera'] = create_follow_camera("/World/FollowCamera")

        # Apply throwing velocity (different for rigid vs deformable)

        if rigidity_type == "deformable":
            # For deformable objects, apply velocity to all nodal points
            print(f"   Applying nodal velocity to deformable body...", flush=True)
            # Deformable objects need per-node velocity, not root velocity
            # For now, skip initial velocity for deformable - let gravity and contact forces handle it
            # TODO: Implement proper nodal velocity application
            print(f"   ⚠️  Note: Initial throwing velocity not implemented for deformable objects yet", flush=True)
        else:
            # For rigid objects, apply root velocity
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

        # Warmup: Run simulation steps to let renderer stabilize
        # NOTE: Warmup disabled to capture initial frames
        print(f"🔥 Skipping warmup - capturing from frame 0...", flush=True)
        for i in range(0):
            physics_obj.write_data_to_sim()
            sim_context.step(render=True)
            physics_obj.update(dt)
            camera_state['camera'].update(dt)
            camera_state['follow_camera'].update(dt)

            if i % 10 == 0:
                print(f"  Warmup frame {i}/0", flush=True)

        # Run simulation and capture frames
        print(f"🎬 Running {video_length} simulation steps at {fps} FPS", flush=True)
        frames_static = []
        frames_follow = []

        for step in range(video_length):
            # Write data, step physics, update buffers (Isaac Lab pattern)
            # Note: For deformable bodies, nodal positions are computed BY the simulation,
            # not written TO it, so write_data_to_sim() may not be needed
            if rigidity_type != "deformable":
                physics_obj.write_data_to_sim()

            sim_context.step(render=True)  # Must render to update camera textures and deformable visuals!
            physics_obj.update(dt)

            # Update follow camera position (different for rigid vs deformable)
            if rigidity_type == "deformable":
                # For deformable objects, get centroid of nodal positions
                nodal_pos = physics_obj.data.nodal_pos_w[0].cpu().numpy()  # Shape: (num_nodes, 3)
                obj_pos = nodal_pos.mean(axis=0)  # Centroid of all nodes

                # Validate nodal positions are reasonable
                if step == 0 or step % 50 == 0:
                    nodal_min_z = nodal_pos[:, 2].min()
                    nodal_max_z = nodal_pos[:, 2].max()
                    print(f"  📍 Step {step}: centroid z={obj_pos[2]:.3f}m, z-range=[{nodal_min_z:.3f}, {nodal_max_z:.3f}]", flush=True)

                    # Warning if object appears to be falling through floor
                    if nodal_min_z < -0.05:
                        print(f"  ⚠️  WARNING: Object is falling through floor! Min z={nodal_min_z:.3f}m", flush=True)
            else:
                obj_pos = physics_obj.data.root_state_w[0, :3].cpu().numpy()

            update_follow_camera_position(stage, obj_pos, camera_path="/World/FollowCamera")

            # Update cameras and capture frames
            camera_state['camera'].update(dt)
            camera_state['follow_camera'].update(dt)

            frame_static = camera_state['camera'].data.output["rgb"][0].clone()
            frame_follow = camera_state['follow_camera'].data.output["rgb"][0].clone()

            # Debug: Save first frame to check if textures are visible
            if step == 0:
                from PIL import Image as PILImage
                debug_img = (frame_static.cpu().numpy() * 255).astype(np.uint8)
                PILImage.fromarray(debug_img).save(f"{out_dir}/debug_frame0_{request_job_id}.png")
                print(f"  💾 Saved debug frame: debug_frame0_{request_job_id}.png", flush=True)
                print(f"  📊 Frame stats: min={debug_img.min()}, max={debug_img.max()}, mean={debug_img.mean():.1f}", flush=True)

            frames_static.append(frame_static)
            frames_follow.append(frame_follow)

        # Log final position
        if rigidity_type == "deformable":
            final_pos = physics_obj.data.nodal_pos_w[0].cpu().numpy().mean(axis=0)
            print(f"  🏁 Final z-position: {final_pos[2]:.3f}m (started at {spawn_z:.3f}m)", flush=True)

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
