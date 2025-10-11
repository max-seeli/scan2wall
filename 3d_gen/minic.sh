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

echo "✅ Miniconda installed!"

# --- Reload shell so Conda works immediately ---
source ~/.bashrc

# --- Create and activate comfyui environment ---
conda create -n comfyui python=3.10 -y
source $HOME/miniconda3/bin/activate comfyui