#!/usr/bin/env python3
import sys

# Force all output to stderr (unbuffered)
sys.stdout = sys.stderr

"""
Isaac Lab Worker - Entry Point

Minimal entry point that wires together:
- HTTP server (http_handlers.py) - Receives API requests
- Kit main loop (kit_main_loop.py) - Processes jobs using Isaac Sim

Architecture:
    HTTP Request → RequestHandler → Job Queue → Kit Main Loop → Job Results → HTTP Response
"""

# ============================================================================
# STEP 1: Initialize Isaac Lab
# ============================================================================

from isaaclab.app import AppLauncher

# Launch Isaac Lab in headless mode with camera support
print(f"🚀 Launching Isaac Lab (headless mode with cameras)...")
app_launcher = AppLauncher({
    "headless": True,
    "enable_cameras": True
})
simulation_app = app_launcher.app

import omni.kit.app
extension_manager = omni.kit.app.get_app().get_extension_manager()
extension_manager.set_extension_enabled_immediate("omni.kit.asset_converter", True)

# Small delay to let it initialize
import time
time.sleep(1)

# Now continue with your existing code
from isaaclab.sim import SimulationContext, SimulationCfg, PhysxCfg

import omni.kit.app

# Initialize simulation context with proper physics configuration
# This is CRITICAL for wall stability - without proper solver iterations and timestep,
# the 24-layer brick wall will collapse during pre-settle phase
sim_cfg = SimulationCfg(
    dt=0.01,  # 100Hz physics timestep (increased for box collider stability)
    render_interval=1,  # Render every physics step (replaced deprecated 'substeps')
    gravity=(0.0, 0.0, -9.81),
    physx=PhysxCfg(
        solver_type=1,  # TGS (Temporal Gauss-Seidel) - more stable than PGS for tall stacks
        min_position_iteration_count=48,  # Increased for 200Hz (TGS loves position iters)
        max_position_iteration_count=64,
        min_velocity_iteration_count=12,
        max_velocity_iteration_count=24,
        enable_ccd=True,  # Continuous Collision Detection - prevents tunneling
        enable_stabilization=True,  # Additional stabilization for stacked objects
        bounce_threshold_velocity=0.05,
        friction_correlation_distance=0.02,
        # Increase GPU buffers for 24-layer wall (360 bricks = many contacts)
        gpu_max_rigid_contact_count=2**22,  # 4M contacts (was default ~500k)
        gpu_max_rigid_patch_count=2**19,     # 512K patches (was default ~80k)
        gpu_found_lost_pairs_capacity=2**21, # 2M pairs (was default ~256k)
        gpu_collision_stack_size=2**28       # 256MB stack (was default ~64MB)
    )
)

sim_context = SimulationContext(cfg=sim_cfg)
print("✅ Isaac Lab initialized with physics config:")
print(f"   • Timestep: {sim_cfg.dt}s (100Hz)")
print(f"   • Solver iterations: {sim_cfg.physx.min_position_iteration_count}-{sim_cfg.physx.max_position_iteration_count} position, {sim_cfg.physx.min_velocity_iteration_count}-{sim_cfg.physx.max_velocity_iteration_count} velocity")
print(f"   • CCD: {sim_cfg.physx.enable_ccd}, Stabilization: {sim_cfg.physx.enable_stabilization}")

# ============================================================================
# Configure Rendering Settings - Disable Blur, Keep Ray Tracing
# ============================================================================

import carb
settings = carb.settings.get_settings()

print("🎨 Configuring rendering settings...")

# Disable motion blur (causes blur during object motion)
settings.set("/rtx/post/motionblur/enable", False)
print("  ✓ Motion blur: DISABLED")

# Disable temporal anti-aliasing (causes blur with fast motion)
# 0=None, 1=FXAA, 2=TAA (temporal), 3=DLSS
settings.set("/rtx/post/aa/op", 0)
print("  ✓ Anti-aliasing: DISABLED (sharp rendering)")

# Keep ray tracing quality high
settings.set("/rtx/pathtracing/spp", 8)  # Samples per pixel
print("  ✓ Ray tracing: ENABLED (8 samples per pixel)")

print("✅ Rendering configured for sharp, blur-free output")

# ============================================================================
# STEP 2: Setup HTTP Server
# ============================================================================

from http.server import HTTPServer
import threading
from queue import Queue
from scan2wall.simulation.http_handlers import RequestHandler

# Create shared job queue and results dictionary
job_queue = Queue()
job_results = {}

# Inject queue and results into RequestHandler (class variables)
RequestHandler.job_queue = job_queue
RequestHandler.job_results = job_results


def run_http_server():
    """Run HTTP server in background thread."""
    server = HTTPServer(('127.0.0.1', 8090), RequestHandler)  # Bind to localhost only for security
    print("🌐 HTTP server started on localhost:8090 (not exposed to network)")
    server.serve_forever()


# Start HTTP server in daemon thread
http_thread = threading.Thread(target=run_http_server, daemon=True)
http_thread.start()

# ============================================================================
# STEP 3: Run Kit Main Loop
# ============================================================================

from scan2wall.simulation.kit_main_loop import (
    process_convert_job,
    process_create_base_scene_job,
    process_simulation_job
)

# Get Kit app interface
app_interface = omni.kit.app.get_app_interface()

# Camera state (persisted across simulations for efficiency)
camera_state = {
    'camera': None,
    'follow_camera': None,
    'watermark_tensor': None
}

# ============================================================================
# STEP 4: Generate fresh base scene on startup
# ============================================================================

import os
from scan2wall.simulation import scene_builder

base_scene_path = "/workspace/s2w-scripts/scenes/throw_against_brick_wall.usd"

# Remove old base scene file if it exists
if os.path.exists(base_scene_path):
    os.remove(base_scene_path)
    print(f"🗑️  Removed old base scene: {base_scene_path}")

# Create fresh base scene
print(f"🏗️  Creating fresh base scene...")
scene_builder.create_base_scene_usd(base_scene_path, sim_context)
print(f"✅ Fresh base scene created: {base_scene_path}")

print("✅ Kit main loop running")
print("   API: http://localhost:8090")
print("   Endpoints: /convert, /run_simulation, /create_base_scene")
print("   Ctrl+C to stop")

# ============================================================================
# Main Loop: Process jobs from queue
# ============================================================================

while app_interface.is_running():
    # Check for jobs in queue
    if not job_queue.empty():
        job_type, job_id, data = job_queue.get()

        # Delegate to appropriate handler
        if job_type == 'convert':
            process_convert_job(job_id, data, job_results)

        elif job_type == 'create_base_scene':
            process_create_base_scene_job(job_id, data, job_results, sim_context)

        elif job_type == 'simulate':
            process_simulation_job(job_id, data, job_results, sim_context, camera_state)

    # Step simulation (required for Kit to stay responsive)
    sim_context.step(render=False)

# ============================================================================
# Cleanup
# ============================================================================

simulation_app.close()
print("👋 Isaac Lab worker shut down")