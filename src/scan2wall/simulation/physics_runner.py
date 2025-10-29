"""
Physics Simulation Runner Module

Handles running physics simulations, capturing frames, and encoding videos.
"""

import os
import time
import subprocess
import shutil
import glob
import numpy as np
import torch
from PIL import Image as PILImage, ImageDraw, ImageFont
from pxr import Gf, UsdGeom
from isaaclab.sensors.camera import Camera, CameraCfg
import isaaclab.sim as sim_utils


def create_static_camera(camera_path: str = "/World/RenderCamera") -> Camera:
    """
    Create a static camera for rendering.

    Args:
        camera_path: USD path for camera prim

    Returns:
        Camera object
    """
    print("📷 Creating static camera")

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

    # Initialize the camera
    print("📷 Initializing static camera...")
    camera._initialize_callback(None)
    print("✅ Static camera created and initialized")

    return camera


def create_follow_camera(camera_path: str = "/World/FollowCamera") -> Camera:
    """
    Create a follow camera that tracks the object.

    Args:
        camera_path: USD path for camera prim

    Returns:
        Camera object
    """
    print("📷 Creating follow camera")

    follow_camera_cfg = CameraCfg(
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
            pos=(0.0, -3.0, 0.0),  # Centered on object, 3m back
            rot=(0.7071, 0.7071, 0.0, 0.0),  # +Y forward, +Z up (90° around X)
            convention="world"
        )
    )
    follow_camera = Camera(cfg=follow_camera_cfg)

    # Initialize the camera
    print("📷 Initializing follow camera...")
    follow_camera._initialize_callback(None)
    print("✅ Follow camera created and initialized")

    return follow_camera


def update_follow_camera_position(
    stage,
    obj_position: np.ndarray,
    camera_path: str = "/World/FollowCamera",
    obj_size: float = 1.0
) -> None:
    """
    Update follow camera position to track object at a distance proportional to its size.

    Args:
        stage: USD stage
        obj_position: Object position as numpy array (x, y, z)
        camera_path: USD path to camera prim
        obj_size: Characteristic size (max dimension) of object in meters
    """
    from pxr import Gf
    import math

    # Dynamically set follow distance and vertical offset
    follow_distance = max(0.5, 2.0 * obj_size)        # further for large objects
    height_offset = 0.3 * follow_distance              # raise camera a bit with size

    # Compute final camera position
    follow_offset = Gf.Vec3d(0.0, -follow_distance, height_offset)
    follow_pos = Gf.Vec3d(float(obj_position[0]), float(obj_position[1]), float(obj_position[2])) + follow_offset

    # Apply transform to camera prim
    follow_cam_prim = stage.GetPrimAtPath(camera_path)
    if follow_cam_prim.IsValid():
        xformable = UsdGeom.Xformable(follow_cam_prim)
        xformable.ClearXformOpOrder()
        xformable.AddTranslateOp().Set(follow_pos)
        
        look_down_deg = -10.0
        half_angle = math.radians(90 + look_down_deg) / 2
        q = Gf.Quatd(math.cos(half_angle), math.sin(half_angle), 0.0, 0.0)

        # Fixed orientation: look forward in +Y direction
        xformable.AddOrientOp(precision=UsdGeom.XformOp.PrecisionDouble).Set(q)


def apply_throwing_velocity(rigid_obj, dt: float, velocity: tuple = (0.0, 13.0, 6.0)) -> None:
    """
    Apply throwing velocity to rigid object.

    Args:
        rigid_obj: RigidObject to throw
        dt: Physics timestep
        velocity: (vx, vy, vz) linear velocity in m/s
    """
    print(f"🎯 Applying throwing velocity: {velocity}")

    # Update buffers first
    rigid_obj.update(dt)

    # Get current state (preserve orientation)
    root_state = rigid_obj.data.root_state_w.clone()

    # Set linear velocity
    root_state[:, 7:10] = torch.tensor(velocity, device=root_state.device)
    # Set angular velocity to ZERO (no spinning)
    root_state[:, 10:13] = torch.tensor([0.0, 0.0, 0.0], device=root_state.device)

    # Write velocity ONLY (don't change pose/orientation)
    rigid_obj.write_root_velocity_to_sim(root_state[:, 7:])
    print("✅ Velocity applied")


def add_watermark_to_frame(frame_rgb: np.ndarray) -> np.ndarray:
    """
    Add watermark to a single frame.

    Args:
        frame_rgb: Frame as numpy array (H, W, 3) uint8

    Returns:
        Frame with watermark
    """
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


def convert_frames_to_uint8(frames_gpu: list) -> tuple:
    """
    Convert GPU tensor frames to uint8 numpy arrays.

    Args:
        frames_gpu: List of GPU tensors (H, W, 3)

    Returns:
        Tuple of (frames_numpy, conversion_time)
    """
    print(f"📦 Converting {len(frames_gpu)} frames to uint8...")
    t_start = time.time()

    # Stack tensors
    frames_tensor = torch.stack(frames_gpu)  # (N, H, W, 3)

    # Handle uint8 vs float32 input
    if frames_tensor.dtype == torch.uint8:
        print("📊 Camera outputs uint8 - using directly")
        frames_uint8_gpu = frames_tensor
    else:
        print("📊 Camera outputs float32 - converting to uint8")
        frames_clamped = torch.clamp(frames_tensor, 0.0, 1.0)
        frames_uint8_gpu = (frames_clamped * 255.0).round().to(torch.uint8)

    # Transfer to CPU
    frames_numpy = frames_uint8_gpu.cpu().numpy()

    t_end = time.time()
    conversion_time = t_end - t_start
    print(f"✅ Conversion complete in {conversion_time:.2f}s")

    return frames_numpy, conversion_time


def ffmpeg_encode_from_memory(
    frames: np.ndarray,
    out_path: str,
    fps: int,
    skip_first: int = 0,
    width: int = 1280,
    height: int = 720,
    use_gpu: bool = True,
    job_id: str = None
) -> None:
    """
    Encode frames directly from memory by piping raw RGB data to ffmpeg.

    Args:
        frames: Numpy array of frames (N, H, W, 3) uint8
        out_path: Output MP4 file path
        fps: Frames per second
        skip_first: Number of initial frames to skip
        width: Frame width
        height: Frame height
        use_gpu: If True, use GPU encoding (NVENC)
        job_id: Job ID for watermark
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        print("[WARN] ffmpeg not found; cannot encode video.")
        return

    if len(frames) == 0 or len(frames) <= skip_first:
        print("[WARN] No frames to encode after skipping.")
        return

    # Skip first N frames
    frames_to_encode = frames[skip_first:]

    # Job ID watermark
    watermark_text = f"job: {job_id}" if job_id else "scan2wall"
    watermark_filter = (
        f"drawtext=text='{watermark_text}':"
        "fontsize=16:"
        "fontcolor=white@0.6:"
        "x=10:"
        "y=10:"
        "shadowcolor=black@0.8:"
        "shadowx=1:shadowy=1"
    )

    # Build FFmpeg command
    if use_gpu:
        # GPU encoding with NVENC - LUDICROUS MODE
        print("[INFO] Using GPU encoding (NVENC - p2 + ll)")
        cmd = [
            ffmpeg, "-y",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}",
            "-r", str(fps),
            "-i", "pipe:0",
            "-vf", watermark_filter,
            "-c:v", "h264_nvenc",
            "-preset", "p2",  # Fastest
            "-tune", "ll",    # Low-latency
            "-rc", "constqp",
            "-qp", "23",
            "-pix_fmt", "yuv420p",
            "-color_primaries", "bt709",
            "-color_trc", "iec61966-2-1",
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
            "-color_primaries", "bt709",
            "-color_trc", "iec61966-2-1",
            "-colorspace", "bt709",
            "-movflags", "+faststart",
            out_path
        ]

    # Start ffmpeg process
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        # Write each frame to ffmpeg stdin
        for frame in frames_to_encode:
            if not frame.flags['C_CONTIGUOUS']:
                frame = np.ascontiguousarray(frame)
            process.stdin.write(frame.tobytes())

        # Close stdin
        process.stdin.close()
        process.wait()

        if process.returncode == 0:
            print(f"[INFO] MP4 saved → {out_path}")
            # Fix permissions
            _fix_video_permissions(out_path)
        else:
            stderr_output = process.stderr.read().decode()
            print(f"[ERROR] ffmpeg encoding failed: {stderr_output}")
            # Retry with CPU if GPU failed
            if use_gpu:
                print("[WARN] GPU encoding failed, retrying with CPU...")
                return ffmpeg_encode_from_memory(frames, out_path, fps, skip_first, width, height, use_gpu=False, job_id=job_id)

    except Exception as e:
        print(f"[ERROR] Failed to encode video: {e}")
        if process.poll() is None:
            process.kill()
        if use_gpu:
            print("[WARN] Retrying with CPU encoding...")
            return ffmpeg_encode_from_memory(frames, out_path, fps, skip_first, width, height, use_gpu=False, job_id=job_id)
    finally:
        if process.stderr:
            process.stderr.close()


def _fix_video_permissions(video_path: str) -> None:
    """Fix video file permissions for host access."""
    import stat
    try:
        os.chmod(video_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
        parent_stat = os.stat(os.path.dirname(video_path))
        os.chown(video_path, parent_stat.st_uid, parent_stat.st_gid)
    except Exception as perm_err:
        print(f"[WARN] Could not fix video permissions: {perm_err}")


def throw_object(prim_path: str, direction: tuple = (1.0, 0.0, 1.0), speed: float = 8.0) -> np.ndarray:
    """
    Calculate throwing velocity vector.

    Args:
        prim_path: Path to object prim
        direction: Direction vector (x, y, z)
        speed: Speed in m/s

    Returns:
        Velocity vector as numpy array
    """
    d = np.array(direction, dtype=float)
    n = d / (np.linalg.norm(d) + 1e-8)
    v = n * float(speed)

    print(f"🎯 Will apply velocity to {prim_path}: {v}")
    return v
