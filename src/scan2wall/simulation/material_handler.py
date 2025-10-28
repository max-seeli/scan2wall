"""
Material Conversion Module

Handles converting GLTF materials to UsdPreviewSurface for Isaac Sim compatibility.
"""

from pxr import Usd, UsdShade, Sdf


def convert_gltf_materials_to_preview_surface(usd_file: str) -> int:
    """
    Convert GLTF materials to UsdPreviewSurface shaders.

    Isaac Sim works best with UsdPreviewSurface, but GLB files contain
    GLTF materials. This function converts them.

    Args:
        usd_file: Path to USD file containing GLTF materials

    Returns:
        Number of materials converted
    """
    print(f"🎨 Converting GLTF materials to UsdPreviewSurface...")

    stage = Usd.Stage.Open(usd_file)
    material_count = 0

    for prim in stage.Traverse():
        # Find GLTF materials
        if prim.GetTypeName() == 'Material':
            material = UsdShade.Material(prim)
            material_path = prim.GetPath()
            print(f"  Found material: {material_path}", flush=True)

            # Look for GLTF shader nodes under this material
            gltf_shader = None
            base_color_texture = None
            metallic_roughness_texture = None

            # DEBUG: List all children
            children = list(prim.GetChildren())
            print(f"    Material has {len(children)} children:", flush=True)
            for child in children:
                print(f"      - {child.GetName()} (type: {child.GetTypeName()})", flush=True)

            for child in children:
                child_name = child.GetName()

                # Check if it's a shader
                if child.IsA(UsdShade.Shader):
                    shader = UsdShade.Shader(child)
                    print(f"      Shader {child_name}: checking inputs...", flush=True)

                    # Check for 'file' or 'texture' inputs
                    for inp_name in ['file', 'texture', 'inputs:file']:
                        file_input = shader.GetInput(inp_name)
                        if file_input and file_input.Get():
                            tex_path = file_input.Get()
                            print(f"        Found texture at {inp_name}: {tex_path}", flush=True)
                            if not base_color_texture and ('baseColor' in child_name or 'diffuse' in child_name.lower()):
                                base_color_texture = tex_path
                            elif not metallic_roughness_texture and ('metallic' in child_name.lower() or 'roughness' in child_name.lower()):
                                metallic_roughness_texture = tex_path

                if 'PBR' in child_name or 'gltf' in child_name.lower():
                    gltf_shader = UsdShade.Shader(child)
                elif 'baseColor' in child_name:
                    tex_shader = UsdShade.Shader(child)
                    file_input = tex_shader.GetInput('file')
                    if file_input:
                        base_color_texture = file_input.Get()
                elif 'metallicRoughness' in child_name or 'MetallicRoughness' in child_name:
                    tex_shader = UsdShade.Shader(child)
                    file_input = tex_shader.GetInput('file')
                    if file_input:
                        metallic_roughness_texture = file_input.Get()

            print(f"    Found textures - base_color: {base_color_texture}, metallic: {metallic_roughness_texture}", flush=True)

            if gltf_shader or base_color_texture:
                material_count += 1
                print(f"  Converting material: {material_path}")

                # Clear existing shader connections
                for child in list(prim.GetChildren()):
                    stage.RemovePrim(child.GetPath())

                # Create UsdPreviewSurface shader
                _create_preview_surface_shader(
                    stage,
                    material,
                    material_path,
                    base_color_texture,
                    metallic_roughness_texture
                )

    if material_count > 0:
        print(f"✓ Converted {material_count} GLTF material(s) to UsdPreviewSurface")
    else:
        print(f"  No GLTF materials found (might already be UsdPreviewSurface)")

    stage.Save()
    return material_count


def _create_preview_surface_shader(
    stage: Usd.Stage,
    material: UsdShade.Material,
    material_path,
    base_color_texture,
    metallic_roughness_texture=None
) -> None:
    """
    Create a UsdPreviewSurface shader for a material.

    Args:
        stage: USD stage
        material: UsdShade.Material to attach shader to
        material_path: Path to the material prim
        base_color_texture: Asset path to base color texture (or None)
        metallic_roughness_texture: Asset path to metallic/roughness texture (or None)
    """
    shader_path = material_path.AppendChild("PreviewSurface")
    shader = UsdShade.Shader.Define(stage, shader_path)
    shader.CreateIdAttr("UsdPreviewSurface")

    # Connect shader to material outputs
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")

    # If we have a base color texture, create texture reader
    if base_color_texture:
        _setup_texture_reader(
            stage,
            shader,
            shader_path,
            base_color_texture,
            metallic_roughness_texture
        )
    else:
        # No texture, use default values
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set((0.8, 0.8, 0.8))
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.5)
        shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)


def _setup_texture_reader(
    stage: Usd.Stage,
    shader: UsdShade.Shader,
    shader_path,
    texture_asset_path,
    metallic_roughness_texture=None
) -> None:
    """
    Create texture reader nodes and connect to shader.

    Sets up the chain: UV reader → Texture sampler → Shader inputs

    Args:
        stage: USD stage
        shader: UsdPreviewSurface shader to connect to
        shader_path: Path to shader prim
        texture_asset_path: Path to base color texture file
        metallic_roughness_texture: Path to metallic/roughness texture (or None)
    """
    # Add UV reader (shared by all textures)
    uv_path = shader_path.GetParentPath().AppendChild("Primvar_st")
    uv_shader = UsdShade.Shader.Define(stage, uv_path)
    uv_shader.CreateIdAttr("UsdPrimvarReader_float2")
    uv_shader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")

    # Create base color texture reader
    tex_path = shader_path.GetParentPath().AppendChild("BaseColorTexture")
    tex_shader = UsdShade.Shader.Define(stage, tex_path)
    tex_shader.CreateIdAttr("UsdUVTexture")
    tex_shader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(texture_asset_path)
    tex_shader.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set("sRGB")
    tex_shader.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(
        uv_shader.ConnectableAPI(), "result"
    )

    # Connect texture to shader diffuseColor
    diffuse_input = shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f)
    diffuse_input.ConnectToSource(tex_shader.ConnectableAPI(), "rgb")

    # If metallic/roughness texture exists, connect it
    if metallic_roughness_texture:
        # Create metallic/roughness texture reader
        mr_tex_path = shader_path.GetParentPath().AppendChild("MetallicRoughnessTexture")
        mr_tex_shader = UsdShade.Shader.Define(stage, mr_tex_path)
        mr_tex_shader.CreateIdAttr("UsdUVTexture")
        mr_tex_shader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(metallic_roughness_texture)
        mr_tex_shader.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set("raw")  # Linear data
        mr_tex_shader.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(
            uv_shader.ConnectableAPI(), "result"
        )

        # Connect metallic (blue channel) and roughness (green channel)
        metallic_input = shader.CreateInput("metallic", Sdf.ValueTypeNames.Float)
        metallic_input.ConnectToSource(mr_tex_shader.ConnectableAPI(), "b")  # Blue channel

        roughness_input = shader.CreateInput("roughness", Sdf.ValueTypeNames.Float)
        roughness_input.ConnectToSource(mr_tex_shader.ConnectableAPI(), "g")  # Green channel
    else:
        # No metallic/roughness texture, use default values
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.5)
        shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
