#!/usr/bin/env python3
import sys

# Force all output to stderr (unbuffered)
sys.stdout = sys.stderr

#!/usr/bin/env python3
"""
Persistent Isaac Lab worker - Kit main loop with HTTP server

LUDICROUS MODE OPTIMIZATIONS:
- Camera resolution: 720p (1280×720) for faster rendering and encoding
- NVENC preset: p2 (fastest) with low-latency tune
- Watermark: Removed to eliminate CPU bottleneck
- Recommended FPS: 30 (instead of 50) for maximum speed
  Example: video_length=120, fps=30 → 4 seconds of video at 30 FPS
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

def linear_to_srgb_gpu(linear_rgb):
    """
    Convert linear RGB to sRGB using proper gamma correction (GPU-accelerated).

    Args:
        linear_rgb: torch.Tensor of shape (..., 3) with values in [0, 1] (linear RGB)

    Returns:
        torch.Tensor of same shape with sRGB gamma applied
    """
    # Clamp to valid range
    linear_rgb = torch.clamp(linear_rgb, 0.0, 1.0)

    # sRGB transfer function
    # For values <= 0.0031308: sRGB = 12.92 * linear
    # For values > 0.0031308: sRGB = 1.055 * linear^(1/2.4) - 0.055
    threshold = 0.0031308
    a = 0.055

    srgb = torch.where(
        linear_rgb <= threshold,
        12.92 * linear_rgb,
        (1 + a) * torch.pow(linear_rgb, 1.0 / 2.4) - a
    )

    return srgb

def srgb_to_linear_gpu(srgb):
    """
    Convert sRGB to linear RGB (inverse of linear_to_srgb_gpu).

    Args:
        srgb: torch.Tensor of shape (..., 3) with values in [0, 1] (sRGB gamma-corrected)

    Returns:
        torch.Tensor of same shape with linear RGB values
    """
    # Clamp to valid range
    srgb = torch.clamp(srgb, 0.0, 1.0)

    # Inverse sRGB transfer function
    # For values <= 0.04045: linear = sRGB / 12.92
    # For values > 0.04045: linear = ((sRGB + 0.055) / 1.055) ^ 2.4
    threshold = 0.04045
    a = 0.055

    linear = torch.where(
        srgb <= threshold,
        srgb / 12.92,
        torch.pow((srgb + a) / (1 + a), 2.4)
    )

    return linear

def inspect_pixel_values(rgb_tensor, label="Camera Output"):
    """
    Analyze pixel value distribution to determine colorspace.

    Linear RGB: Most values cluster in 0.0-0.3 range (darker)
    sRGB: Values spread more evenly across 0.0-1.0 range (brighter)

    Args:
        rgb_tensor: torch.Tensor of shape (H, W, 3) or (N, H, W, 3)
        label: String label for logging
    """
    if rgb_tensor.ndim == 4:
        rgb_tensor = rgb_tensor[0]  # Take first frame if batched

    # Convert to CPU for analysis
    rgb_np = rgb_tensor.cpu().numpy()

    # Calculate statistics
    min_val = rgb_np.min()
    max_val = rgb_np.max()
    mean_val = rgb_np.mean()
    median_val = np.median(rgb_np)

    # Calculate histogram bins
    hist, bins = np.histogram(rgb_np.flatten(), bins=10, range=(0.0, 1.0))

    # Calculate percentage in lower range (indicator of linear vs sRGB)
    low_range_pct = (rgb_np < 0.3).sum() / rgb_np.size * 100
    mid_range_pct = ((rgb_np >= 0.3) & (rgb_np < 0.7)).sum() / rgb_np.size * 100
    high_range_pct = (rgb_np >= 0.7).sum() / rgb_np.size * 100

    print(f"\n{'='*60}")
    print(f"🔍 Pixel Value Analysis: {label}")
    print(f"{'='*60}")
    print(f"  Min:    {min_val:.4f}")
    print(f"  Max:    {max_val:.4f}")
    print(f"  Mean:   {mean_val:.4f}")
    print(f"  Median: {median_val:.4f}")
    print(f"\n  Distribution:")
    print(f"    Low (0.0-0.3):   {low_range_pct:5.1f}%  {'█' * int(low_range_pct/5)}")
    print(f"    Mid (0.3-0.7):   {mid_range_pct:5.1f}%  {'█' * int(mid_range_pct/5)}")
    print(f"    High (0.7-1.0):  {high_range_pct:5.1f}%  {'█' * int(high_range_pct/5)}")
    print(f"\n  💡 Heuristic:")
    if low_range_pct > 60:
        print(f"     Likely LINEAR RGB (dark bias)")
    elif mid_range_pct > 40:
        print(f"     Likely sRGB (gamma-corrected, even distribution)")
    else:
        print(f"     Ambiguous - check visual comparison")
    print(f"{'='*60}\n")

    return {
        "min": min_val,
        "max": max_val,
        "mean": mean_val,
        "median": median_val,
        "low_pct": low_range_pct,
        "mid_pct": mid_range_pct,
        "high_pct": high_range_pct
    }

def save_color_comparison(rgb_tensor, out_dir, frame_idx=0):
    """
    Save the same frame with 4 different color treatments for comparison.

    Args:
        rgb_tensor: torch.Tensor of shape (H, W, 3) - raw camera output (0-1 float)
        out_dir: Directory to save comparison images
        frame_idx: Frame number for filename

    Saves:
        debug_a_raw.png - Just * 255 (original broken version)
        debug_b_lin2srgb.png - Linear→sRGB gamma correction (current "fix")
        debug_c_srgb2lin.png - sRGB→Linear (inverse operation)
        debug_d_gamma22.png - Simple power gamma 2.2
    """
    os.makedirs(out_dir, exist_ok=True)

    # Version A: Raw (just * 255) - what we had before
    raw = (rgb_tensor * 255.0).round().to(torch.uint8).cpu().numpy()
    PILImage.fromarray(raw, mode="RGB").save(os.path.join(out_dir, f"debug_{frame_idx:03d}_a_raw.png"))

    # Version B: Linear→sRGB (current "fix")
    lin2srgb = linear_to_srgb_gpu(rgb_tensor)
    lin2srgb_u8 = (lin2srgb * 255.0).round().to(torch.uint8).cpu().numpy()
    PILImage.fromarray(lin2srgb_u8, mode="RGB").save(os.path.join(out_dir, f"debug_{frame_idx:03d}_b_lin2srgb.png"))

    # Version C: sRGB→Linear (inverse)
    srgb2lin = srgb_to_linear_gpu(rgb_tensor)
    srgb2lin_u8 = (srgb2lin * 255.0).round().to(torch.uint8).cpu().numpy()
    PILImage.fromarray(srgb2lin_u8, mode="RGB").save(os.path.join(out_dir, f"debug_{frame_idx:03d}_c_srgb2lin.png"))

    # Version D: Simple power gamma 2.2 (old-school gamma correction)
    gamma22 = torch.pow(torch.clamp(rgb_tensor, 0.0, 1.0), 1.0 / 2.2)
    gamma22_u8 = (gamma22 * 255.0).round().to(torch.uint8).cpu().numpy()
    PILImage.fromarray(gamma22_u8, mode="RGB").save(os.path.join(out_dir, f"debug_{frame_idx:03d}_d_gamma22.png"))

    print(f"💾 Saved 4-way color comparison to {out_dir}/debug_{frame_idx:03d}_*.png")
    print(f"   A: Raw (* 255 only)")
    print(f"   B: Linear→sRGB (current fix)")
    print(f"   C: sRGB→Linear (inverse)")
    print(f"   D: Gamma 2.2 power curve")

def create_watermark_tensor(width, height, device='cuda:0'):
    """
    Create a watermark as a GPU tensor for fast overlay.
    Returns a tensor of shape (H, W, 3) with values 0-1 (float32).
    """
    from PIL import Image, ImageDraw, ImageFont

    # Create transparent image
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Text settings
    text = "scan2wall.com"
    font_size = max(24, int(height * 0.04))  # Scale with resolution

    try:
        # Try to use a nice font
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except:
        # Fallback to default
        font = ImageFont.load_default()

    # Get text size
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # Position: bottom-right corner with padding
    padding = 20
    x = width - text_width - padding
    y = height - text_height - padding

    # Draw shadow (black, slightly offset)
    shadow_offset = 2
    draw.text((x + shadow_offset, y + shadow_offset), text,
              fill=(0, 0, 0, 180), font=font)

    # Draw main text (white)
    draw.text((x, y), text, fill=(255, 255, 255, 230), font=font)

    # Convert RGBA to additive overlay
    img_array = np.array(img, dtype=np.float32) / 255.0  # Normalize to 0-1
    rgb = img_array[:, :, :3]  # RGB channels
    alpha = img_array[:, :, 3:4]  # Alpha channel

    # Create additive watermark: RGB weighted by alpha, scaled for subtlety
    # This creates a tensor that can simply be ADDED to frames
    watermark_overlay = rgb * alpha * 0.4  # 40% opacity, only where there's text

    watermark_tensor = torch.from_numpy(watermark_overlay).to(device)
    return watermark_tensor

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

def create_base_scene_usd(output_path="/workspace/s2w-scripts/scenes/throw_against_brick_wall.usd"):
    """
    Create and export a pre-built base scene USD file containing:
    - Ground plane with physics materials
    - Lighting setup (sky dome + 3-point lighting)
    - Wall structure

    This eliminates ~5 seconds of scene building per simulation.
    """
    print(f"🏗️  Creating base scene USD: {output_path}")

    # Get current stage
    stage = sim_context.stage

    # Clear existing scene elements (collect paths first to avoid iterator invalidation)
    world_prim = stage.GetPrimAtPath("/World")
    if world_prim.IsValid():
        child_paths = [child.GetPath() for child in world_prim.GetChildren()]
        for path in child_paths:
            if stage.GetPrimAtPath(path).IsValid():
                stage.RemovePrim(path)

    # Build ground plane
    cfg_ground = sim_utils.GroundPlaneCfg(
        color=(0.35, 0.35, 0.35),
        physics_material=sim_utils.RigidBodyMaterialCfg(
            static_friction=0.7,
            dynamic_friction=0.6
        )
    )
    cfg_ground.visual_material = sim_utils.PreviewSurfaceCfg(
        diffuse_color=(0.35, 0.35, 0.35),
        roughness=0.9,
        metallic=0.0
    )
    cfg_ground.func("/World/defaultGroundPlane", cfg_ground)

    # Add sky dome light (REDUCED from 2000 to fix overexposure)
    cfg_dome = sim_utils.DomeLightCfg(
        intensity=500.0,  # Was 2000
        color=(0.3, 0.6, 1.0)
    )
    cfg_dome.func("/World/skyDome", cfg_dome)

    # Add 3-point lighting (ALL REDUCED by 75% to fix overexposure)
    cfg_key = sim_utils.DistantLightCfg(intensity=500.0, color=(1.0, 0.95, 0.85))  # Was 2000
    cfg_key.func("/World/lightKey", cfg_key, translation=(-3, -2, 8))

    cfg_fill = sim_utils.DistantLightCfg(intensity=200.0, color=(0.9, 0.9, 1.0))  # Was 800
    cfg_fill.func("/World/lightFill", cfg_fill, translation=(3, -1, 5))

    cfg_rim = sim_utils.DistantLightCfg(intensity=150.0, color=(1.0, 1.0, 1.0))  # Was 600
    cfg_rim.func("/World/lightRim", cfg_rim, translation=(0, 5, 6))

    # Build wall structure
    build_wall("/World/StaticObjects/Wall", width=15, height=20,
               brick_width=0.3, brick_height=0.15, brick_depth=0.15,
               gap=0.0, base_xy=(0.0, 10.0), z0=0.075)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Export the stage to USD file
    print(f"💾 Exporting base scene to {output_path}...")
    stage.Export(output_path)
    print(f"✅ Base scene USD created: {output_path}")

    return output_path

def design_scene(usd_path_abs, scaling_factor=1.0, use_base_scene=True):
    """
    Load scene elements and dynamic object.

    Args:
        usd_path_abs: Path to the dynamic object USD file
        scaling_factor: Scale factor for the dynamic object
        use_base_scene: If True, load pre-built base scene USD (faster)
    """
    base_scene_path = "/workspace/s2w-scripts/scenes/throw_against_brick_wall.usd"

    # Try to use pre-built base scene for performance
    if use_base_scene and os.path.exists(base_scene_path):
        print(f"📦 Loading pre-built base scene from {base_scene_path}")
        stage = sim_context.stage

        # Load base scene as a sublayer (contains ground, lights, wall)
        root_layer = stage.GetRootLayer()
        if base_scene_path not in root_layer.subLayerPaths:
            root_layer.subLayerPaths.append(base_scene_path)
        print("✅ Base scene loaded")

    else:
        # Fallback: Build scene from scratch (old behavior)
        print("⚠️  Base scene not found, building from scratch...")

        # Textured ground plane (concrete/pavement look with roughness)
        cfg_ground = sim_utils.GroundPlaneCfg(
            color=(0.35, 0.35, 0.35),
            physics_material=sim_utils.RigidBodyMaterialCfg(
                static_friction=0.7,
                dynamic_friction=0.6
            )
        )
        cfg_ground.visual_material = sim_utils.PreviewSurfaceCfg(
            diffuse_color=(0.35, 0.35, 0.35),
            roughness=0.9,
            metallic=0.0
        )
        cfg_ground.func("/World/defaultGroundPlane", cfg_ground)

        # Add sky dome light (REDUCED from 2000 to fix overexposure)
        cfg_dome = sim_utils.DomeLightCfg(
            intensity=500.0,  # Was 2000
            color=(0.3, 0.6, 1.0)
        )
        cfg_dome.func("/World/skyDome", cfg_dome)

        # 3-point lighting (ALL REDUCED by 75% to fix overexposure)
        cfg_key = sim_utils.DistantLightCfg(intensity=500.0, color=(1.0, 0.95, 0.85))  # Was 2000
        cfg_key.func("/World/lightKey", cfg_key, translation=(-3, -2, 8))

        cfg_fill = sim_utils.DistantLightCfg(intensity=200.0, color=(0.9, 0.9, 1.0))  # Was 800
        cfg_fill.func("/World/lightFill", cfg_fill, translation=(3, -1, 5))

        cfg_rim = sim_utils.DistantLightCfg(intensity=150.0, color=(1.0, 1.0, 1.0))  # Was 600
        cfg_rim.func("/World/lightRim", cfg_rim, translation=(0, 5, 6))

        # Build wall (only if not using base scene)
        build_wall("/World/StaticObjects/Wall", width=15, height=20,
                   brick_width=0.3, brick_height=0.15, brick_depth=0.15,
                   gap=0.0, base_xy=(0.0, 10.0), z0=0.075)

    # Always load the dynamic object (this changes per simulation)
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
        # sRGB colorspace metadata (ensures correct color interpretation)
        "-color_primaries", "bt709",
        "-color_trc", "iec61966-2-1",  # sRGB transfer characteristic
        "-colorspace", "bt709",
        "-movflags", "+faststart", out_path
    ]
    subprocess.run(cmd, check=True)
    print(f"[INFO] MP4 with watermark saved → {out_path}")

def ffmpeg_encode_from_memory(frames, out_path, fps, skip_first=0, width=1280, height=720, use_gpu=True):
    """
    Encode frames directly from memory by piping raw RGB data to ffmpeg stdin.
    This eliminates the need for intermediate PNG files.

    Args:
        frames: List of numpy arrays (H, W, 3) uint8 RGB frames
        out_path: Output MP4 file path
        fps: Frames per second
        skip_first: Number of initial frames to skip
        width: Frame width
        height: Frame height
        use_gpu: If True, try GPU encoding (NVENC) first, fallback to CPU if unavailable
    """
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        print("[WARN] ffmpeg not found; cannot encode video.")
        return

    if len(frames) == 0 or len(frames) <= skip_first:
        print("[WARN] No frames to encode after skipping.")
        return

    # Skip first N frames
    frames_to_encode = frames[skip_first:]

    # Watermark filter (same as before)
    watermark_filter = (
        "drawtext=text='scan2wall.com':"
        "fontsize=32:"
        "fontcolor=white@0.8:"
        "x=w-tw-20:"
        "y=h-th-20:"
        "shadowcolor=black@0.6:"
        "shadowx=2:shadowy=2"
    )

    # Build FFmpeg command based on encoder type
    if use_gpu:
        # GPU encoding with NVENC - LUDICROUS MODE (p2 + low-latency)
        print("[INFO] Using GPU encoding (NVENC - LUDICROUS MODE: p2 + ll)")
        cmd = [
            ffmpeg, "-y",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}",
            "-r", str(fps),
            "-i", "pipe:0",
            # NO watermark filter - removes CPU bottleneck
            "-c:v", "h264_nvenc",       # NVIDIA GPU encoder
            "-preset", "p2",             # FASTEST preset (was p4)
            "-tune", "ll",               # Low-latency (disables B-frames, was hq)
            "-rc", "constqp",            # Constant QP (simpler than VBR)
            "-qp", "23",                 # Quality level
            "-pix_fmt", "yuv420p",
            # sRGB colorspace metadata (ensures correct color interpretation)
            "-color_primaries", "bt709",
            "-color_trc", "iec61966-2-1",  # sRGB transfer characteristic
            "-colorspace", "bt709",
            "-movflags", "+faststart",
            out_path
        ]
    else:
        # CPU encoding with libx264
        print("[INFO] Using CPU encoding (libx264)")
        cmd = [
            ffmpeg, "-y",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}",
            "-r", str(fps),
            "-i", "pipe:0",
            "-vf", watermark_filter,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            # sRGB colorspace metadata (ensures correct color interpretation)
            "-color_primaries", "bt709",
            "-color_trc", "iec61966-2-1",  # sRGB transfer characteristic
            "-colorspace", "bt709",
            "-movflags", "+faststart",
            out_path
        ]

    # Start ffmpeg process
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        # Write each frame to ffmpeg stdin
        for frame in frames_to_encode:
            # Ensure frame is contiguous in memory for efficient writing
            if not frame.flags['C_CONTIGUOUS']:
                frame = np.ascontiguousarray(frame)
            process.stdin.write(frame.tobytes())

        # Close stdin to signal end of input
        process.stdin.close()

        # Wait for ffmpeg to finish
        process.wait()

        if process.returncode == 0:
            print(f"[INFO] MP4 with watermark saved → {out_path}")
        else:
            stderr_output = process.stderr.read().decode()
            print(f"[ERROR] ffmpeg encoding failed: {stderr_output}")

            # If GPU encoding failed, retry with CPU
            if use_gpu:
                print("[WARN] GPU encoding failed, retrying with CPU encoding...")
                return ffmpeg_encode_from_memory(frames, out_path, fps, skip_first, width, height, use_gpu=False)

    except Exception as e:
        print(f"[ERROR] Failed to encode video: {e}")
        if process.poll() is None:
            process.kill()

        # If GPU encoding failed, retry with CPU
        if use_gpu:
            print("[WARN] GPU encoding failed, retrying with CPU encoding...")
            return ffmpeg_encode_from_memory(frames, out_path, fps, skip_first, width, height, use_gpu=False)
    finally:
        if process.stderr:
            process.stderr.close()

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
        elif self.path == '/create_base_scene':
            self._handle_create_base_scene()
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

    def _handle_create_base_scene(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b'{}'
        req = json.loads(body) if body else {}

        output_path = req.get('output_path', '/workspace/s2w-scripts/scenes/throw_against_brick_wall.usd')

        job_id = str(uuid.uuid4())
        print(f"🏗️  Queuing base scene creation: {output_path} (job: {job_id})")

        job_queue.put(('create_base_scene', job_id, {'output_path': output_path}))
        result = self._wait_for_result(job_id, timeout=60)

        if result["status"] == "completed":
            print(f"✅ Base scene created (job: {job_id})")
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        else:
            print(f"❌ Base scene creation failed (job: {job_id})")
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
print("   Endpoints: /convert, /run_simulation, /create_base_scene")
print("   Ctrl+C to stop")

camera = None
follow_camera = None
watermark_tensor = None  # GPU watermark overlay (additive)
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

        elif job_type == 'create_base_scene':
            print(f"⚙️  Processing base scene creation {job_id}...")
            try:
                output_path = data['output_path']
                result_path = create_base_scene_usd(output_path)
                job_results[job_id] = {
                    "status": "completed",
                    "output_path": result_path
                }
                print(f"✅ Base scene creation {job_id} done")
            except Exception as e:
                import traceback
                traceback.print_exc()
                job_results[job_id] = {"status": "failed", "error": str(e)}
                print(f"❌ Base scene creation {job_id} failed: {e}")

        elif job_type == 'simulate':
            print(f"⚙️  Processing simulation {job_id}...")
            try:
                
                # Start timing
                sim_start_time = time.time()

                # Initialize timing trackers
                timing_cleanup_start = sim_start_time

                # Extract params
                usd_path = data['usd_path']
                out_dir = data.get('out_dir', '/workspace/s2w-data/recordings')
                video = data.get('video', True)
                video_length = data.get('video_length', 200)
                fps = data.get('fps', 50)
                scaling_factor = data.get('scaling_factor', 1.0)
                skip_first = data.get('skip_first', 10)
                request_job_id = data.get('job_id', 'unknown')  # Get job_id from request
                color_debug_mode = data.get('color_debug_mode', False)  # Enable color diagnostics

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

                # Remove base scene sublayer if present (so it can be re-added cleanly)
                base_scene_path = "/workspace/s2w-scripts/scenes/throw_against_brick_wall.usd"
                root_layer = stage.GetRootLayer()
                if base_scene_path in root_layer.subLayerPaths:
                    root_layer.subLayerPaths.remove(base_scene_path)
                    print("🗑️  Removed base scene sublayer for clean reload")

                # Reset physics to clear cached state
                sim_context.reset()

                sim_context.step()
                app_interface.update()
                print("✅ Cleanup done")

                timing_cleanup_end = time.time()
                timing_camera_start = timing_cleanup_end

                # === CREATE OR REUSE CAMERAS ===
                if camera is None:
                    print("📷 Creating static camera (first time)")
                    from isaaclab.sensors.camera import Camera, CameraCfg

                    camera_cfg = CameraCfg(
                        prim_path=camera_path,
                        update_period=0,
                        height=720,
                        width=1280,
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
                        height=720,
                        width=1280,
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

                # Create GPU watermark tensor (once, cached globally)
                if watermark_tensor is None:
                    print("🎨 Creating GPU watermark tensor...")
                    watermark_tensor = create_watermark_tensor(1280, 720, device='cuda:0')
                    print("✅ GPU watermark ready (zero encoding overhead!)")

                timing_camera_end = time.time()
                timing_scene_start = timing_camera_end

                # BUILD SCENE
                print("🏗️  Loading scene...")
                # design_scene now loads pre-built base scene (ground, lights, wall)
                # and only adds the dynamic object
                design_scene(usd_path, scaling_factor)

                timing_scene_end = time.time()
                timing_physics_init_start = timing_scene_end

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

                # Ensure output directory exists
                os.makedirs(out_dir, exist_ok=True)

                # Initialize frame storage lists (keep on GPU during simulation!)
                frames_static_gpu = []  # Store GPU tensors
                frames_follow_gpu = []  # Store GPU tensors

                # Initialize debug data storage
                pixel_stats = None  # Will store pixel statistics if debug mode enabled
                debug_info = {}  # Will store all debug information for JSON response

                steps = max(1, video_length)
                captured = 0
                velocity_applied = False
                pause_frames = 50  # 1 second pause at 50 FPS

                timing_physics_init_end = time.time()
                timing_loop_start = timing_physics_init_end

                # Initialize loop timing accumulators
                timing_physics_step_total = 0.0
                timing_camera_render_total = 0.0
                timing_gpu_transfer_total = 0.0
                timing_transform_update_total = 0.0
                # Note: No more image_io timing - we store frames in memory!

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

                    # Time physics step
                    t_physics_start = time.time()
                    sim_context.step()
                    timing_physics_step_total += time.time() - t_physics_start

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
                        t_transform_start = time.time()
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
                        timing_transform_update_total += time.time() - t_transform_start

                        # === CAPTURE FROM STATIC CAMERA ===
                        t_camera_start = time.time()
                        camera.update(dt)
                        timing_camera_render_total += time.time() - t_camera_start
                        rgb_data_static = camera.data.output["rgb"]

                        # Capture debug info (first frame only)
                        if captured == 0 and color_debug_mode:
                            # Convert to float if uint8 for mean calculation
                            data_for_stats = rgb_data_static.float() if rgb_data_static.dtype == torch.uint8 else rgb_data_static
                            debug_info["raw_camera_frame0"] = {
                                "dtype": str(rgb_data_static.dtype),
                                "device": str(rgb_data_static.device),
                                "shape": list(rgb_data_static.shape),
                                "min": float(rgb_data_static.min().item()),
                                "max": float(rgb_data_static.max().item()),
                                "mean": float(data_for_stats.mean().item())
                            }

                        # Keep on GPU - just extract first batch element if needed
                        if rgb_data_static.ndim == 4:
                            rgb_data_static = rgb_data_static[0]  # Shape: (H, W, 3)
                            if captured == 0 and color_debug_mode:
                                debug_info["raw_camera_frame0"]["shape_after_squeeze"] = list(rgb_data_static.shape)

                        # === COLOR DEBUG MODE (analyze first frame after throw) ===
                        if color_debug_mode and captured == pause_frames:
                            print("\n" + "="*80)
                            print("🔬 COLOR DEBUG MODE ENABLED")
                            print("="*80)

                            # Inspect raw pixel values and capture stats
                            pixel_stats = inspect_pixel_values(rgb_data_static, label="Raw Camera Output (Static)")

                            # Save 4-way comparison
                            debug_dir = os.path.join(out_dir, "color_debug")
                            save_color_comparison(rgb_data_static, debug_dir, frame_idx=captured)

                            print("\n💡 Visual Inspection Guide:")
                            print("   - If A (raw) looks best: Camera outputs sRGB, remove gamma correction")
                            print("   - If B (lin2srgb) looks best: Camera outputs linear, keep current fix")
                            print("   - If C (srgb2lin) looks best: Camera outputs sRGB, need inverse")
                            print("   - If D (gamma22) looks best: Use simple power curve instead")
                            print("="*80 + "\n")

                        # Store GPU tensor WITHOUT watermark (add it after batch transfer on CPU)
                        frames_static_gpu.append(rgb_data_static.clone())

                        # === CAPTURE FROM FOLLOW CAMERA ===
                        t_camera_start = time.time()
                        follow_camera.update(dt)
                        timing_camera_render_total += time.time() - t_camera_start
                        rgb_data_follow = follow_camera.data.output["rgb"]

                        # Keep on GPU - just extract first batch element if needed
                        if rgb_data_follow.ndim == 4:
                            rgb_data_follow = rgb_data_follow[0]  # Shape: (H, W, 3)

                        # Store GPU tensor WITHOUT watermark (add it after batch transfer on CPU)
                        frames_follow_gpu.append(rgb_data_follow.clone())

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
                
                # Mark end of simulation loop
                timing_loop_end = time.time()

                # Batch transfer frames from GPU to CPU (much faster than per-frame)
                print(f"📦 Batch transferring {len(frames_static_gpu)} frames from GPU to CPU...")
                t_batch_transfer_start = time.time()

                # Stack tensors and convert to uint8 on GPU
                import torch
                frames_static_tensor = torch.stack(frames_static_gpu)  # (N, H, W, 3)
                frames_follow_tensor = torch.stack(frames_follow_gpu)  # (N, H, W, 3)

                # Capture stacked tensor debug info (handle uint8 for mean)
                if color_debug_mode:
                    data_for_mean = frames_static_tensor.float() if frames_static_tensor.dtype == torch.uint8 else frames_static_tensor
                    debug_info["stacked_tensor"] = {
                        "shape": list(frames_static_tensor.shape),
                        "dtype": str(frames_static_tensor.dtype),
                        "min": float(frames_static_tensor.min().item()),
                        "max": float(frames_static_tensor.max().item()),
                        "mean": float(data_for_mean.mean().item())
                    }

                # Handle uint8 vs float32 input
                if frames_static_tensor.dtype == torch.uint8:
                    # Camera already outputs uint8 - use directly!
                    print("📊 Camera outputs uint8 - using directly (no conversion needed)")
                    frames_static_uint8_gpu = frames_static_tensor
                    frames_follow_uint8_gpu = frames_follow_tensor
                else:
                    # Camera outputs float32 - convert to uint8
                    print("📊 Camera outputs float32 - converting to uint8")
                    frames_static_clamped = torch.clamp(frames_static_tensor, 0.0, 1.0)
                    frames_follow_clamped = torch.clamp(frames_follow_tensor, 0.0, 1.0)
                    frames_static_uint8_gpu = (frames_static_clamped * 255.0).round().to(torch.uint8)
                    frames_follow_uint8_gpu = (frames_follow_clamped * 255.0).round().to(torch.uint8)

                # Capture final uint8 stats
                if color_debug_mode:
                    debug_info["final_uint8"] = {
                        "min": int(frames_static_uint8_gpu.min().item()),
                        "max": int(frames_static_uint8_gpu.max().item()),
                        "mean": float(frames_static_uint8_gpu.float().mean().item())
                    }

                # Single batched transfer to CPU
                frames_static = frames_static_uint8_gpu.cpu().numpy()
                frames_follow = frames_follow_uint8_gpu.cpu().numpy()

                t_batch_transfer_end = time.time()
                batch_transfer_time = t_batch_transfer_end - t_batch_transfer_start
                print(f"✅ Batch transfer complete in {batch_transfer_time:.2f}s")

                # Add watermark on CPU (PIL-based, proven to work)
                print("🎨 Adding watermark to frames...")
                from PIL import Image, ImageDraw, ImageFont

                def add_watermark_to_frame(frame_rgb):
                    """Add watermark to a single frame (numpy array H×W×3 uint8)"""
                    img = PILImage.fromarray(frame_rgb)
                    draw = ImageDraw.Draw(img)
                    text = "scan2wall.com"
                    try:
                        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
                    except:
                        font = ImageFont.load_default()

                    bbox = draw.textbbox((0, 0), text, font=font)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]

                    x = img.width - text_width - 20
                    y = img.height - text_height - 20

                    # Shadow
                    draw.text((x+2, y+2), text, fill=(0, 0, 0, 200), font=font)
                    # Main text
                    draw.text((x, y), text, fill=(255, 255, 255, 230), font=font)

                    return np.array(img)

                # Apply watermark to all frames
                for i in range(len(frames_static)):
                    frames_static[i] = add_watermark_to_frame(frames_static[i])
                    frames_follow[i] = add_watermark_to_frame(frames_follow[i])

                print("✅ Watermark added to all frames")

                # Clear GPU tensors to free VRAM
                frames_static_gpu.clear()
                frames_follow_gpu.clear()
                del frames_static_tensor, frames_follow_tensor, frames_static_uint8_gpu, frames_follow_uint8_gpu

                encoding_start_time = time.time()
                encoding_static_time = 0
                encoding_follow_time = 0
                if video:
                    print(f"🎥 Encoding videos from memory ({len(frames_static)} frames)...")

                    # Encode both videos in parallel using ThreadPoolExecutor
                    from concurrent.futures import ThreadPoolExecutor, as_completed

                    video_filename_static = f"{request_job_id}_static.mp4"
                    out_mp4_static = os.path.join(out_dir, video_filename_static)

                    video_filename_follow = f"{request_job_id}_follow.mp4"
                    out_mp4_follow = os.path.join(out_dir, video_filename_follow)

                    def encode_video(frames, out_path, camera_name):
                        """Encode a single video and return timing info"""
                        start = time.time()
                        print(f"   Encoding {camera_name} camera view...")
                        ffmpeg_encode_from_memory(frames, out_path, fps, skip_first)
                        elapsed = time.time() - start
                        print(f"   ✅ {camera_name} camera encoded in {elapsed:.2f}s")
                        return camera_name, elapsed

                    # Submit both encoding tasks to run in parallel
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        future_static = executor.submit(encode_video, frames_static, out_mp4_static, "static")
                        future_follow = executor.submit(encode_video, frames_follow, out_mp4_follow, "follow")

                        # Wait for both to complete and collect timing
                        for future in as_completed([future_static, future_follow]):
                            camera_name, elapsed = future.result()
                            if camera_name == "static":
                                encoding_static_time = elapsed
                            else:
                                encoding_follow_time = elapsed

                    # Clear frames from memory to free RAM (NumPy arrays - delete references)
                    del frames_static, frames_follow

                encoding_end_time = time.time()
                encoding_time = encoding_end_time - encoding_start_time
                total_time = encoding_end_time - sim_start_time

                # Calculate timing breakdown
                cleanup_time = timing_cleanup_end - timing_cleanup_start
                camera_setup_time = timing_camera_end - timing_camera_start
                scene_building_time = timing_scene_end - timing_scene_start
                physics_init_time = timing_physics_init_end - timing_physics_init_start
                setup_total_time = timing_loop_start - sim_start_time
                simulation_loop_time = timing_loop_end - timing_loop_start
                simulation_total_time = timing_loop_end - sim_start_time

                # Calculate performance metrics
                fps_achieved = captured / simulation_loop_time if simulation_loop_time > 0 else 0
                avg_frame_time_ms = (simulation_loop_time * 1000) / captured if captured > 0 else 0

                # Build result dict
                result = {
                    "status": "completed",
                    "frames": captured,
                    "output": out_dir,
                    "video_path_static": out_mp4_static,
                    "video_path_follow": out_mp4_follow,
                    "timing": {
                        # Setup breakdown
                        "cleanup_seconds": round(cleanup_time, 2),
                        "camera_setup_seconds": round(camera_setup_time, 2),
                        "scene_building_seconds": round(scene_building_time, 2),
                        "physics_init_seconds": round(physics_init_time, 2),
                        "setup_total_seconds": round(setup_total_time, 2),

                        # Simulation loop breakdown (accumulated over all frames)
                        "physics_step_seconds": round(timing_physics_step_total, 2),
                        "camera_render_seconds": round(timing_camera_render_total, 2),
                        "transform_update_seconds": round(timing_transform_update_total, 2),
                        "simulation_loop_seconds": round(simulation_loop_time, 2),
                        # Note: Frames kept on GPU during loop, batch transferred after

                        # Batch GPU→CPU transfer (after simulation loop)
                        "batch_gpu_transfer_seconds": round(batch_transfer_time, 2),

                        # Encoding (parallel execution)
                        "encoding_seconds": round(encoding_time, 2),
                        "encoding_static_seconds": round(encoding_static_time, 2),
                        "encoding_follow_seconds": round(encoding_follow_time, 2),

                        # Totals
                        "simulation_total_seconds": round(simulation_total_time, 2),
                        "total_seconds": round(total_time, 2),

                        # Performance metrics
                        "fps_achieved": round(fps_achieved, 1),
                        "avg_frame_time_ms": round(avg_frame_time_ms, 1)
                    }
                }

                # Add pixel statistics if debug mode was enabled
                if pixel_stats is not None:
                    result["pixel_statistics"] = {
                        "min": float(pixel_stats["min"]),
                        "max": float(pixel_stats["max"]),
                        "mean": float(pixel_stats["mean"]),
                        "median": float(pixel_stats["median"]),
                        "distribution": {
                            "low_0_to_0.3_percent": round(pixel_stats["low_pct"], 1),
                            "mid_0.3_to_0.7_percent": round(pixel_stats["mid_pct"], 1),
                            "high_0.7_to_1.0_percent": round(pixel_stats["high_pct"], 1)
                        },
                        "interpretation": "Linear RGB" if pixel_stats["low_pct"] > 60 else ("sRGB" if pixel_stats["mid_pct"] > 40 else "Ambiguous")
                    }
                    result["debug_images_dir"] = os.path.join(out_dir, "color_debug")

                # Add debug info if debug mode was enabled
                if debug_info:
                    result["debug_data"] = debug_info

                job_results[job_id] = result
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