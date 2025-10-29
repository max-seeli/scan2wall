"""
Mesh Conversion Module

Handles GLB → USD conversion with physics properties and scaling.
Uses Omni's AssetConverter to preserve textures (unlike Isaac Lab's MeshConverter).
"""

import os
import asyncio
from pxr import Usd, UsdGeom, UsdPhysics, UsdShade, Gf, PhysxSchema
import omni.kit.app
# NOTE: omni.kit.asset_converter must be imported AFTER Isaac Sim initializes,
# so we import it lazily inside functions (not at module level)


def convert_glb_to_usd(
    asset_path: str,
    usd_dir: str,
    mass: float = 1.0,
    collision_approximation: str = "convexHull"
) -> str:
    """
    Convert GLB mesh to USD format using Omni's AssetConverter (preserves textures).

    This uses Isaac Sim's native asset converter which preserves materials and textures,
    unlike Isaac Lab's MeshConverter which strips visual data.

    Args:
        asset_path: Path to input GLB file
        usd_dir: Directory where USD will be saved
        mass: Mass in kg
        collision_approximation: Physics collision shape ("convexHull", "convexDecomposition", etc.)

    Returns:
        Path to the created USD file
    """
    import omni.kit.asset_converter
    print(f"🔄 Converting GLB → USD (preserving textures): {asset_path}")

    # Ensure output directory exists
    os.makedirs(usd_dir, exist_ok=True)

    # Calculate output path
    usd_file = os.path.join(usd_dir, os.path.basename(asset_path).replace('.glb', '.usd'))

    # Step 1: Convert GLB to USD using Omni's converter (preserves textures)
    _convert_glb_with_omni_converter(asset_path, usd_file)

    # Step 2: Add physics properties manually
    _add_physics_properties(usd_file, mass, collision_approximation)

    print(f"✓ USD created with textures: {usd_file}")

    return usd_file


def _convert_glb_with_omni_converter(glb_path: str, usd_path: str) -> None:
    """
    Convert GLB to USD using Omni's AssetConverter (async wrapper).

    This preserves materials and textures from the GLB file.
    """
    # Import here (lazy) - only available after Isaac Sim initializes
    import omni.kit.asset_converter

    # Run async conversion in sync context
    async def convert():
        converter = omni.kit.asset_converter.get_instance()

        # Configure converter to preserve materials and textures
        context = omni.kit.asset_converter.AssetConverterContext()
        context.ignore_materials = False  # KEEP materials!
        context.ignore_animations = True
        context.ignore_cameras = True
        context.ignore_lights = True
        context.single_mesh = False
        context.smooth_normals = True
        context.export_preview_surface = True  # Use UsdPreviewSurface
        context.use_meter_as_world_unit = True
        context.create_world_as_default_root_prim = False
        context.embed_textures = True  # Embed textures in USD (CRITICAL for textures!)

        # Run conversion
        task = converter.create_converter_task(glb_path, usd_path, None, context)
        success = await task.wait_until_finished()

        if not success:
            error = task.get_status()
            raise RuntimeError(f"Asset conversion failed: {error}")

    # Execute async conversion
    asyncio.ensure_future(convert())

    # Wait for conversion to complete (pump Omni event loop)
    app = omni.kit.app.get_app_interface()
    max_iterations = 1000
    for _ in range(max_iterations):
        app.update()
        if os.path.exists(usd_path):
            break

    if not os.path.exists(usd_path):
        raise RuntimeError(f"Conversion timed out - USD file not created: {usd_path}")

    print(f"  ✓ GLB converted to USD with materials preserved")


def _add_physics_properties(
    usd_file: str,
    mass: float,
    collision_approximation: str
) -> None:
    """
    Add physics properties to USD file.

    Manually adds rigid body, collision, and mass properties to the mesh
    since Omni's AssetConverter doesn't add physics.

    Args:
        usd_file: Path to USD file
        mass: Mass in kg
        collision_approximation: Collision shape type
    """
    stage = Usd.Stage.Open(usd_file)

    # Find the geometry root (typically the default prim or first mesh)
    root_prim = stage.GetDefaultPrim()
    if not root_prim:
        # Find first Xform or Mesh prim
        for prim in stage.Traverse():
            if prim.IsA(UsdGeom.Xform) or prim.IsA(UsdGeom.Mesh):
                root_prim = prim
                stage.SetDefaultPrim(root_prim)
                break

    if not root_prim:
        raise RuntimeError("Could not find root prim for physics setup")

    print(f"  Adding physics to: {root_prim.GetPath()}")

    # 1. Add RigidBodyAPI
    if not root_prim.HasAPI(UsdPhysics.RigidBodyAPI):
        rigid_api = UsdPhysics.RigidBodyAPI.Apply(root_prim)
        rigid_api.CreateRigidBodyEnabledAttr().Set(True)
        print(f"  ✓ Added RigidBodyAPI")

    # 2. Add MassAPI and set mass
    if not root_prim.HasAPI(UsdPhysics.MassAPI):
        mass_api = UsdPhysics.MassAPI.Apply(root_prim)
        mass_api.CreateMassAttr().Set(mass)
        print(f"  ✓ Set mass: {mass} kg")

    # 3. Add collision to all meshes
    collision_count = 0
    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            if not prim.HasAPI(UsdPhysics.CollisionAPI):
                collision_api = UsdPhysics.CollisionAPI.Apply(prim)
                collision_count += 1

                # Add collision approximation
                if collision_approximation != "none":
                    if not prim.HasAPI(UsdPhysics.MeshCollisionAPI):
                        mesh_collision_api = UsdPhysics.MeshCollisionAPI.Apply(prim)
                        mesh_collision_api.CreateApproximationAttr().Set(collision_approximation)

    if collision_count > 0:
        print(f"  ✓ Added collision to {collision_count} mesh(es) (type: {collision_approximation})")

    stage.Save()
    print(f"  ✓ Physics properties added")


def apply_physics_properties(
    usd_file: str,
    static_friction: float,
    dynamic_friction: float,
    restitution: float
) -> None:
    """Apply physics material properties to USD file."""
    stage = Usd.Stage.Open(usd_file)
    
    for prim in stage.Traverse():
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            if not prim.HasAPI(UsdPhysics.MaterialAPI):
                UsdPhysics.MaterialAPI.Apply(prim)
            
            mat = UsdPhysics.MaterialAPI(prim)
            mat.CreateStaticFrictionAttr().Set(static_friction)
            mat.CreateDynamicFrictionAttr().Set(dynamic_friction)
            mat.CreateRestitutionAttr().Set(restitution)
            break
    
    stage.Save()


def scale_mesh_to_real_size(usd_file: str, target_size_meters: float) -> None:
    """Scale mesh so its max dimension equals target_size_meters."""
    import logging
    logger = logging.getLogger(__name__)

    stage = Usd.Stage.Open(usd_file)
    root = stage.GetDefaultPrim()

    # Get current max dimension
    bbox = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ['default']).ComputeWorldBound(root)
    bbox_size = bbox.ComputeAlignedBox().GetSize()
    current_max = max(bbox_size)

    logger.info(f"📏 Mesh bbox before scaling: {bbox_size[0]:.3f}m × {bbox_size[1]:.3f}m × {bbox_size[2]:.3f}m (max: {current_max:.3f}m)")
    logger.info(f"🎯 Target max dimension: {target_size_meters:.3f}m")

    # Apply scale transform
    scale_factor = target_size_meters / current_max if current_max > 0 else 1.0
    logger.info(f"📐 Applying scale factor: {scale_factor:.4f}")

    xform = UsdGeom.Xformable(root)

    # Reuse existing scale op if present
    scale_op = next((op for op in xform.GetOrderedXformOps()
                     if op.GetOpType() == UsdGeom.XformOp.TypeScale), None)
    if not scale_op:
        scale_op = xform.AddScaleOp(UsdGeom.XformOp.PrecisionFloat)

    scale_op.Set(Gf.Vec3f(scale_factor, scale_factor, scale_factor))
    stage.Save()

    logger.info(f"✓ Mesh scaled: {current_max:.3f}m → {target_size_meters:.3f}m")


def store_metadata(
    usd_file: str,
    object_type: str = None,
    scene_description: str = None
) -> None:
    """
    Store custom metadata in USD file.

    Args:
        usd_file: Path to USD file
        object_type: Object type from inference (e.g., "soccer ball", "coffee mug")
        scene_description: Scene description from inference
    """
    stage = Usd.Stage.Open(usd_file)
    root_prim = stage.GetDefaultPrim()

    if root_prim:
        if object_type:
            root_prim.SetCustomDataByKey("scan2wall:object_type", object_type)
            print(f"✓ Stored object type metadata: {object_type}")
        if scene_description:
            root_prim.SetCustomDataByKey("scan2wall:scene_description", scene_description)
            print(f"✓ Stored scene description metadata: {scene_description}")

    stage.Save()
