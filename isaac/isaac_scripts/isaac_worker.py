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

def throw_object(prim_path: str, direction=(1.0, 0.0, 0.5), speed=8.0):
    """Throw object using Isaac Lab RigidObject (GPU-compatible)"""
    d = np.array(direction, dtype=float)
    n = d / (np.linalg.norm(d) + 1e-8)
    v = n * float(speed)
    
    print(f"🎯 Will apply velocity to {prim_path}: {v}")
    return v

def design_scene(usd_path_abs, scaling_factor=1.0):
    cfg_ground = sim_utils.GroundPlaneCfg()
    cfg_ground.func("/World/defaultGroundPlane", cfg_ground)
    
    cfg_light = sim_utils.DistantLightCfg(intensity=3000.0, color=(1.0, 1.0, 1.0))
    cfg_light.func("/World/lightDistant", cfg_light, translation=(1, 0, 10))
    
    cfg_light2 = sim_utils.DistantLightCfg(intensity=2000.0, color=(1.0, 1.0, 1.0))
    cfg_light2.func("/World/lightDistant2", cfg_light2, translation=(-1, -1, 8))

    # Just spawn using simple UsdFileCfg
    obj_cfg = sim_utils.UsdFileCfg(
        usd_path=usd_path_abs,
        scale=(scaling_factor, scaling_factor, scaling_factor),
        rigid_props=sim_utils.RigidBodyPropertiesCfg(),
        mass_props=sim_utils.MassPropertiesCfg(mass=1.0),
        collision_props=sim_utils.CollisionPropertiesCfg(),
    )
    obj_cfg.func("/World/Objects/custom_obj", obj_cfg, translation=(0.0, 0.0, 2.0))

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
    cmd = [
        ffmpeg, "-y", "-framerate", str(fps),
        "-start_number", str(skip_first),
        "-pattern_type", "sequence",
        "-i", os.path.join(frames_dir, f"rgb_%0{digits}d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", out_path
    ]
    subprocess.run(cmd, check=True)
    print(f"[INFO] MP4 saved → {out_path}")

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
                
                # Extract params
                usd_path = data['usd_path']
                out_dir = data.get('out_dir', '/workspace/s2w-data/recordings')
                video = data.get('video', True)
                video_length = data.get('video_length', 200)
                fps = data.get('fps', 50)
                scaling_factor = data.get('scaling_factor', 1.0)
                skip_first = data.get('skip_first', 10)
                
                stage = sim_context.stage
                camera_path = "/World/RenderCamera"
                
                # === CLEANUP ===
                print("🧹 Cleaning up old objects...")
                
                # Only remove dynamic content, NOT the camera
                paths_to_remove = [
                    "/World/Objects",
                    "/World/defaultGroundPlane",
                    "/World/lightDistant",
                    "/World/lightDistant2"
                ]
                
                for path in paths_to_remove:
                    if stage.GetPrimAtPath(path).IsValid():
                        stage.RemovePrim(path)
                
                # Reset physics to clear cached state
                sim_context.reset()
                
                sim_context.step()
                app_interface.update()
                print("✅ Cleanup done")
        
                # === CREATE OR REUSE CAMERA ===
                if camera is None:
                    print("📷 Creating camera (first time)")
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
                            pos=(0.0, -5.0, 7.0),
                            rot=(0.6830, -0.1830, 0.1830, 0.6830),
                            convention="world"
                        )
                    )
                    camera = Camera(cfg=camera_cfg)
                    
                    # Initialize the camera
                    print("📷 Initializing camera...")
                    camera._initialize_callback(None)
                    print("✅ Camera created and initialized")
                else:
                    print("📷 Reusing existing camera")
        
                # BUILD SCENE
                # BUILD SCENE
                print("🏗️  Building scene...")
                design_scene(usd_path, scaling_factor)
                build_pyramid("/World/Objects/Pyramid", levels=20, cube_size=0.15, gap=0.0, base_xy=(0.0, 10.0), z0=0.075)
                
                # Create RigidObject wrapper AFTER scene is built
                from isaaclab.assets import RigidObject, RigidObjectCfg
                obj_cfg = RigidObjectCfg(prim_path="/World/Objects/custom_obj", spawn=None)
                rigid_obj = RigidObject(cfg=obj_cfg)
                
                # Initialize physics AND play the simulation
                print("⚙️  Initializing physics...")
                dt = sim_context.get_physics_dt() if hasattr(sim_context, "get_physics_dt") else 0.01
                sim_context.reset()  # This plays the simulation and initializes physics handles
                
                for _ in range(5):
                    sim_context.step()
                    app_interface.update()
                
                # Update buffers to populate the data attribute
                rigid_obj.update(dt)
                
                # NOW set velocity - clone from default state
                print("🎯 Applying velocity...")
                root_state = rigid_obj.data.default_root_state.clone()
                root_state[:, 7:10] = torch.tensor([0.0, 17.0, 1.7], device=root_state.device)  # Set lin_vel
                
                # Write to simulation
                rigid_obj.write_root_pose_to_sim(root_state[:, :7])
                rigid_obj.write_root_velocity_to_sim(root_state[:, 7:])
                
                # Reset internal buffers
                rigid_obj.reset()
                
                print("✅ Velocity applied!")

                os.makedirs(out_dir, exist_ok=True)
                frames_dir = os.path.join(out_dir, "frames")
                if os.path.isdir(frames_dir):
                    shutil.rmtree(frames_dir)
                os.makedirs(frames_dir)
                
                steps = max(1, video_length)
                captured = 0
                
                print(f"🎬 Running {steps} simulation steps...")
                for i in range(steps):
                    t0 = time.time()
                                        
                    sim_context.step()

                    if video and (i % 1) == 0:
                        app_interface.update()
                        
                        camera.update(dt)
                        rgb_data = camera.data.output["rgb"]
                        
                        frame_path = os.path.join(frames_dir, f"rgb_{captured:05d}.png")
                        import cv2
                        
                        if hasattr(rgb_data, 'cpu'):
                            rgb_data = rgb_data.cpu().numpy()
                        
                        if rgb_data.ndim == 4:
                            rgb_data = rgb_data[0]
                        
                        if i % 50 == 0:
                            print(f"   Frame {captured}/{steps}")
                        
                        cv2.imwrite(frame_path, cv2.cvtColor(rgb_data, cv2.COLOR_RGB2BGR))
                        captured += 1
                    
                    sleep_time = dt - (time.time() - t0)
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                
                # Cleanup - but keep the camera!
                print("🧹 Final cleanup (keeping camera)...")
                for path in paths_to_remove:
                    if stage.GetPrimAtPath(path).IsValid():
                        stage.RemovePrim(path)
                
                if video:
                    print("🎥 Encoding video...")
                    out_mp4 = os.path.join(out_dir, "sim_run.mp4")
                    ffmpeg_encode(frames_dir, out_mp4, fps, skip_first)
                    shutil.rmtree(frames_dir, ignore_errors=True)
                
                job_results[job_id] = {
                    "status": "completed",
                    "frames": captured,
                    "output": out_dir,
                    "video_path": out_mp4
                }
                print(f"✅ Simulation {job_id} done ({captured} frames)")
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