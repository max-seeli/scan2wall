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

#--- Install reqs for ComfyUI and custom nodes ---
cd ~/ComfyUI
pip install -r requirements.txt --upgrade --no-cache-dir

cd custom_nodes
git clone https://github.com/Comfy-Org/ComfyUI-Manager

cd ComfyUI-Manager


echo "🎨 All set! To run ComfyUI:"
echo "--------------------------------------------"
echo "conda activate comfyui"
echo "cd ~/ComfyUI"
echo "python main.py"
echo "--------------------------------------------"