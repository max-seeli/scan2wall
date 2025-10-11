set -e  # stop on first error

# Make sure you're in the comfyui environment
source $HOME/miniconda3/bin/activate comfyui

# Install comfy-cli if not already installed
pip install comfy-cli

# Disable tracking prompt
export COMFY_CLI_SKIP_PROMPT=1

# Download models (assuming ComfyUI is at ~/scan2wall/ComfyUI)
cd $HOME/scan2wall/ComfyUI

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