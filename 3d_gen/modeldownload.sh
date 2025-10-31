#!/bin/bash
set -e  # stop on first error

echo "📥 Downloading Hunyuan 3D 2.1 models..."
echo "========================================"

# Get the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Activate the uv virtual environment
if [ ! -d ".venv" ]; then
    echo "❌ Virtual environment not found. Please run setup_comfyui.sh first."
    exit 1
fi

source .venv/bin/activate

# Disable tracking prompt BEFORE installing comfy-cli
export COMFY_CLI_SKIP_PROMPT=1
export DO_NOT_TRACK=1

# Install comfy-cli if not already installed
echo "📦 Installing comfy-cli..."
uv pip install comfy-cli

# Navigate to ComfyUI directory
cd ComfyUI

# Download DIT model (auto-respond 'n' to tracking prompt)
echo "n" | comfy --here model download \
  --url "https://huggingface.co/tencent/Hunyuan3D-2.1/resolve/main/hunyuan3d-dit-v2-1/model.fp16.ckpt" \
  --relative-path models/diffusion_models \
  --filename hunyuan3d-dit-v2-1-fp16.ckpt

# Download VAE model
comfy --here model download \
  --url "https://huggingface.co/tencent/Hunyuan3D-2.1/resolve/main/hunyuan3d-vae-v2-1/model.fp16.ckpt" \
  --relative-path models/vae \
  --filename Hunyuan3D-vae-v2-1-fp16.ckpt

comfy --here model download \
  --url "https://huggingface.co/Kim2091/UltraSharpV2/resolve/main/4x-UltraSharpV2.safetensors" \
  --relative-path models/upscale_models \
  --filename 4x-UltraSharpV2.safetensors

# # Download Lumina VAE
# comfy --here model download \
#   --url "https://huggingface.co/Comfy-Org/Lumina_Image_2.0_Repackaged/resolve/main/split_files/vae/ae.safetensors" \
#   --relative-path models/vae \
#   --filename lumina_ae.safetensors

# # Download FLUX text encoders
# comfy --here model download \
#   --url "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors" \
#   --relative-path models/clip \
#   --filename clip_l.safetensors

# comfy --here model download \
#   --url "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn_scaled.safetensors" \
#   --relative-path models/clip \
#   --filename t5xxl_fp8_e4m3fn_scaled.safetensors

# # Download FLUX diffusion model
# comfy --here model download \
#   --url "https://huggingface.co/Comfy-Org/flux1-kontext-dev_ComfyUI/resolve/main/split_files/diffusion_models/flux1-dev-kontext_fp8_scaled.safetensors" \
#   --relative-path models/diffusion_models \
#   --filename flux1-dev-kontext_fp8_scaled.safetensors

echo ""
echo "✅ Model download complete!"
echo "Models installed to:"
echo "  - models/diffusion_models/hunyuan3d-dit-v2-1-fp16.ckpt"
echo "  - models/vae/Hunyuan3D-vae-v2-1-fp16.ckpt"
echo "  - models/upscale_models/4x-UltraSharpV2.safetensors"
echo "  - models/vae/lumina_ae.safetensors"
echo "  - models/clip/clip_l.safetensors"
echo "  - models/clip/t5xxl_fp8_e4m3fn_scaled.safetensors"
echo "  - models/diffusion_models/flux1-dev-kontext_fp8_scaled.safetensors"