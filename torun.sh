#!/bin/bash
set -e  # stop on first error

# --- Install Miniconda silently ---
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh
bash miniconda.sh -b -p $HOME/miniconda3
rm miniconda.sh

# --- Initialize Conda ---
$HOME/miniconda3/bin/conda init bash

# --- Accept TOS for Anaconda channels ---
$HOME/miniconda3/bin/conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
$HOME/miniconda3/bin/conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# --- Reload shell so Conda works immediately ---
source ~/.bashrc

# --- Create and activate comfyui environment ---
conda create -n comfyui python=3.10 -y
source $HOME/miniconda3/bin/activate comfyui

echo "✅ Miniconda installed and comfyui env active"

# --- Install core dependencies ---
cat > requirements.txt <<EOF
torch==2.4.0
torchvision==0.19.0
torchaudio==2.4.0
xformers==0.0.27.post2
numpy==2.1.3
pillow==11.0.0
tqdm==4.67.1
safetensors==0.4.5
transformers==4.46.3
diffusers==0.31.0
accelerate==1.10.1
huggingface-hub==0.25.2
einops==0.8.0
scipy==1.14.1
opencv-python==4.10.0.84
pandas==2.2.3
matplotlib==3.9.2
kornia==0.7.2
pymeshlab==2023.12
trimesh==4.4.9
open3d==0.19.0
rembg==2.0.57
EOF

pip install -r requirements.txt --upgrade --no-cache-dir

--- Install reqs for ComfyUI and custom nodes ---
cd ~/ComfyUI

# Install main ComfyUI requirements (if present)
if [ -f requirements.txt ]; then
  echo "📦 Installing ComfyUI core requirements..."
  pip install -r requirements.txt --upgrade --no-cache-dir
fi

# Loop through each subfolder in custom_nodes and install its requirements if present
echo "🔍 Scanning custom_nodes for dependencies..."
for d in custom_nodes/*/ ; do
  if [ -f "${d}requirements.txt" ]; then
    echo "📦 Installing requirements for ${d}..."
    pip install -r "${d}requirements.txt" --upgrade --no-cache-dir || true
  else
    echo "⚠️  No requirements.txt in ${d}, skipping."
  fi
done

find custom_nodes -maxdepth 1 -type d -exec touch {}/__init__.py \;

echo "🎨 All set! To run ComfyUI:"
echo "--------------------------------------------"
echo "conda activate comfyui"
echo "cd ~/ComfyUI"
echo "python main.py"
echo "--------------------------------------------"