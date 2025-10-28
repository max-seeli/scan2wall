#!/usr/bin/env python3
"""Inspect USDZ file to debug texture loading issues."""
import sys
from pxr import Usd, UsdShade, Sdf

if len(sys.argv) < 2:
    print("Usage: python inspect_usdz.py <path_to_usdz>")
    sys.exit(1)

usdz_path = sys.argv[1]
stage = Usd.Stage.Open(usdz_path)

print(f"\n📦 Inspecting: {usdz_path}")
print(f"✓ Stage loaded successfully\n")

# Find all materials
materials = []
for prim in stage.Traverse():
    if prim.GetTypeName() == 'Material':
        materials.append(prim)

print(f"Found {len(materials)} material(s):\n")

for mat_prim in materials:
    print(f"Material: {mat_prim.GetPath()}")
    material = UsdShade.Material(mat_prim)

    # Find shaders
    for child in mat_prim.GetChildren():
        if child.IsA(UsdShade.Shader):
            shader = UsdShade.Shader(child)
            shader_id = shader.GetIdAttr().Get()
            print(f"  Shader: {child.GetName()} (type: {shader_id})")

            # Print all inputs
            for input in shader.GetInputs():
                value = input.Get()
                print(f"    Input: {input.GetBaseName()} = {value}")
    print()

# Find mesh prims and their material bindings
print("\nMesh material bindings:")
for prim in stage.Traverse():
    if prim.GetTypeName() in ['Mesh', 'Xform']:
        binding_api = UsdShade.MaterialBindingAPI(prim)
        if binding_api:
            mat_binding = binding_api.GetDirectBinding()
            if mat_binding:
                bound_mat = mat_binding.GetMaterial()
                if bound_mat:
                    print(f"  {prim.GetPath()} → {bound_mat.GetPath()}")
