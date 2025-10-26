"""Check dimensions of GLB or USD files."""

import click
from pathlib import Path
import sys


@click.command()
@click.argument('file_path', type=click.Path(exists=True))
def check_size(file_path):
    """Check dimensions of a GLB or USD file.

    Args:
        file_path: Path to GLB or USD file

    Example:
        scan2wall check-size data/test/usd/basketball.usd
        scan2wall check-size data/test/texturedmeshes/basketball.glb
    """
    file_path = Path(file_path)

    if not file_path.exists():
        click.echo(f"❌ Error: File not found: {file_path}")
        sys.exit(1)

    suffix = file_path.suffix.lower()

    if suffix == '.usd' or suffix == '.usdz':
        _check_usd_size(file_path)
    elif suffix == '.glb':
        _check_glb_size(file_path)
    else:
        click.echo(f"❌ Error: Unsupported file type '{suffix}'")
        click.echo("   Supported types: .usd, .usdz, .glb")
        sys.exit(1)


def _check_usd_size(file_path: Path):
    """Check USD file dimensions and physics properties using usd-core library."""
    try:
        from pxr import Usd, UsdGeom, UsdPhysics
    except ImportError:
        click.echo("❌ Error: usd-core library not available.")
        click.echo("   Install with: uv pip install usd-core")
        sys.exit(1)

    try:
        stage = Usd.Stage.Open(str(file_path))
        bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ['default'])
        root_prim = stage.GetDefaultPrim()

        if not root_prim:
            click.echo(f"❌ Error: USD file has no default prim")
            sys.exit(1)

        # Get bounding box
        bbox = bbox_cache.ComputeWorldBound(root_prim)
        bbox_range = bbox.ComputeAlignedBox()
        bbox_size = bbox_range.GetSize()

        x = float(bbox_size[0])
        y = float(bbox_size[1])
        z = float(bbox_size[2])
        max_dim = max(x, y, z)

        click.echo(f"\n📏 USD File: {file_path.name}")
        click.echo(f"   Path: {file_path}")
        click.echo()

        click.echo(f"📐 Dimensions:")
        click.echo(f"   X-axis: {x:.4f}m")
        click.echo(f"   Y-axis: {y:.4f}m")
        click.echo(f"   Z-axis: {z:.4f}m")
        click.echo(f"   Max:    {max_dim:.4f}m")
        click.echo()

        # Get physics properties
        physics_info = []
        for prim in stage.Traverse():
            # Check for rigid body
            if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                rigid_body = UsdPhysics.RigidBodyAPI(prim)
                physics_info.append("✓ Has RigidBodyAPI")

                # Get mass
                if prim.HasAPI(UsdPhysics.MassAPI):
                    mass_api = UsdPhysics.MassAPI(prim)
                    mass_attr = mass_api.GetMassAttr()
                    if mass_attr:
                        mass = mass_attr.Get()
                        if mass:
                            physics_info.append(f"   Mass: {mass:.2f}kg")

            # Check for physics material
            if prim.HasAPI(UsdPhysics.MaterialAPI):
                mat_api = UsdPhysics.MaterialAPI(prim)

                sf_attr = mat_api.GetStaticFrictionAttr()
                df_attr = mat_api.GetDynamicFrictionAttr()
                rest_attr = mat_api.GetRestitutionAttr()

                if sf_attr:
                    sf = sf_attr.Get()
                    if sf is not None:
                        physics_info.append(f"   Static friction: {sf:.2f}")

                if df_attr:
                    df = df_attr.Get()
                    if df is not None:
                        physics_info.append(f"   Dynamic friction: {df:.2f}")

                if rest_attr:
                    rest = rest_attr.Get()
                    if rest is not None:
                        physics_info.append(f"   Restitution: {rest:.2f}")

        if physics_info:
            click.echo("⚙️  Physics Properties:")
            for info in physics_info:
                click.echo(f"   {info}")
            click.echo()
        else:
            click.echo("⚙️  Physics Properties: None found")
            click.echo()

        # Display custom metadata (object type and scene description)
        if root_prim:
            object_type = root_prim.GetCustomDataByKey("scan2wall:object_type")
            scene_description = root_prim.GetCustomDataByKey("scan2wall:scene_description")

            if object_type or scene_description:
                click.echo("🏷️  Metadata:")
                if object_type:
                    click.echo(f"   Object type: {object_type}")
                if scene_description:
                    click.echo(f"   Scene: {scene_description}")
                click.echo()

        # Display texture information
        from pxr import UsdShade
        import os
        textures_found = []

        # Look for all shader prims that have a "texture" input
        # (Isaac Lab's GLB converter creates separate texture sampler shaders)
        for prim in stage.Traverse():
            if prim.IsA(UsdShade.Shader):
                shader = UsdShade.Shader(prim)

                # Check for common texture input names
                texture_input = shader.GetInput("texture")  # Most common
                if not texture_input:
                    texture_input = shader.GetInput("file")  # Alternative name

                if texture_input:
                    asset_path = texture_input.Get()
                    if asset_path:
                        # Get shader name to determine texture type
                        shader_name = prim.GetName().lower()
                        filename = os.path.basename(str(asset_path.path) if hasattr(asset_path, 'path') else str(asset_path))

                        # Try to determine texture type from shader name
                        if 'basecolor' in shader_name or 'diffuse' in shader_name or 'albedo' in shader_name:
                            texture_type = "Base Color/Albedo"
                        elif 'metallic' in shader_name and 'roughness' in shader_name:
                            texture_type = "Metallic-Roughness"
                        elif 'metallic' in shader_name:
                            texture_type = "Metallic"
                        elif 'roughness' in shader_name:
                            texture_type = "Roughness"
                        elif 'normal' in shader_name:
                            texture_type = "Normal"
                        elif 'emissive' in shader_name:
                            texture_type = "Emissive"
                        elif 'opacity' in shader_name or 'alpha' in shader_name:
                            texture_type = "Opacity"
                        elif 'occlusion' in shader_name or 'ao' in shader_name:
                            texture_type = "Occlusion"
                        else:
                            texture_type = "Texture"

                        textures_found.append(f"{texture_type}: {filename}")

        if textures_found:
            click.echo("🎨 Textures:")
            for texture in textures_found:
                click.echo(f"   {texture}")
            click.echo()
        else:
            click.echo("🎨 Textures: None found")
            click.echo()

    except Exception as e:
        click.echo(f"❌ Error reading USD file: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def _check_glb_size(file_path: Path):
    """Check GLB file dimensions using trimesh."""
    try:
        import trimesh
    except ImportError:
        click.echo("❌ Error: trimesh library not available.")
        click.echo("   Install with: pip install trimesh")
        sys.exit(1)

    try:
        mesh = trimesh.load(str(file_path))

        # Get bounding box
        bounds = mesh.bounds  # [[min_x, min_y, min_z], [max_x, max_y, max_z]]
        extents = mesh.extents  # [x_size, y_size, z_size]

        x = float(extents[0])
        y = float(extents[1])
        z = float(extents[2])
        max_dim = max(x, y, z)

        click.echo(f"\n📏 GLB Dimensions: {file_path.name}")
        click.echo(f"   X-axis: {x:.4f} units")
        click.echo(f"   Y-axis: {y:.4f} units")
        click.echo(f"   Z-axis: {z:.4f} units")
        click.echo(f"   Max:    {max_dim:.4f} units")
        click.echo()
        click.echo("   Note: GLB dimensions are in model units (not meters).")
        click.echo("   Convert to USD to get real-world scale.")
        click.echo()

    except Exception as e:
        click.echo(f"❌ Error reading GLB file: {e}")
        sys.exit(1)
