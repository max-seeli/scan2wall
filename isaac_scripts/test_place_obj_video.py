# SPDX-License-Identifier: BSD-3-Clause
# Spawn scene and (optionally) record a single iteration to MP4 using viewport capture (no Replicator).

import argparse
import os
import shutil
import subprocess
import glob
import time

from isaaclab.app import AppLauncher

# ---------------------------
# CLI (match skrl-style flags)
# ---------------------------
parser = argparse.ArgumentParser(description="Spawn prims and (optionally) record one iteration to video.")
parser.add_argument("--video", action="store_true", default=False, help="Record video.")
parser.add_argument("--video_length", type=int, default=200, help="Length of the recorded video (in steps).")
parser.add_argument("--real-time", action="store_true", default=False, help="Run in real-time, if possible.")

# Performance / quality knobs
parser.add_argument("--out_dir", type=str, default="recordings", help="Output folder for video/frames.")
parser.add_argument("--video_name", type=str, default="sim_run.mp4", help="Output mp4 filename.")
parser.add_argument("--fps", type=int, default=50, help="Playback FPS for the video.")
parser.add_argument("--width", type=int, default=1920, help="Capture width.")
parser.add_argument("--height", type=int, default=1080, help="Capture height.")
parser.add_argument("--every_n", type=int, default=1, help="Save every Nth frame.")
parser.add_argument("--jpg", action="store_true", help="Write JPG instead of PNG (faster/smaller).")

parser.add_argument("--usd_path_abs", type=str, help="Absolute path to USD file to be inserted.")

# NEW: how many captured frames to skip at the start of the video
parser.add_argument("--skip_first", type=int, default=10, help="Skip the first N frames when encoding the video.")

# Isaac Lab defaults (device, experience, etc.)
AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()

# Launch Omniverse
app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

# ---------------------------
# Isaac / Omniverse imports
# ---------------------------
import isaacsim.core.utils.prims as prim_utils
import isaaclab.sim as sim_utils

from pxr import UsdPhysics, Gf
import omni.usd
import numpy as np

import omni.kit.viewport.utility as vp_utils  # viewport-based capture

# ---------------------------
# Scene helpers
# ---------------------------
def build_pyramid(parent: str, levels: int = 6, cube_size: float = 0.15, gap: float = 0.02, base_xy=(0.0, 0.0), z0: float = 0.075):
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
            name = f"{parent}/cube_{lvl}_{j}"
            cfg_cube.func(name, cfg_cube, translation=(x, y, z))

def throw_object(prim_path: str, direction=(1.0, 0.0, 0.5), speed=8.0):
    d = np.array(direction, dtype=float)
    n = d / (np.linalg.norm(d) + 1e-8)
    v = n * float(speed)
    stage = omni.usd.get_context().get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    rb = UsdPhysics.RigidBodyAPI(prim)
    rb.CreateRigidBodyEnabledAttr(True)
    rb.GetVelocityAttr().Set(Gf.Vec3f(float(v[0]), float(v[1]), float(v[2])))

def design_scene():
    cfg_ground = sim_utils.GroundPlaneCfg()
    cfg_ground.func("/World/defaultGroundPlane", cfg_ground)
    cfg_light_distant = sim_utils.DistantLightCfg(intensity=5000.0, color=(0.75, 0.75, 0.75))
    cfg_light_distant.func("/World/lightDistant", cfg_light_distant, translation=(1, 0, 10))
    custom_obj_cfg = sim_utils.UsdFileCfg(
        usd_path=f"{args_cli.usd_path_abs}",
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

# ---------------------------
# Video helpers
# ---------------------------
def _ffmpeg():
    return shutil.which("ffmpeg")

def _encode(frames_dir: str, out_mp4_path: str, fps: int, pattern_glob: str, start_number: int = 0):
    ff = _ffmpeg()
    if ff is None:
        print("[WARN] ffmpeg not found; keeping image sequence only.")
        return False
    cmd = [
        ff, "-y",
        "-framerate", str(fps),
        "-start_number", str(max(0, int(start_number))),
        "-pattern_type", "sequence",
        "-i", os.path.join(frames_dir, pattern_glob),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        out_mp4_path,
    ]
    print(f"[INFO] Encoding MP4 with ffmpeg (skipping first {start_number} frames)...")
    subprocess.run(cmd, check=True)
    print(f"[INFO] MP4 saved to: {out_mp4_path}")
    return True

def _detect_rgb_pattern(frames_dir: str):
    cand = sorted(glob.glob(os.path.join(frames_dir, "rgb_*.png")) +
                  glob.glob(os.path.join(frames_dir, "rgb_*.jpg")))
    if not cand:
        return None, None
    sample = os.path.basename(cand[0])         # e.g., rgb_00001.png
    ext = ".jpg" if sample.endswith(".jpg") else ".png"
    name, _ = os.path.splitext(sample)          # rgb_00001
    _, digits = name.split("_", 1)              # 00001
    width = len(digits)
    pattern = f"rgb_%0{width}d{ext}"
    return pattern, sample

# ---------------------------
# Main
# ---------------------------
def main():
    # Simulation context
    sim_cfg = sim_utils.SimulationCfg(dt=0.01, device=args_cli.device)
    sim = sim_utils.SimulationContext(sim_cfg)

    # Camera
    sim.set_camera_view([0.0, -4.0, 4.0], [0.0, 0.0, 3.0])

    # Scene
    design_scene()
    build_pyramid("/World/Objects/Pyramid", levels=20, cube_size=0.15, gap=0.00, base_xy=(0.0, 10.0), z0=0.075)
    throw_object("/World/Objects/custom_obj", direction=(0.0, 1.0, 0.1), speed=17.0)

    # Initialize
    sim.reset()
    print("[INFO]: Setup complete.")

    # If not recording, just run one pass for video_length steps and exit (no file I/O)
    if not args_cli.video:
        steps = max(1, args_cli.video_length)
        print(f"[INFO] Running {steps} steps (no recording).")
        start = time.time()
        for _ in range(steps):
            sim.step()
        print(f"[INFO] Done in {time.time() - start:.2f}s.")
        return

    # --- Recording path: viewport capture (no Replicator) ---
    print("[INFO] Recording video (viewport capture, no Replicator)...")

    # Prepare output dirs (clean slate)
    out_dir = os.path.abspath(args_cli.out_dir)
    frames_dir = os.path.join(out_dir, "frames")
    if os.path.isdir(frames_dir):
        shutil.rmtree(frames_dir)
    os.makedirs(frames_dir, exist_ok=True)

    # Viewport/render setup
    viewport = vp_utils.get_active_viewport()
    viewport.set_texture_resolution((args_cli.width, args_cli.height))

    # Step & capture
    steps_total = max(1, args_cli.video_length)
    every_n = max(1, args_cli.every_n)

    # physics dt (for --real-time pacing)
    dt = sim.get_physics_dt() if hasattr(sim, "get_physics_dt") else 0.01

    ext = "jpg" if args_cli.jpg else "png"
    captured = 0
    for i in range(steps_total):
        t0 = time.time()
        sim.step()

        if (i % every_n) == 0:
            # Force a render tick before capturing (helps on some setups)
            simulation_app.update()
            frame_path = os.path.join(frames_dir, f"rgb_{captured:05d}.{ext}")
            # IMPORTANT: pass viewport first, then path
            vp_utils.capture_viewport_to_file(viewport, frame_path)
            captured += 1

        if args_cli.real_time:
            sleep_time = dt - (time.time() - t0)
            if sleep_time > 0:
                time.sleep(sleep_time)

    if captured == 0:
        # Safety: always write at least one frame
        simulation_app.update()
        frame_path = os.path.join(frames_dir, f"rgb_{0:05d}.{ext}")
        vp_utils.capture_viewport_to_file(viewport, frame_path)
        captured = 1

    print(f"[INFO] Captured {captured} frames to: {frames_dir}")

    # Stitch to MP4
    pattern, sample = _detect_rgb_pattern(frames_dir)
    if not pattern:
        print("[ERROR] No frames found in:", frames_dir)
        return

    print("[INFO] Saved the image sequence.")

    video_path = os.path.join(out_dir, args_cli.video_name if args_cli.video_name.endswith(".mp4")
                              else args_cli.video_name + ".mp4")

    # Clamp skip to available range to avoid empty outputs
    effective_skip = max(0, int(args_cli.skip_first))
    if effective_skip >= captured:
        print(f"[WARN] Requested skip_first={effective_skip} exceeds captured frames ({captured}). "
              f"Clamping to {max(0, captured - 1)} to ensure at least one frame is encoded.")
        effective_skip = max(0, captured - 1)

    made_mp4 = _encode(frames_dir, video_path, args_cli.fps, pattern, start_number=effective_skip)

    if not made_mp4:
        print(f"[INFO] Frames saved to: {frames_dir}")
        print("[INFO] Encode manually, e.g.:")
        print(f'       ffmpeg -y -framerate {args_cli.fps} -start_number {effective_skip} '
              f'-pattern_type sequence -i "{os.path.join(frames_dir, pattern)}" '
              f'-c:v libx264 -pix_fmt yuv420p -movflags +faststart "{video_path}"')

    if os.path.isdir(frames_dir):
        print(f"[INFO] Cleaning up frame directory: {frames_dir}")
        shutil.rmtree(frames_dir, ignore_errors=True)

    else:
        print(f"[INFO] Done. Video: {video_path}")

if __name__ == "__main__":
    import sys, os
    #try:
    main()
    #finally:
    #    os._exit(0)  # because fuck you