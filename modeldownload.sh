#!/bin/bash
set -e  # stop on first error

# Make sure you're in the comfyui environment
source $HOME/miniconda3/bin/activate comfyui

# Install comfy-cli if not already installed
pip install comfy-cli

# Download model (assuming ComfyUI is at ~/scan2wall/ComfyUI)
cd ~/scan2wall/ComfyUI
comfy --here model download --url https://huggingface.co/runwayml/stable-diffusion-v1-5/resolve/main/v1-5-pruned.safetensors --relative-path models/checkpoints