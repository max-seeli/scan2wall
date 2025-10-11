#!/bin/bash
set -e  # stop on first error

#--- Install reqs for ComfyUI and custom nodes ---
git clone https://github.com/comfyanonymous/ComfyUI

cd $HOME/scan2wall/3d_gen/ComfyUI
pip install -r requirements.txt --upgrade --no-cache-dir

cd $HOME/scan2wall/ComfyUI/custom_nodes
git clone https://github.com/Comfy-Org/ComfyUI-Manager

cd $HOME/scan2wall/3d_gen/ComfyUI/custom_nodes/ComfyUI-Manager
pip install -r requirements.txt --upgrade --no-cache-dir

cd $HOME/scan2wall/3d_gen/ComfyUI/custom_nodes

# --- Install custom nodes from git URLs ---
CUSTOM_NODES=(
    "https://github.com/Suzie1/ComfyUI_Comfyroll_CustomNodes"
    "https://github.com/kijai/ComfyUI-KJNodes"
    "https://github.com/visualbruno/ComfyUI-Hunyuan3d-2-1"
    "https://github.com/john-mnz/ComfyUI-Inspyrenet-Rembg"
    # Add more URLs here
)

echo "📦 Installing custom nodes..."
for repo in "${CUSTOM_NODES[@]}"; do
    echo "Cloning $repo"
    git clone "$repo"
done

--- Install dependencies for all custom nodes ---
pip install -r $HOME/scan2wall/3d_gen/ComfyUI/custom_nodes/ComfyUI-Hunyuan3d-2-1/requirements.txt
pip install -r $HOME/scan2wall/3d_gen/ComfyUI/custom_nodes/ComfyUI-Inspyrenet-Rembg/requirements.txt
pip install rembg[gpu]

cd $HOME/scan2wall/3d_gen/ComfyUI/custom_nodes/ComfyUI-Hunyuan3d-2-1/hy3dpaint/custom_rasterizer/
python -m setup install
cd $HOME/scan2wall/3d_gen/ComfyUI/custom_nodes/ComfyUI-Hunyuan3d-2-1/hy3dpaint/DifferentiableRenderer/
python -m setup install

cp -r $HOME/scan2wall/3d_gen/andrea-nodes $HOME/scan2wall/3d_gen/ComfyUI/custom_nodes/andrea-nodes

pip install transformers==4.46.3

echo "🎨 All set! To run ComfyUI:"
echo "--------------------------------------------"
echo "conda activate comfyui"
echo "cd ~/ComfyUI"
echo "python main.py"
echo "--------------------------------------------"