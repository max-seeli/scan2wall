#!/usr/bin/env python3
import sys

# Force all output to stderr (unbuffered)
sys.stdout = sys.stderr

#!/usr/bin/env python3
"""
Persistent Isaac Lab worker - Kit main loop with HTTP server
"""

# Start Isaac FIRST
from isaaclab.app import AppLauncher
print("🚀 Launching Isaac Lab (headless with offscreen rendering)...")
app_launcher = AppLauncher({
    "headless": True,
    "enable_cameras": True  # This enables offscreen rendering!
})
simulation_app = app_launcher.app

# Import Isaac modules
from isaaclab.sim import SimulationContext
import isaaclab.sim as sim_utils
import isaacsim.core.utils.prims as prim_utils
import isaacsim.core.utils.viewports as vp_utils
from isaaclab.sim.converters import MeshConverter, MeshConverterCfg
from pxr import UsdPhysics, Gf
import numpy as np
import os, shutil, glob, subprocess, time
import torch
from PIL import Image as PILImage
# Initialize simulation
sim_context = SimulationContext()
print("✅ Isaac Lab initialized")

# Helper functions
def build_pyramid(parent: str, levels: int = 6, cube_size=0.15, gap=0.02, base_xy=(0.0, 0.0), z0=0.075):
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

def build_wall(parent: str, width: int = 15, height: int = 12, brick_width=0.3, brick_height=0.15, brick_depth=0.15, gap=0.01, base_xy=(0.0, 10.0), z0=0.075):
    prim_utils.create_prim(parent, "Xform")
    
    cfg_brick = sim_utils.CuboidCfg(
        size=(brick_width * 0.97, brick_depth * 0.97, brick_height * 0.97),  # Slightly smaller for dark edge gaps
        rigid_props=sim_utils.RigidBodyPropertiesCfg(),
        collision_props=sim_utils.CollisionPropertiesCfg(
            contact_offset=0.02,
            rest_offset=0.0
        ),
        mass_props=sim_utils.MassPropertiesCfg(mass=0.5),
        visual_material=sim_utils.PreviewSurfaceCfg(
            diffuse_color=(0.7, 0.3, 0.2),  # Reddish-brown brick color
            roughness=0.8  # Matte finish
        ),
    )
    
    x0, y0 = base_xy
    brick_spacing_x = brick_width + gap
    brick_spacing_z = brick_height + gap
    
    for row in range(height):
        # Alternate brick pattern (offset every other row by half a brick)
        offset = (brick_spacing_x / 2) if row % 2 == 1 else 0

        for col in range(width):
            # Skip edge bricks on top row (they're unstable)
            if row == height - 1 and (col == 0 or col == width - 1):
                continue

            x = x0 - 0.5 * (width - 1) * brick_spacing_x + col * brick_spacing_x + offset
            y = y0
            z = z0 + row * brick_spacing_z

            cfg_brick.func(f"{parent}/brick_{row}_{col}", cfg_brick, translation=(x, y, z))
def throw_object(prim_path: str, direction=(1.0, 0.0, 1.0), speed=8.0):
    """Throw object using Isaac Lab RigidObject (GPU-compatible)"""
    d = np.array(direction, dtype=float)
    n = d / (np.linalg.norm(d) + 1e-8)
    v = n * float(speed)
    
    print(f"🎯 Will apply velocity to {prim_path}: {v}")
    return v

def design_scene(usd_path_abs, scaling_factor=1.0):
    # Textured ground plane (concrete/pavement look with roughness)
    cfg_ground = sim_utils.GroundPlaneCfg(
        color=(0.35, 0.35, 0.35),  # Dark gray concrete
        physics_material=sim_utils.RigidBodyMaterialCfg(
            static_friction=0.7,
            dynamic_friction=0.6
        )
    )
    # Apply visual material with roughness for texture
    cfg_ground.visual_material = sim_utils.PreviewSurfaceCfg(
        diffuse_color=(0.35, 0.35, 0.35),
        roughness=0.9,  # Very rough for asphalt look
        metallic=0.0
    )
    cfg_ground.func("/World/defaultGroundPlane", cfg_ground)

    # Add sky dome light (very bright blue sky background)
    cfg_dome = sim_utils.DomeLightCfg(
        intensity=2000.0,  # Much brighter
        color=(0.3, 0.6, 1.0)  # Deep sky blue
    )
    cfg_dome.func("/World/skyDome", cfg_dome)

    # Reduced intensity 3-point lighting to let sky show through
    # Key light (main, from front-left, elevated) - warmer tone
    cfg_key = sim_utils.DistantLightCfg(intensity=2000.0, color=(1.0, 0.95, 0.85))
    cfg_key.func("/World/lightKey", cfg_key, translation=(-3, -2, 8))

    # Fill light (softer, from front-right, lower intensity) - slightly cool
    cfg_fill = sim_utils.DistantLightCfg(intensity=800.0, color=(0.9, 0.9, 1.0))
    cfg_fill.func("/World/lightFill", cfg_fill, translation=(3, -1, 5))

    # Rim/back light (from behind, creates edge definition) - reduced
    cfg_rim = sim_utils.DistantLightCfg(intensity=600.0, color=(1.0, 1.0, 1.0))
    cfg_rim.func("/World/lightRim", cfg_rim, translation=(0, 5, 6))

    # Just spawn using simple UsdFileCfg
    obj_cfg = sim_utils.UsdFileCfg(
        usd_path=usd_path_abs,
        scale=(scaling_factor, scaling_factor, scaling_factor),
        rigid_props=sim_utils.RigidBodyPropertiesCfg(),
        mass_props=sim_utils.MassPropertiesCfg(mass=1.0),
        collision_props=sim_utils.CollisionPropertiesCfg(),
    )
    obj_cfg.func("/World/Objects/custom_obj", obj_cfg, translation=(0.0, 0.0, 0.5))

def ffmpeg_encode(frames_dir, out_path, fps, skip_first=0):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        print("[WARN] ffmpeg not found; keeping image sequence.")
        return
    pattern = sorted(glob.glob(os.path.join(frames_dir, "rgb_*.png")))
    if not pattern:
        print("[WARN] No frames to encode.")
        return
    digits = len(os.path.basename(pattern[0]).split("_")[1].split(".")[0])

    # Add watermark with ffmpeg drawtext filter
    watermark_filter = (
        "drawtext=text='scan2wall.com':"
        "fontsize=32:"
        "fontcolor=white@0.8:"
        "x=w-tw-20:"
        "y=h-th-20:"
        "shadowcolor=black@0.6:"
        "shadowx=2:shadowy=2"
    )

    cmd = [
        ffmpeg, "-y", "-framerate", str(fps),
        "-start_number", str(skip_first),
        "-pattern_type", "sequence",
        "-i", os.path.join(frames_dir, f"rgb_%0{digits}d.png"),
        "-vf", watermark_filter,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", out_path
    ]
    subprocess.run(cmd, check=True)
    print(f"[INFO] MP4 with watermark saved → {out_path}")

# HTTP server
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import threading
from queue import Queue
import uuid

# Job queue
job_queue = Queue()
job_results = {}

class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/convert':
            self._handle_convert()
        elif self.path == '/run_simulation':
            self._handle_simulation()
        else:
            self.send_response(404)
            self.end_headers()
    
    def _handle_convert(self):
        content_length = int(self.headers['Content-Length'])
        body = self.rfile.read(content_length)
        req = json.loads(body)
        
        job_id = str(uuid.uuid4())
        print(f"🔄 Queuing conversion: {req['asset_path']} (job: {job_id})")
        
        cfg = MeshConverterCfg(
            asset_path=req['asset_path'],
            usd_dir=req['usd_dir'],
            force_usd_conversion=True,
            make_instanceable=False,
            mass_props=sim_utils.MassPropertiesCfg(mass=req.get('mass', 1.0)),
            rigid_props=sim_utils.RigidBodyPropertiesCfg(),  # ADD THIS
            collision_props=sim_utils.CollisionPropertiesCfg(),  # ADD THIS
        )
        
        job_queue.put(('convert', job_id, cfg))
        result = self._wait_for_result(job_id)
        
        if result["status"] == "completed":
            print(f"✅ Conversion complete (job: {job_id})")
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "completed",
                "usd_dir": req['usd_dir'],
                "job_id": job_id
            }).encode())
        else:
            print(f"❌ Failed (job: {job_id})")
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
    
    def _handle_simulation(self):
        content_length = int(self.headers['Content-Length'])
        body = self.rfile.read(content_length)
        req = json.loads(body)
        
        job_id = str(uuid.uuid4())
        print(f"🎬 Queuing simulation: {req['usd_path']} (job: {job_id})")
        
        job_queue.put(('simulate', job_id, req))
        result = self._wait_for_result(job_id, timeout=300)  # 5 min timeout for sims
        
        if result["status"] == "completed":
            print(f"✅ Simulation complete (job: {job_id})")
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        else:
            print(f"❌ Simulation failed (job: {job_id})")
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
    
    def _wait_for_result(self, job_id, timeout=120):
        start = time.time()
        while job_id not in job_results:
            time.sleep(0.1)
            if time.time() - start > timeout:
                return {"status": "timeout", "job_id": job_id}
        return job_results.pop(job_id)
    
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ready",
                "queue_size": job_queue.qsize()
            }).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass  # Suppress default logging

# Start HTTP server in background
def run_http_server():
    server = HTTPServer(('0.0.0.0', 8090), RequestHandler)
    print("🌐 HTTP server started on port 8090")
    server.serve_forever()

http_thread = threading.Thread(target=run_http_server, daemon=True)
http_thread.start()

# Process jobs on Kit's main loop
import omni.kit.app
app_interface = omni.kit.app.get_app_interface()

print("✅ Kit main loop running")
print("   API: http://localhost:8090")
print("   Endpoints: /convert, /run_simulation")
print("   Ctrl+C to stop")

camera = None
follow_camera = None
frame_count = 0
while app_interface.is_running():
    # Process jobs on main thread
    if not job_queue.empty():
        job_type, job_id, data = job_queue.get()
        
        if job_type == 'convert':
            print(f"⚙️  Processing conversion {job_id}...")
            try:
                MeshConverter(data)
                job_results[job_id] = {"status": "completed"}
                print(f"✅ Conversion {job_id} done")
            except Exception as e:
                import traceback
                traceback.print_exc()
                job_results[job_id] = {"status": "failed", "error": str(e)}
                print(f"❌ Conversion {job_id} failed: {e}")
        
        elif job_type == 'simulate':
            print(f"⚙️  Processing simulation {job_id}...")
            try:
                
                # Start timing
                sim_start_time = time.time()

                # Extract params
                usd_path = data['usd_path']
                out_dir = data.get('out_dir', '/workspace/s2w-data/recordings')
                video = data.get('video', True)
                video_length = data.get('video_length', 200)
                fps = data.get('fps', 50)
                scaling_factor = data.get('scaling_factor', 1.0)
                skip_first = data.get('skip_first', 10)
                request_job_id = data.get('job_id', 'unknown')  # Get job_id from request

                stage = sim_context.stage
                camera_path = "/World/RenderCamera"
                
                # === CLEANUP ===
                print("🧹 Cleaning up old objects...")
                
                # Only remove dynamic content, NOT the camera
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
                
                # Reset physics to clear cached state
                sim_context.reset()
                
                sim_context.step()
                app_interface.update()
                print("✅ Cleanup done")
        
                # === CREATE OR REUSE CAMERAS ===
                if camera is None:
                    print("📷 Creating static camera (first time)")
                    from isaaclab.sensors.camera import Camera, CameraCfg

                    camera_cfg = CameraCfg(
                        prim_path=camera_path,
                        update_period=0,
                        height=1080,
                        width=1920,
                        data_types=["rgb"],
                        spawn=sim_utils.PinholeCameraCfg(
                            focal_length=24.0,
                            focus_distance=400.0,
                            horizontal_aperture=20.955,
                            clipping_range=(0.1, 1.0e5)
                        ),
                        offset=CameraCfg.OffsetCfg(
                            pos=(0.0, -8.0, 1.2),
                            rot=(0.7071, 0.0, 0.0, 0.7071),
                            convention="world"
                        )
                    )
                    camera = Camera(cfg=camera_cfg)

                    # Initialize the static camera
                    print("📷 Initializing static camera...")
                    camera._initialize_callback(None)
                    print("✅ Static camera created and initialized")
                else:
                    print("📷 Reusing existing static camera")

                # Create follow camera
                if follow_camera is None:
                    print("📷 Creating follow camera (first time)")
                    from isaaclab.sensors.camera import Camera, CameraCfg

                    follow_camera_cfg = CameraCfg(
                        prim_path="/World/FollowCamera",
                        update_period=0,
                        height=1080,
                        width=1920,
                        data_types=["rgb"],
                        spawn=sim_utils.PinholeCameraCfg(
                            focal_length=24.0,
                            focus_distance=400.0,
                            horizontal_aperture=20.955,
                            clipping_range=(0.1, 1.0e5)
                        ),
                        offset=CameraCfg.OffsetCfg(
                            pos=(0.0, -3.0, 0.0),  # Centered on object, 3m back - updated each frame
                            rot=(0.7071, 0.7071, 0.0, 0.0),  # FIXED: +Y forward, +Z up (90° around X)
                            convention="world"
                        )
                    )
                    follow_camera = Camera(cfg=follow_camera_cfg)

                    # Initialize the follow camera
                    print("📷 Initializing follow camera...")
                    follow_camera._initialize_callback(None)
                    print("✅ Follow camera created and initialized")
                else:
                    print("📷 Reusing existing follow camera")
        
                # BUILD SCENE
                # BUILD SCENE
                print("🏗️  Building scene...")
                design_scene(usd_path, scaling_factor)
                build_wall("/World/Objects/Wall", width=15, height=20, brick_width=0.3, brick_height=0.15, brick_depth=0.15, gap=0.0, base_xy=(0.0, 10.0), z0=0.075)
                
                # Create RigidObject wrapper AFTER scene is built
                from isaaclab.assets import RigidObject, RigidObjectCfg
                obj_cfg = RigidObjectCfg(prim_path="/World/Objects/custom_obj", spawn=None)
                rigid_obj = RigidObject(cfg=obj_cfg)

                # Initialize physics AND play the simulation
                print("⚙️  Initializing physics...")
                dt = sim_context.get_physics_dt() if hasattr(sim_context, "get_physics_dt") else 0.01
                sim_context.reset()  # This plays the simulation and initializes physics handles

                # More warmup steps to let wall settle
                for _ in range(20):
                    sim_context.step()
                    app_interface.update()

                # Update buffers to populate the data attribute
                rigid_obj.update(dt)

                os.makedirs(out_dir, exist_ok=True)
                frames_dir_static = os.path.join(out_dir, "frames_static")
                frames_dir_follow = os.path.join(out_dir, "frames_follow")

                if os.path.isdir(frames_dir_static):
                    shutil.rmtree(frames_dir_static)
                if os.path.isdir(frames_dir_follow):
                    shutil.rmtree(frames_dir_follow)

                os.makedirs(frames_dir_static)
                os.makedirs(frames_dir_follow)
                
                steps = max(1, video_length)
                captured = 0
                velocity_applied = False
                pause_frames = 50  # 1 second pause at 50 FPS

                print(f"🎬 Running {steps} simulation steps (1s pause, then throw)...")
                for i in range(steps):
                    t0 = time.time()

                    # Apply velocity after pause period
                    if not velocity_applied and captured >= pause_frames:
                        print("🎯 Applying velocity after pause...")
                        rigid_obj.update(dt)  # Update buffers first
                        root_state = rigid_obj.data.default_root_state.clone()
                        root_state[:, 7:10] = torch.tensor([0.0, 13.0, 6.0], device=root_state.device)
                        rigid_obj.write_root_pose_to_sim(root_state[:, :7])
                        rigid_obj.write_root_velocity_to_sim(root_state[:, 7:])
                        rigid_obj.reset()
                        velocity_applied = True
                        print("✅ Velocity applied!")

                    sim_context.step()

                    if video and (i % 1) == 0:
                        app_interface.update()
                        rigid_obj.update(dt)  # Update for next frame

                        # Get object position for follow camera
                        obj_pos = rigid_obj.data.root_pos_w[0].cpu().numpy()

                        # Update follow camera position (centered behind object)
                        from pxr import Gf
                        follow_offset = Gf.Vec3d(0.0, -3.0, 0.0)  # X=0 (centered), Y=-3m (behind), Z=0 (centered)
                        follow_pos = Gf.Vec3d(float(obj_pos[0]), float(obj_pos[1]), float(obj_pos[2])) + follow_offset

                        # Update follow camera transform (position only, keep rotation fixed)
                        follow_cam_prim = stage.GetPrimAtPath("/World/FollowCamera")
                        if follow_cam_prim.IsValid():
                            from pxr import UsdGeom
                            xformable = UsdGeom.Xformable(follow_cam_prim)
                            xformable.ClearXformOpOrder()
                            xformable.AddTranslateOp().Set(follow_pos)
                            # Fixed rotation: look forward in +Y direction
                            # Quaternion (w, x, y, z) = (0.7071, 0.7071, 0, 0) is 90° around X-axis
                            # This rotates camera from looking down -Z to looking forward +Y
                            xformable.AddOrientOp(precision=UsdGeom.XformOp.PrecisionDouble).Set(Gf.Quatd(0.7071, 0.7071, 0.0, 0.0))

                        # === CAPTURE FROM STATIC CAMERA ===
                        camera.update(dt)
                        rgb_data_static = camera.data.output["rgb"]

                        frame_path_static = os.path.join(frames_dir_static, f"rgb_{captured:05d}.png")

                        if hasattr(rgb_data_static, 'cpu'):
                            rgb_data_static = rgb_data_static.cpu().numpy()

                        if rgb_data_static.ndim == 4:
                            rgb_data_static = rgb_data_static[0]

                        rgb_uint8_static = (rgb_data_static * 255).astype('uint8')
                        # Isaac Lab returns RGB, PIL expects RGB - no conversion needed
                        PILImage.fromarray(rgb_uint8_static).save(frame_path_static)

                        # === CAPTURE FROM FOLLOW CAMERA ===
                        follow_camera.update(dt)
                        rgb_data_follow = follow_camera.data.output["rgb"]

                        frame_path_follow = os.path.join(frames_dir_follow, f"rgb_{captured:05d}.png")

                        if hasattr(rgb_data_follow, 'cpu'):
                            rgb_data_follow = rgb_data_follow.cpu().numpy()

                        if rgb_data_follow.ndim == 4:
                            rgb_data_follow = rgb_data_follow[0]

                        rgb_uint8_follow = (rgb_data_follow * 255).astype('uint8')
                        # Isaac Lab returns RGB, PIL expects RGB - no conversion needed
                        PILImage.fromarray(rgb_uint8_follow).save(frame_path_follow)

                        captured += 1

                        if i % 50 == 0:
                            print(f"   Frame {captured}/{steps}")
                    
                    sleep_time = dt - (time.time() - t0)
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                
                # Cleanup - but keep the camera!
                print("🧹 Final cleanup (keeping camera)...")
                for path in paths_to_remove:
                    if stage.GetPrimAtPath(path).IsValid():
                        stage.RemovePrim(path)
                
                # Mark simulation time (before encoding)
                sim_end_time = time.time()
                simulation_time = sim_end_time - sim_start_time

                encoding_start_time = time.time()
                if video:
                    print("🎥 Encoding videos...")
                    # Encode static camera video
                    video_filename_static = f"{request_job_id}_static.mp4"
                    out_mp4_static = os.path.join(out_dir, video_filename_static)
                    print("   Encoding static camera view...")
                    ffmpeg_encode(frames_dir_static, out_mp4_static, fps, skip_first)
                    shutil.rmtree(frames_dir_static, ignore_errors=True)

                    # Encode follow camera video
                    video_filename_follow = f"{request_job_id}_follow.mp4"
                    out_mp4_follow = os.path.join(out_dir, video_filename_follow)
                    print("   Encoding follow camera view...")
                    ffmpeg_encode(frames_dir_follow, out_mp4_follow, fps, skip_first)
                    shutil.rmtree(frames_dir_follow, ignore_errors=True)

                encoding_end_time = time.time()
                encoding_time = encoding_end_time - encoding_start_time
                total_time = encoding_end_time - sim_start_time

                job_results[job_id] = {
                    "status": "completed",
                    "frames": captured,
                    "output": out_dir,
                    "video_path_static": out_mp4_static,
                    "video_path_follow": out_mp4_follow,
                    "timing": {
                        "simulation_seconds": round(simulation_time, 2),
                        "encoding_seconds": round(encoding_time, 2),
                        "total_seconds": round(total_time, 2)
                    }
                }
                print(f"✅ Simulation {job_id} done ({captured} frames, {total_time:.1f}s total)")
            except Exception as e:
                import traceback
                traceback.print_exc()
                job_results[job_id] = {"status": "failed", "error": str(e)}
                print(f"❌ Simulation {job_id} failed: {e}")    
    app_interface.update()
    frame_count += 1
    
    if frame_count % 600 == 0:
        print(f"💓 Alive (frame {frame_count}, queue: {job_queue.qsize()})")

print("👋 Shutdown")