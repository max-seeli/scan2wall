# #!/bin/bash
# set -e  # stop on first error

# #--- Install reqs for ComfyUI and custom nodes ---
# git clone https://github.com/comfyanonymous/ComfyUI

# cd $HOME/scan2wall/ComfyUI
# pip install -r requirements.txt --upgrade --no-cache-dir

cd $HOME/scan2wall/ComfyUI/custom_nodes
git clone https://github.com/Comfy-Org/ComfyUI-Manager

cd $HOME/scan2wall/ComfyUI/custom_nodes/ComfyUI-Manager
pip install -r requirements.txt --upgrade --no-cache-dir

cd $HOME/scan2wall/ComfyUI/custom_nodes

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

# --- Install dependencies for all custom nodes ---
python $HOME/scan2wall/ComfyUI/custom_nodes/ComfyUI-Manager/cm-cli.py install-deps

echo "🎨 All set! To run ComfyUI:"
echo "--------------------------------------------"
echo "conda activate comfyui"
echo "cd ~/ComfyUI"
echo "python main.py"
echo "--------------------------------------------"