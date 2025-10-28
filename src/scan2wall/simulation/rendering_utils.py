"""
Rendering Utilities Module

Helper functions for color conversion, debugging, and watermark creation.
"""

import os
import numpy as np
import torch
from PIL import Image as PILImage, ImageDraw, ImageFont


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

    Returns:
        Dictionary with pixel statistics
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

    Args:
        width: Image width in pixels
        height: Image height in pixels
        device: PyTorch device to place tensor on

    Returns:
        torch.Tensor of shape (H, W, 3) with values 0-1 (float32)
    """
    # Create transparent image
    img = PILImage.new('RGBA', (width, height), (0, 0, 0, 0))
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
