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

# Download DIT model
comfy --here model download \
  --url "https://huggingface.co/tencent/Hunyuan3D-2.1/resolve/main/hunyuan3d-dit-v2-1/model.fp16.ckpt" \
  --relative-path models/diffusion_models \
  --filename hunyuan3d-dit-v2-1-fp16.ckpt

# Download VAE model
comfy --here model download \
  --url "https://huggingface.co/tencent/Hunyuan3D-2.1/resolve/main/hunyuan3d-vae-v2-1/model.fp16.ckpt" \
  --relative-path models/vae \
  --filename Hunyuan3D-vae-v2-1-fp16.ckpt

comfy --here model download \
  --url "https://huggingface.co/lokCX/4x-Ultrasharp/blob/main/4x-UltraSharp.pth" \
  --relative-path models/upscale_models \
  --filename 4x-UltraSharp.pth

echo ""
echo "✅ Model download complete!"
echo "Models installed to:"
echo "  - models/diffusion_models/hunyuan3d-dit-v2-1-fp16.ckpt"
echo "  - models/vae/Hunyuan3D-vae-v2-1-fp16.ckpt"