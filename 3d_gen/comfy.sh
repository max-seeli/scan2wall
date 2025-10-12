#!/bin/bash
set -e  # stop on first error

#--- Install reqs for ComfyUI and custom nodes ---
git clone https://github.com/comfyanonymous/ComfyUI
BPATH="scan2wall/3d_gen"

cd $HOME/$BPATH/ComfyUI
pip install -r requirements.txt --upgrade --no-cache-dir

cd $HOME/$BPATH/ComfyUI/custom_nodes
git clone https://github.com/Comfy-Org/ComfyUI-Manager

cd $HOME/$BPATH/ComfyUI/custom_nodes/ComfyUI-Manager
pip install -r requirements.txt --upgrade --no-cache-dir

cd $HOME/$BPATH/ComfyUI/custom_nodes

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
pip install -r $HOME/$BPATH/ComfyUI/custom_nodes/ComfyUI-Hunyuan3d-2-1/requirements.txt
pip install -r $HOME/$BPATH/ComfyUI/custom_nodes/ComfyUI-Inspyrenet-Rembg/requirements.txt
pip install rembg[gpu]

cd $HOME/$BPATH/ComfyUI/custom_nodes/ComfyUI-Hunyuan3d-2-1/hy3dpaint/custom_rasterizer/
python -m setup install
cd $HOME/$BPATH/ComfyUI/custom_nodes/ComfyUI-Hunyuan3d-2-1/hy3dpaint/DifferentiableRenderer/
python -m setup install

cp -r $HOME/$BPATH/andrea-nodes $HOME/$BPATH/ComfyUI/custom_nodes/andrea-nodes
# cp -r $HOME/scan2wall/3d_gen/andrea-nodes $HOME/scan2wall/3d_gen/ComfyUI/custom_nodes/andrea-nodes

cp $HOME/$BPATH/optnodes/hunyan_opt_nodes.py $HOME/$BPATH/ComfyUI/custom_nodes/ComfyUI-Hunyuan3d-2-1/nodes.py
cp $HOME/$BPATH/optnodes/textureGenPipeline.py $HOME/$BPATH/ComfyUI/custom_nodes/ComfyUI-Hunyuan3d-2-1/hy3dpaint/textureGenPipeline.py
cp $HOME/$BPATH/optnodes/Inspyrenet_Rembg.py $HOME/$BPATH/ComfyUI/custom_nodes/ComfyUI-Inspyrenet-Rembg/Inspyrenet_Rembg.py

pip install transformers==4.46.3
pip install pynanoinstantmeshes

echo "🎨 All set! To run ComfyUI:"
echo "--------------------------------------------"
echo "conda activate comfyui"
echo "cd ~/ComfyUI"
echo "python main.py"
echo "--------------------------------------------"