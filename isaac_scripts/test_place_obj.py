"""
./isaaclab/isaaclab.sh -p isaaclab/scripts/test_place_obj.py --kit_args="--no-window --enable omni.kit.livestream.webrtc --/app/livestream/publicEndpointAddress=35.153.104.189 --/app/livestream/port=49100"
"""

"""Launch Isaac Sim Simulator first."""


import argparse

from isaaclab.app import AppLauncher

# create argparser
parser = argparse.ArgumentParser(
    description="Tutorial on spawning prims into the scene."
)
# append AppLauncher cli args
AppLauncher.add_app_launcher_args(parser)
# parse the arguments
args_cli = parser.parse_args()
# launch omniverse app
app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

"""Rest everything follows."""
import omni.timeline
import isaacsim.core.utils.prims as prim_utils

import isaaclab.sim as sim_utils
from omni.physx.scripts import utils

from pxr import UsdPhysics, Gf
import omni.usd
import numpy as np

def build_pyramid(parent: str, levels: int = 6, cube_size: float = 0.15, gap: float = 0.02, base_xy=(0.0, 0.0), z0: float = 0.075):
    prim_utils.create_prim(parent, "Xform")
    size = (cube_size, cube_size, cube_size)
    spacing = cube_size + gap
    cfg_cube = sim_utils.CuboidCfg(
        size=size,
        # deformable_props=sim_utils.DeformableBodyPropertiesCfg(),  # FEM default
        rigid_props=sim_utils.RigidBodyPropertiesCfg(),
        # physics_material=sim_utils.DeformableBodyMaterialCfg(),
        collision_props=sim_utils.CollisionPropertiesCfg(),
        mass_props=sim_utils.MassPropertiesCfg(mass=0.15),
        visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.25, 0.6, 0.95)),
    )
    x0, y0 = base_xy
    for lvl in range(levels):
        count = levels - lvl
        # center the row
        x_start = x0 - 0.5 * (count - 1) * spacing
        y = y0
        z = z0 + lvl * spacing
        for j in range(count):
            x = x_start + j * spacing
            name = f"{parent}/cube_{lvl}_{j}"
            cfg_cube.func(name, cfg_cube, translation=(x, y, z))

def throw_object(prim_path: str, direction=(1.0, 0.0, 0.5), speed=8.0):
    """Set an initial linear velocity for a rigid body."""
    # normalize direction
    d = np.array(direction, dtype=float)
    n = d / (np.linalg.norm(d) + 1e-8)
    v = n * float(speed)

    stage = omni.usd.get_context().get_stage()
    prim = stage.GetPrimAtPath(prim_path)

    # Make sure the prim is a rigid body
    rb = UsdPhysics.RigidBodyAPI(prim)
    rb.CreateRigidBodyEnabledAttr(True)

    # Set initial velocity (units: distance/time in your stage units)
    rb.GetVelocityAttr().Set(Gf.Vec3f(float(v[0]), float(v[1]), float(v[2])))

def design_scene():
    """Designs the scene by spawning ground plane, light, objects and meshes from usd files."""
    # Ground-plane
    cfg_ground = sim_utils.GroundPlaneCfg()
    cfg_ground.func("/World/defaultGroundPlane", cfg_ground)

    # spawn distant light
    cfg_light_distant = sim_utils.DistantLightCfg(
        intensity=5000.0,
        color=(0.75, 0.75, 0.75),
    )
    cfg_light_distant.func(
        "/World/lightDistant", cfg_light_distant, translation=(1, 0, 10)
    )

    custom_obj_cfg = sim_utils.UsdFileCfg(
        usd_path="/workspace/isaaclab/sample.usd",
        scale=(1.0, 1.0, 1.0),
        collision_props=sim_utils.CollisionPropertiesCfg(),
    )

    custom_obj_cfg.func(
        "/World/Objects/custom_obj",
        custom_obj_cfg,
        translation=(0.0, 0.0, 2.0),
        orientation=(0.4207, 0.5609, 0.5609, 0.4370),
        clone_in_fabric=True,
    )

def main():
    """Main function."""

    # Initialize the simulation context
    sim_cfg = sim_utils.SimulationCfg(dt=0.01, device=args_cli.device)
    sim = sim_utils.SimulationContext(sim_cfg)
    # Set main camera
    sim.set_camera_view([0.0, -8.0, 5.0], [0.0, 0.0, 3.0])
    design_scene()

    build_pyramid("/World/Objects/Pyramid", levels=20, cube_size=0.15, gap=0.00, base_xy=(0.0, 10.0), z0=0.075)

    throw_object("/World/Objects/custom_obj", direction=(0.0, 1.0, 0.1), speed=17.0)

    # Play the simulator
    sim.reset()
    # Now we are ready!
    print("[INFO]: Setup complete...")
    # Simulate physics
    i = 0
    while simulation_app.is_running():
        # perform step
        sim.step()
        i = i + 1
        if (i >= 400):
            sim.reset()
            i = 0

if __name__ == "__main__":
    # run the main function
    main()
    # close sim app
    simulation_app.close()