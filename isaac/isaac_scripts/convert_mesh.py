# Copyright (c) 2022-2025, The Isaac Lab Project Developers
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""
Utility to convert an OBJ/STL/FBX into USD format, with optional mass/inertia
edits and physics material (friction/restitution) binding.

python isaaclab/scripts/tools/convert_mesh.py \
      /workspace/isaaclab/sample.glb /workspace/isaaclab/sample.usd \
        --collision-approximation convexHull --mass 0.35 --com 0 0 0 \
        --inertia 0.00195 0.00195 0.000246 --principal-axes 1 0 0 0 \
        --static-friction 0.6 --dynamic-friction 0.5 --restitution 0.2 \
        --friction-combine average --restitution-combine min
"""

import argparse

from isaaclab.app import AppLauncher

# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Utility to convert a mesh file into USD format.")
parser.add_argument("input", type=str, help="The path to the input mesh file.")
parser.add_argument("output", type=str, help="The path to store the USD file.")
parser.add_argument(
    "--make-instanceable",
    action="store_true",
    default=False,
    help="Make the asset instanceable for efficient cloning.",
)
parser.add_argument(
    "--collision-approximation",
    type=str,
    default="convexDecomposition",
    choices=["convexDecomposition", "convexHull", "boundingCube", "boundingSphere", "meshSimplification", "none"],
    help=('The method used for approximating collision mesh. Set to "none" to not add a collision mesh.'),
)
parser.add_argument(
    "--mass",
    type=float,
    default=None,
    help="Mass in kg to assign to the asset. If not provided, no mass is added.",
)
parser.add_argument(
    "--density",
    type=float,
    default=None,
    help="Density in kg/m³ to assign to the asset. If not provided, no density is added.",
)

# --- Center of mass and inertia controls ---
parser.add_argument(
    "--com",
    type=float,
    nargs=3,
    metavar=("X", "Y", "Z"),
    default=None,
    help="Center of mass in meters (X Y Z). Example: --com 0 0 0",
)
parser.add_argument(
    "--inertia",
    type=float,
    nargs=3,
    metavar=("IXX", "IYY", "IZZ"),
    default=None,
    help="Principal moments of inertia in kg·m² (Ixx Iyy Izz). Example: --inertia 0.01 0.02 0.03",
)
parser.add_argument(
    "--principal-axes",
    type=float,
    nargs=4,
    metavar=("QW", "QX", "QY", "QZ"),
    default=None,
    help="Quaternion (qw qx qy qz) for principal axes orientation. Example: --principal-axes 1 0 0 0",
)

# --- Physics material (friction/restitution) controls ---
parser.add_argument("--static-friction", type=float, default=None, help="Static friction coefficient (unitless).")
parser.add_argument("--dynamic-friction", type=float, default=None, help="Dynamic friction coefficient (unitless).")
parser.add_argument("--restitution", type=float, default=None, help="Coefficient of restitution (bounciness).")
parser.add_argument(
    "--friction-combine",
    type=str,
    choices=["average", "min", "multiply", "max"],
    default=None,
    help="(Optional, PhysX) Friction combine mode.",
)
parser.add_argument(
    "--restitution-combine",
    type=str,
    choices=["average", "min", "multiply", "max"],
    default=None,
    help="(Optional, PhysX) Restitution combine mode.",
)

# Append AppLauncher args and parse
AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()

# Launch Omniverse app
app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

# -----------------------------------------------------------------------------
# Imports that require app context
# -----------------------------------------------------------------------------
import contextlib
import os

import carb
import isaacsim.core.utils.stage as stage_utils
import omni.kit.app

from isaaclab.sim.converters import MeshConverter, MeshConverterCfg
from isaaclab.sim.schemas import schemas_cfg
from isaaclab.utils.assets import check_file_path
from isaaclab.utils.dict import print_dict

# USD imports
from pxr import Usd, UsdPhysics, Gf, UsdShade
try:
    # Only present in Isaac/Omniverse distributions that ship PhysX schema
    from pxr import PhysxSchema
except Exception:
    PhysxSchema = None


def _any_material_args_provided():
    return any(
        v is not None
        for v in (
            args_cli.static_friction,
            args_cli.dynamic_friction,
            args_cli.restitution,
            args_cli.friction_combine,
            args_cli.restitution_combine,
        )
    )


def _bind_physics_material_robust(prim: Usd.Prim, mat: UsdShade.Material):
    """Bind material with physics purpose, with fallback if UsdShade.Tokens.physics is missing."""
    bind_api = UsdShade.MaterialBindingAPI(prim)
    if hasattr(UsdShade.Tokens, "physics"):
        bind_api.Bind(mat, UsdShade.Tokens.physics)
        print(f"Bound physics material using UsdShade.Tokens.physics to {prim.GetPath()}.")
    else:
        # Older USD: create "physics:material:binding" relationship manually
        rel = prim.CreateRelationship("physics:material:binding", False)
        rel.SetTargets([mat.GetPath()])
        print(f"Bound physics material via 'physics:material:binding' relationship to {prim.GetPath()}.")


def main():
    # Validate mesh path
    mesh_path = args_cli.input if os.path.isabs(args_cli.input) else os.path.abspath(args_cli.input)
    if not check_file_path(mesh_path):
        raise ValueError(f"Invalid mesh file path: {mesh_path}")

    # Destination path
    dest_path = args_cli.output if os.path.isabs(args_cli.output) else os.path.abspath(args_cli.output)

    # Mass / rigid props
    if (args_cli.mass is not None) or (args_cli.density is not None):
        mass_props = schemas_cfg.MassPropertiesCfg(mass=args_cli.mass, density=args_cli.density)
        rigid_props = schemas_cfg.RigidBodyPropertiesCfg()
    else:
        mass_props = None
        rigid_props = None

    # Collision props
    collision_props = schemas_cfg.CollisionPropertiesCfg(
        collision_enabled=args_cli.collision_approximation != "none"
    )

    # Converter config
    mesh_converter_cfg = MeshConverterCfg(
        mass_props=mass_props,
        rigid_props=rigid_props,
        collision_props=collision_props,
        asset_path=mesh_path,
        force_usd_conversion=True,
        usd_dir=os.path.dirname(dest_path),
        usd_file_name=os.path.basename(dest_path),
        make_instanceable=args_cli.make_instanceable,
        collision_approximation=args_cli.collision_approximation,
    )

    # Info
    print("-" * 80)
    print(f"Input Mesh file: {mesh_path}")
    print("Mesh importer config:")
    print_dict(mesh_converter_cfg.to_dict(), nesting=0)
    print("-" * 80)

    # Convert
    mesh_converter = MeshConverter(mesh_converter_cfg)
    print(f"Generated USD file: {mesh_converter.usd_path}")
    print("-" * 80)

    # Post-conversion USD edits
    need_mass_edit = (args_cli.com is not None) or (args_cli.inertia is not None) or (args_cli.principal_axes is not None)
    need_material = _any_material_args_provided()

    if need_mass_edit or need_material:
        stage = Usd.Stage.Open(mesh_converter.usd_path)
        if stage is None:
            raise RuntimeError(f"Failed to open generated USD: {mesh_converter.usd_path}")
        prim = stage.GetDefaultPrim()
        if not prim:
            raise RuntimeError("USD has no default prim; cannot apply properties.")

        # MassAPI edits
        if need_mass_edit:
            mass_api = UsdPhysics.MassAPI.Apply(prim)
            if args_cli.com is not None:
                x, y, z = args_cli.com
                mass_api.CreateCenterOfMassAttr().Set(Gf.Vec3f(float(x), float(y), float(z)))
                print(f"Set centerOfMass to: ({x}, {y}, {z})")
            if args_cli.inertia is not None:
                ixx, iyy, izz = args_cli.inertia
                mass_api.CreateDiagonalInertiaAttr().Set(Gf.Vec3f(float(ixx), float(iyy), float(izz)))
                print(f"Set diagonalInertia to: ({ixx}, {iyy}, {izz})")
            if args_cli.principal_axes is not None:
                qw, qx, qy, qz = args_cli.principal_axes
                mass_api.CreatePrincipalAxesAttr().Set(Gf.Quatf(float(qw), float(qx), float(qy), float(qz)))
                print(f"Set principalAxes (quat) to: ({qw}, {qx}, {qy}, {qz})")
            print("USD mass properties updated (MassAPI).")

        # Physics material
        if need_material:
            mat_path = prim.GetPath().AppendChild("PhysicsMaterial")
            mat = UsdShade.Material.Define(stage, mat_path)

            mat_api = UsdPhysics.MaterialAPI.Apply(mat.GetPrim())
            if args_cli.static_friction is not None:
                mat_api.CreateStaticFrictionAttr().Set(float(args_cli.static_friction))
                print(f"Set staticFriction: {args_cli.static_friction}")
            if args_cli.dynamic_friction is not None:
                mat_api.CreateDynamicFrictionAttr().Set(float(args_cli.dynamic_friction))
                print(f"Set dynamicFriction: {args_cli.dynamic_friction}")
            if args_cli.restitution is not None:
                mat_api.CreateRestitutionAttr().Set(float(args_cli.restitution))
                print(f"Set restitution: {args_cli.restitution}")

            if PhysxSchema is not None:
                physx_api = PhysxSchema.PhysxMaterialAPI.Apply(mat.GetPrim())
                if args_cli.friction_combine is not None:
                    physx_api.CreateFrictionCombineModeAttr().Set(args_cli.friction_combine)
                    print(f"Set PhysX frictionCombineMode: {args_cli.friction_combine}")
                if args_cli.restitution_combine is not None:
                    physx_api.CreateRestitutionCombineModeAttr().Set(args_cli.restitution_combine)
                    print(f"Set PhysX restitutionCombineMode: {args_cli.restitution_combine}")
            else:
                if (args_cli.friction_combine is not None) or (args_cli.restitution_combine is not None):
                    print("Warning: PhysxSchema not available; combine modes ignored.")

            _bind_physics_material_robust(prim, mat)

            if args_cli.collision_approximation == "none":
                print("Note: collision_approximation='none' — no collider present; "
                      "physics material will take effect only if a collider is added later.")

        # Save once
        stage.Save()
        print("USD edits saved.")
        print("-" * 80)


if __name__ == "__main__":
    main()
    simulation_app.close()
