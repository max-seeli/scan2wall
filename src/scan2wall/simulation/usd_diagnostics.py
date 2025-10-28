"""
USD Diagnostics Module

Tools for inspecting and debugging USD/USDZ files.
Helps verify materials, textures, physics properties, and mesh data.
"""

from pxr import Usd, UsdGeom, UsdShade, UsdPhysics
import sys


def inspect_loaded_object(stage: Usd.Stage, object_path: str = "/World/Objects/custom_obj") -> dict:
    """
    Comprehensive inspection of a loaded USD object.

    Checks:
    - Transform/scale
    - Material bindings
    - Texture paths and resolution
    - Physics properties
    - Mesh data (vertices, faces)

    Args:
        stage: USD stage containing the object
        object_path: Path to the object prim

    Returns:
        Dictionary with inspection results
    """
    print("\n" + "="*60, flush=True)
    print("🔍 USD LOADING DIAGNOSTICS", flush=True)
    print("="*60, flush=True)

    results = {
        "object_exists": False,
        "transform": None,
        "materials": [],
        "textures": [],
        "physics": {},
        "mesh": {}
    }

    obj_prim = stage.GetPrimAtPath(object_path)
    print(f"DEBUG: Looking for prim at {object_path}", flush=True)
    print(f"DEBUG: obj_prim exists: {obj_prim is not None}", flush=True)
    print(f"DEBUG: obj_prim.IsValid(): {obj_prim.IsValid() if obj_prim else 'N/A'}", flush=True)

    if obj_prim and obj_prim.IsValid():
        results["object_exists"] = True

        # Check transform/scale
        results["transform"] = check_transform(obj_prim)

        # Check material bindings
        results["materials"] = check_materials(obj_prim, stage)

        # Find textures
        results["textures"] = check_textures(stage)

        # Check physics properties
        results["physics"] = check_physics_properties(obj_prim)

        # Check mesh data
        results["mesh"] = check_mesh_data(stage, object_path)

    else:
        print(f"❌ Object prim not found at {object_path}", flush=True)
        print(f"\n📋 Available prims under /World:", flush=True)
        world_prim = stage.GetPrimAtPath("/World")
        if world_prim and world_prim.IsValid():
            for child in world_prim.GetChildren():
                print(f"   - {child.GetPath()}", flush=True)
                if child.GetPath().pathString == "/World/Objects":
                    for subchild in child.GetChildren():
                        print(f"      → {subchild.GetPath()}", flush=True)

    print("="*60 + "\n", flush=True)
    return results


def check_transform(prim) -> dict:
    """
    Check transform matrix and extract scale.

    Args:
        prim: USD prim to inspect

    Returns:
        Dictionary with transform info
    """
    print(f"\n📏 Transform Matrix:", flush=True)

    xformable = UsdGeom.Xformable(prim)
    if not xformable:
        print(f"   ❌ Not an xformable prim", flush=True)
        return {"valid": False}

    local_transform = xformable.GetLocalTransformation()
    print(f"   {local_transform}", flush=True)

    # Extract scale from matrix
    scale_x = local_transform.GetRow(0).GetLength()
    scale_y = local_transform.GetRow(1).GetLength()
    scale_z = local_transform.GetRow(2).GetLength()
    print(f"   Extracted Scale: ({scale_x:.3f}, {scale_y:.3f}, {scale_z:.3f})", flush=True)

    return {
        "valid": True,
        "scale": (scale_x, scale_y, scale_z),
        "matrix": str(local_transform)
    }


def check_materials(prim, stage: Usd.Stage) -> list:
    """
    Check material bindings on a prim.

    Args:
        prim: USD prim to inspect
        stage: USD stage

    Returns:
        List of material paths found
    """
    print(f"\n🎨 Material Bindings:", flush=True)

    materials_found = []
    material_binding_api = UsdShade.MaterialBindingAPI(prim)

    # Check all-purpose binding
    all_purpose_binding = material_binding_api.GetDirectBinding()
    if all_purpose_binding.GetMaterial():
        mat = all_purpose_binding.GetMaterial()
        mat_path = str(mat.GetPath())
        materials_found.append(mat_path)
        print(f"   All-purpose: {mat_path}", flush=True)
    else:
        print(f"   All-purpose: NONE ❌", flush=True)

    # Check computed bound material
    computed_binding = material_binding_api.ComputeBoundMaterial()
    if computed_binding[0]:
        mat = computed_binding[0]
        mat_path = str(mat.GetPath())
        if mat_path not in materials_found:
            materials_found.append(mat_path)
        print(f"   Computed bound material: {mat_path}", flush=True)
    else:
        print(f"   Computed bound material: NONE", flush=True)

    return materials_found


def check_textures(stage: Usd.Stage) -> list:
    """
    Find all textures in the scene.

    Args:
        stage: USD stage

    Returns:
        List of dictionaries with texture info
    """
    print(f"\n🖼️  Textures Found:", flush=True)

    textures_found = []
    texture_count = 0

    for prim in stage.Traverse():
        if prim.IsA(UsdShade.Shader):
            shader = UsdShade.Shader(prim)
            # Check for texture inputs
            for input_name in ['file', 'texture', 'diffuseTexture', 'baseColorTexture']:
                texture_input = shader.GetInput(input_name)
                if texture_input:
                    asset_path = texture_input.Get()
                    if asset_path:
                        texture_count += 1
                        path_str = str(asset_path)
                        textures_found.append({
                            "index": texture_count,
                            "input_name": input_name,
                            "path": path_str,
                            "shader": str(prim.GetPath())
                        })
                        print(f"   [{texture_count}] {input_name}: {asset_path}", flush=True)

    if texture_count == 0:
        print(f"   ❌ NO TEXTURES FOUND IN USD!", flush=True)

    return textures_found


def check_physics_properties(prim) -> dict:
    """
    Check physics properties on a prim.

    Args:
        prim: USD prim to inspect

    Returns:
        Dictionary with physics info
    """
    print(f"\n⚙️  Physics Properties:", flush=True)

    physics_info = {"has_rigid_body": False}

    if prim.HasAPI(UsdPhysics.RigidBodyAPI):
        rigid_body = UsdPhysics.RigidBodyAPI(prim)
        physics_info["has_rigid_body"] = True
        print(f"   Has RigidBodyAPI: ✅", flush=True)
    else:
        print(f"   Has RigidBodyAPI: ❌", flush=True)

    return physics_info


def check_mesh_data(stage: Usd.Stage, object_path: str) -> dict:
    """
    Check mesh geometry data.

    Args:
        stage: USD stage
        object_path: Path to object prim

    Returns:
        Dictionary with mesh info
    """
    print(f"\n📦 Mesh Properties:", flush=True)

    mesh_info = {"found": False}
    found_mesh = False

    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh) and str(prim.GetPath()).startswith(object_path):
            mesh = UsdGeom.Mesh(prim)
            points = mesh.GetPointsAttr().Get()
            face_counts = mesh.GetFaceVertexCountsAttr().Get()

            if points and face_counts:
                num_verts = len(points)
                num_faces = len(face_counts)
                mesh_path = str(prim.GetPath())

                mesh_info = {
                    "found": True,
                    "path": mesh_path,
                    "vertices": num_verts,
                    "faces": num_faces
                }

                print(f"   Mesh: {mesh_path}", flush=True)
                print(f"   Vertices: {num_verts}", flush=True)
                print(f"   Faces: {num_faces}", flush=True)
                found_mesh = True
                break

    if not found_mesh:
        print(f"   ❌ No mesh found under {object_path}", flush=True)

    return mesh_info


def verify_texture_resolution(stage: Usd.Stage, verbose: bool = True) -> dict:
    """
    Verify that all texture paths resolve correctly.

    Useful for debugging USDZ archive texture loading.

    Args:
        stage: USD stage
        verbose: If True, print detailed output

    Returns:
        Dictionary with resolution stats
    """
    if verbose:
        print(f"\n🔍 Texture Resolution Check:", flush=True)

    resolved_count = 0
    unresolved_count = 0
    texture_paths = []

    for prim in stage.Traverse():
        if prim.IsA(UsdShade.Shader):
            shader = UsdShade.Shader(prim)

            for input_name in ['file', 'texture']:
                texture_input = shader.GetInput(input_name)
                if not texture_input:
                    continue

                asset_path = texture_input.Get()
                if not asset_path:
                    continue

                path_str = str(asset_path.path) if hasattr(asset_path, 'path') else str(asset_path)

                # Try to resolve
                resolved = asset_path.GetResolvedPath() if hasattr(asset_path, 'GetResolvedPath') else None

                if resolved:
                    resolved_count += 1
                    if verbose:
                        print(f"   ✅ {path_str} → {resolved}", flush=True)
                else:
                    unresolved_count += 1
                    if verbose:
                        print(f"   ❌ {path_str} → UNRESOLVED", flush=True)

                texture_paths.append({
                    "path": path_str,
                    "resolved": resolved,
                    "shader": str(prim.GetPath())
                })

    if verbose:
        print(f"\n   Summary: {resolved_count} resolved, {unresolved_count} unresolved", flush=True)

    return {
        "resolved_count": resolved_count,
        "unresolved_count": unresolved_count,
        "textures": texture_paths
    }
