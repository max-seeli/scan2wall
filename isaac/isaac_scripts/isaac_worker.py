#!/usr/bin/env python3
"""
Persistent Isaac Lab worker - Kit main loop with simple HTTP
"""

# Start Isaac FIRST
from isaaclab.app import AppLauncher
print("🚀 Launching Isaac Lab (headless)...")
app_launcher = AppLauncher(headless=True)
simulation_app = app_launcher.app

# Import Isaac modules
from isaaclab.sim import SimulationContext
import isaaclab.sim as sim_utils
import isaacsim.core.utils.prims as prim_utils
import isaacsim.core.utils.viewports as vp_utils
from isaaclab.sim.converters import MeshConverter, MeshConverterCfg
from pxr import UsdPhysics, Gf

# Initialize simulation
sim_context = SimulationContext()
print("✅ Isaac Lab initialized")

# Simple HTTP server
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import threading
from queue import Queue
import uuid

# Job queue
job_queue = Queue()
job_results = {}

class ConversionHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/convert':
            # Read request body
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            req = json.loads(body)
            
            job_id = str(uuid.uuid4())
            print(f"🔄 Queuing conversion: {req['asset_path']} (job: {job_id})")
            
            # Create config
            cfg = MeshConverterCfg(
                asset_path=req['asset_path'],
                usd_dir=req['usd_dir'],
                force_usd_conversion=True,
                make_instanceable=False,
                mass_props=sim_utils.MassPropertiesCfg(mass=req.get('mass', 1.0)),
            )
            
            # Queue job
            job_queue.put((job_id, cfg))
            
            # Wait for result
            import time
            timeout = 120
            start = time.time()
            while job_id not in job_results:
                time.sleep(0.1)
                if time.time() - start > timeout:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "timeout", "job_id": job_id}).encode())
                    return
            
            result = job_results.pop(job_id)
            
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
        else:
            self.send_response(404)
            self.end_headers()
    
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
        # Suppress default logging
        pass

# Start HTTP server in background
def run_http_server():
    server = HTTPServer(('0.0.0.0', 8090), ConversionHandler)
    print("🌐 HTTP server started on port 8090")
    server.serve_forever()

http_thread = threading.Thread(target=run_http_server, daemon=True)
http_thread.start()

# Process jobs on Kit's main loop
import omni.kit.app
app_interface = omni.kit.app.get_app_interface()

print("✅ Kit main loop running")
print("   API: http://localhost:8090")
print("   Ctrl+C to stop")

frame_count = 0
while app_interface.is_running():
    # Process jobs on main thread
    if not job_queue.empty():
        job_id, cfg = job_queue.get()
        print(f"⚙️  Processing job {job_id}...")
        
        try:
            MeshConverter(cfg)
            job_results[job_id] = {"status": "completed"}
            print(f"✅ Job {job_id} done")
        except Exception as e:
            import traceback
            traceback.print_exc()
            job_results[job_id] = {"status": "failed", "error": str(e)}
            print(f"❌ Job {job_id} failed: {e}")
    
    app_interface.update()
    frame_count += 1
    
    if frame_count % 600 == 0:
        print(f"💓 Alive (frame {frame_count}, queue: {job_queue.qsize()})")

print("👋 Shutdown")