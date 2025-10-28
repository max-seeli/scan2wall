"""
Scene Building Module

Handles creating and loading Isaac Sim scenes with lights, ground, walls, and objects.
"""

import os
from pxr import Usd, UsdGeom
import isaaclab.sim as sim_utils
import isaacsim.core.utils.prims as prim_utils


def create_base_scene_usd(output_path: str = "/workspace/s2w-scripts/scenes/throw_against_brick_wall.usd", sim_context=None):
    """
    Create and export a pre-built base scene USD file containing:
    - Ground plane with physics materials
    - Lighting setup (sky dome + 3-point lighting)
    - Wall structure

    This eliminates ~5 seconds of scene building per simulation.

    Args:
        output_path: Where to save the base scene USD
        sim_context: Isaac Sim simulation context

    Returns:
        Path to created USD file
    """
    print(f"🏗️  Creating base scene USD: {output_path}")

    stage = sim_context.stage

    # Clear existing scene elements
    world_prim = stage.GetPrimAtPath("/World")
    if world_prim.IsValid():
        child_paths = [child.GetPath() for child in world_prim.GetChildren()]
        for path in child_paths:
            if stage.GetPrimAtPath(path).IsValid():
                stage.RemovePrim(path)

    # Build ground plane
    _create_ground_plane(stage)

    # Add lighting
    _create_lighting(stage)

    # Build wall structure
    build_wall(
        "/World/StaticObjects/Wall",
        width=15,
        height=20,
        brick_width=0.3,
        brick_height=0.15,
        brick_depth=0.15,
        gap=0.0,
        base_xy=(0.15, 10.0),
        z0=0.075
    )

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Export the stage to USD file
    print(f"💾 Exporting base scene to {output_path}...")
    stage.Export(output_path)
    print(f"✅ Base scene USD created: {output_path}")

    return output_path


def load_base_scene(base_scene_path: str, stage: Usd.Stage) -> None:
    """
    Load a pre-built base scene from USD file.

    Args:
        base_scene_path: Path to base scene USD file
        stage: USD stage to load into
    """
    print(f"📦 Loading pre-built base scene from {base_scene_path}")

    root_layer = stage.GetRootLayer()
    if base_scene_path not in root_layer.subLayerPaths:
        root_layer.subLayerPaths.append(base_scene_path)

    print("✅ Base scene loaded")


def build_scene_from_scratch(stage: Usd.Stage) -> None:
    """
    Build scene elements from scratch (fallback if no base scene).

    Creates:
    - Ground plane
    - Lighting (sky dome + 3-point lighting)
    - Wall structure

    Args:
        stage: USD stage to build in
    """
    print("⚠️  Building scene from scratch (use_base_scene=False)...")

    _create_ground_plane(stage)
    _create_lighting(stage)

    # Build wall
    build_wall(
        "/World/StaticObjects/Wall",
        width=15,
        height=20,
        brick_width=0.3,
        brick_height=0.15,
        brick_depth=0.15,
        gap=0.0,
        base_xy=(0.15, 10.0),
        z0=0.075
    )


def load_usdz_object(stage: Usd.Stage, usd_path: str, position: tuple = (0.0, 0.0, 0.5)) -> None:
    """
    Load a USDZ object into the scene.

    Extracts USDZ to temp folder and loads USD directly for better texture access.

    Args:
        stage: USD stage
        usd_path: Path to USDZ file
        position: (x, y, z) position to place object
    """
    print(f"📦 Loading object: {os.path.basename(usd_path)}", flush=True)

    # Check if it's a USDZ (zip) or plain USD
    if usd_path.endswith('.usdz'):
        # Extract USDZ to temp folder for direct texture access
        import zipfile
        import tempfile

        extract_dir = tempfile.mkdtemp(prefix="usdz_")
        print(f"  Extracting USDZ to: {extract_dir}", flush=True)

        with zipfile.ZipFile(usd_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)

        # List extracted contents
        extracted_files = []
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, extract_dir)
                extracted_files.append(rel_path)
                if file.endswith('.png') or file.endswith('.jpg'):
                    file_size = os.path.getsize(full_path)
                    print(f"    📷 Texture: {rel_path} ({file_size} bytes)", flush=True)

        print(f"  Extracted {len(extracted_files)} file(s)", flush=True)

        # Find the USD file in extracted content
        usd_file = None
        for file in os.listdir(extract_dir):
            if file.endswith('.usd') or file.endswith('.usda') or file.endswith('.usdc'):
                usd_file = os.path.join(extract_dir, file)
                break

        if not usd_file:
            raise RuntimeError(f"No USD file found in USDZ archive: {usd_path}")

        print(f"  Loading USD file: {os.path.basename(usd_file)}", flush=True)
    else:
        # Plain USD file - use it directly
        print(f"  Loading USD file directly (not a USDZ): {os.path.basename(usd_path)}", flush=True)
        usd_file = usd_path

    # Fix texture paths: Convert USDZ archive paths to absolute file paths
    from pxr import Sdf, UsdShade
    import shutil
    print(f"  Fixing texture paths to be absolute...", flush=True)

    temp_stage = Usd.Stage.Open(usd_file)
    fixed_count = 0

    # Copy textures to videos folder for inspection
    videos_dir = "/workspace/s2w-data/test/videos"
    os.makedirs(videos_dir, exist_ok=True)

    # Find all texture shader nodes and make their paths absolute
    for prim in temp_stage.Traverse():
        if prim.IsA(UsdShade.Shader):
            shader = UsdShade.Shader(prim)
            file_input = shader.GetInput("file")
            if file_input:
                current_path = file_input.Get()
                if current_path and isinstance(current_path, Sdf.AssetPath):
                    path_str = current_path.path

                    # Strip USDZ archive notation: @archive.usdz@/path/file.png → textures/file.png
                    if '@' in path_str:
                        # Extract the actual path after the second @
                        parts = path_str.split('@')
                        if len(parts) >= 3:
                            path_str = parts[2].lstrip('/')

                    # Make absolute path to extracted texture
                    if not os.path.isabs(path_str):
                        abs_path = os.path.join(extract_dir, path_str)
                        abs_path = os.path.normpath(abs_path)

                        if os.path.exists(abs_path):
                            file_input.Set(Sdf.AssetPath(abs_path))
                            print(f"    Fixed: {current_path.path} → {abs_path}", flush=True)
                            fixed_count += 1

                            # Copy texture to videos folder for inspection
                            try:
                                dest = os.path.join(videos_dir, os.path.basename(abs_path))
                                shutil.copy2(abs_path, dest)
                                print(f"    📷 Copied texture to: {dest}", flush=True)
                            except Exception as e:
                                print(f"    ⚠️  Could not copy texture: {e}", flush=True)
                        else:
                            print(f"    ✗ Texture not found: {abs_path}", flush=True)

    if fixed_count > 0:
        temp_stage.Save()
        print(f"  ✓ Fixed {fixed_count} texture path(s)", flush=True)
    else:
        print(f"  ⚠️  No textures were fixed!", flush=True)

    # Create xform prim for the object
    obj_prim = stage.DefinePrim("/World/Objects/custom_obj", "Xform")

    # Set translation
    xformable = UsdGeom.Xformable(obj_prim)
    xformable.AddTranslateOp().Set(position)

    # Add the USD as a reference (now with absolute texture paths)
    obj_prim.GetReferences().AddReference(usd_file)

    print(f"✓ Object loaded at position {position}", flush=True)

    # Debug: Check material bindings
    from pxr import UsdShade
    import time
    time.sleep(0.5)  # Wait for reference to fully load

    found_materials = False
    for prim in stage.Traverse():
        if prim.GetTypeName() == 'Mesh' and 'custom_obj' in str(prim.GetPath()):
            binding_api = UsdShade.MaterialBindingAPI(prim)
            mat_binding = binding_api.GetDirectBinding()
            if mat_binding:
                bound_mat = mat_binding.GetMaterial()
                if bound_mat:
                    print(f"  ✓ Mesh {prim.GetName()} → Material {bound_mat.GetPath()}", flush=True)
                    found_materials = True

                    # Check shader
                    surface_output = bound_mat.GetSurfaceOutput()
                    if surface_output:
                        connected_source = surface_output.GetConnectedSource()
                        if connected_source:
                            shader = UsdShade.Shader(connected_source[0].GetPrim())
                            print(f"    Shader: {shader.GetIdAttr().Get()}", flush=True)

                            # Check diffuse color input
                            diffuse_input = shader.GetInput("diffuseColor")
                            if diffuse_input:
                                connected = diffuse_input.GetConnectedSource()
                                if connected:
                                    print(f"    diffuseColor connected to: {connected[0].GetPath()}", flush=True)
                                else:
                                    value = diffuse_input.Get()
                                    print(f"    diffuseColor value: {value}", flush=True)
                else:
                    print(f"  ✗ Mesh {prim.GetName()} has no material!", flush=True)

    if not found_materials:
        print(f"  ⚠️  WARNING: No materials found on imported object!", flush=True)


def cleanup_old_objects(stage: Usd.Stage, base_scene_path: str = None) -> None:
    """
    Remove old dynamic content from scene, keeping static elements.

    Args:
        stage: USD stage
        base_scene_path: Path to base scene sublayer (will be removed and reloaded)
    """
    print("🧹 Cleaning up old objects...")

    # Remove dynamic content, NOT the camera
    paths_to_remove = [
        "/World/Objects",
        "/World/defaultGroundPlane",
        "/World/skyDome",
        "/World/lightKey",
        "/World/lightFill",
        "/World/lightRim"
    ]

    for path in paths_to_remove:
        if stage.GetPrimAtPath(path).IsValid():
            stage.RemovePrim(path)

    # Remove base scene sublayer if present (so it can be re-added cleanly)
    if base_scene_path:
        root_layer = stage.GetRootLayer()
        if base_scene_path in root_layer.subLayerPaths:
            root_layer.subLayerPaths.remove(base_scene_path)
            print("🗑️  Removed base scene sublayer for clean reload")

    print("✅ Cleanup done")


def _create_ground_plane(stage: Usd.Stage) -> None:
    """Create textured ground plane with physics (compatible with deformables)."""
    from pxr import UsdPhysics, PhysxSchema

    # Use default GroundPlaneCfg for deformable compatibility
    # Custom physics materials can interfere with deformable-rigid collisions
    cfg_ground = sim_utils.GroundPlaneCfg(
        color=(0.35, 0.35, 0.35)
    )
    cfg_ground.visual_material = sim_utils.PreviewSurfaceCfg(
        diffuse_color=(0.35, 0.35, 0.35),
        roughness=0.9,
        metallic=0.0
    )
    cfg_ground.func("/World/defaultGroundPlane", cfg_ground)

    # Phase A: Ensure ground has proper collision setup for deformables
    ground_prim = stage.GetPrimAtPath("/World/defaultGroundPlane")
    if ground_prim.IsValid():
        print("🔧 Phase A: Configuring ground for deformable compatibility...", flush=True)

        # Ensure collision API is applied
        if not ground_prim.HasAPI(UsdPhysics.CollisionAPI):
            UsdPhysics.CollisionAPI.Apply(ground_prim)
            print("   ✓ Applied CollisionAPI to ground", flush=True)

        # Add PhysX-specific collision tuning for deformables
        if not ground_prim.HasAPI(PhysxSchema.PhysxCollisionAPI):
            physx_coll = PhysxSchema.PhysxCollisionAPI.Apply(ground_prim)
            # Contact offset: distance at which contacts are detected (1-2% of typical object size)
            physx_coll.CreateContactOffsetAttr().Set(0.01)  # 1cm contact detection distance
            # Rest offset: minimum separation distance (typically 0 for stable ground)
            physx_coll.CreateRestOffsetAttr().Set(0.0)
            print("   ✓ Applied PhysxCollisionAPI with contact/rest offsets", flush=True)

        # Create and bind physics material with proper friction
        mat_path = "/World/PhysicsMaterials/GroundMaterial"
        mat_prim = stage.GetPrimAtPath(mat_path)
        if not mat_prim.IsValid():
            mat_prim = stage.DefinePrim(mat_path, "Material")
            phys_mat = UsdPhysics.MaterialAPI.Apply(mat_prim)
            phys_mat.CreateStaticFrictionAttr().Set(0.6)
            phys_mat.CreateDynamicFrictionAttr().Set(0.5)
            phys_mat.CreateRestitutionAttr().Set(0.0)
            print("   ✓ Created ground physics material (friction=0.6/0.5, restitution=0)", flush=True)

        # Bind material to ground
        sim_utils.bind_physics_material("/World/defaultGroundPlane", mat_path, stage=stage)
        print("   ✓ Bound physics material to ground", flush=True)
        print("✅ Phase A complete: Ground ready for deformables", flush=True)


def _create_lighting(stage: Usd.Stage) -> None:
    """Create lighting setup (sky dome + 3-point lighting)."""
    # Sky dome light (reduced intensity to fix overexposure)
    cfg_dome = sim_utils.DomeLightCfg(
        intensity=500.0,  # Was 2000
        color=(0.3, 0.6, 1.0)
    )
    cfg_dome.func("/World/skyDome", cfg_dome)

    # 3-point lighting (all reduced by 75% to fix overexposure)
    cfg_key = sim_utils.DistantLightCfg(intensity=500.0, color=(1.0, 0.95, 0.85))
    cfg_key.func("/World/lightKey", cfg_key, translation=(-3, -2, 8))

    cfg_fill = sim_utils.DistantLightCfg(intensity=200.0, color=(0.9, 0.9, 1.0))
    cfg_fill.func("/World/lightFill", cfg_fill, translation=(3, -1, 5))

    cfg_rim = sim_utils.DistantLightCfg(intensity=150.0, color=(1.0, 1.0, 1.0))
    cfg_rim.func("/World/lightRim", cfg_rim, translation=(0, 5, 6))


def build_pyramid(parent: str, levels: int = 6, cube_size=0.15, gap=0.02, base_xy=(0.0, 0.0), z0=0.075):
    """
    Build a pyramid of cubes.

    Args:
        parent: Parent prim path
        levels: Number of pyramid levels
        cube_size: Size of each cube
        gap: Gap between cubes
        base_xy: (x, y) position of pyramid base
        z0: Z height of bottom level
    """
    prim_utils.create_prim(parent, "Xform")
    size = (cube_size, cube_size, cube_size)
    spacing = cube_size + gap

    cfg_cube = sim_utils.CuboidCfg(
        size=size,
        rigid_props=sim_utils.RigidBodyPropertiesCfg(),
        collision_props=sim_utils.CollisionPropertiesCfg(),
        mass_props=sim_utils.MassPropertiesCfg(mass=0.15),
        visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.25, 0.6, 0.95)),
    )

    x0, y0 = base_xy
    for lvl in range(levels):
        count = levels - lvl
        x_start = x0 - 0.5 * (count - 1) * spacing
        y = y0
        z = z0 + lvl * spacing
        for j in range(count):
            x = x_start + j * spacing
            cfg_cube.func(f"{parent}/cube_{lvl}_{j}", cfg_cube, translation=(x, y, z))


def build_wall(
    parent: str,
    width: int = 15,
    height: int = 12,
    brick_width=0.3,
    brick_height=0.15,
    brick_depth=0.15,
    gap=0.01,
    base_xy=(0.0, 10.0),
    z0=0.075
):
    """
    Build a brick wall structure.

    Args:
        parent: Parent prim path
        width: Number of bricks wide
        height: Number of bricks tall
        brick_width: Width of each brick
        brick_height: Height of each brick
        brick_depth: Depth of each brick
        gap: Gap between bricks
        base_xy: (x, y) position of wall base
        z0: Z height of bottom row
    """
    prim_utils.create_prim(parent, "Xform")

    # High-friction brick material for stability
    brick_physics_material = sim_utils.RigidBodyMaterialCfg(
        static_friction=1.2,   # Very high friction (bricks are rough)
        dynamic_friction=1.0,
        restitution=0.1        # Low bounce
    )

    cfg_brick = sim_utils.CuboidCfg(
        size=(brick_width * 0.98, brick_depth * 0.98, brick_height * 0.98),
        rigid_props=sim_utils.RigidBodyPropertiesCfg(),
        collision_props=sim_utils.CollisionPropertiesCfg(
            contact_offset=0.005,
            rest_offset=-0.001
        ),
        mass_props=sim_utils.MassPropertiesCfg(mass=2.0),  # Heavy bricks
        physics_material=brick_physics_material,
        visual_material=sim_utils.PreviewSurfaceCfg(
            diffuse_color=(0.7, 0.3, 0.2),  # Reddish-brown
            roughness=0.8
        ),
    )

    x0, y0 = base_xy
    brick_spacing_x = brick_width + gap
    brick_spacing_z = brick_height + gap

    for row in range(height):
        # Alternate brick pattern (offset every other row)
        offset = (brick_spacing_x / 2) if row % 2 == 1 else 0

        for col in range(width):
            # Skip edge bricks on top row (they're unstable)
            if row == height - 1 and (col == 0 or col == width - 1):
                continue

            x = x0 - 0.5 * (width - 1) * brick_spacing_x + col * brick_spacing_x + offset
            y = y0
            z = z0 + row * brick_spacing_z

            cfg_brick.func(f"{parent}/brick_{row}_{col}", cfg_brick, translation=(x, y, z))
