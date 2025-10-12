#!/bin/bash
set -e  # Stop on first error

echo "🚀 Setting up ComfyUI with uv (fast Python package manager)"
echo "=========================================================="

# Get the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "❌ uv is not installed. Installing now..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

echo "✅ uv found: $(uv --version)"

# Create virtual environment with Python 3.10
echo ""
echo "📦 Creating Python 3.10 virtual environment..."
if [ -d ".venv" ]; then
    echo "⚠️  .venv already exists, skipping creation"
else
    uv venv --python 3.10
fi

# Activate the virtual environment
source .venv/bin/activate

echo ""
echo "📥 Cloning ComfyUI repository..."
if [ -d "ComfyUI" ]; then
    echo "⚠️  ComfyUI directory already exists, skipping clone"
    cd ComfyUI
else
    git clone https://github.com/comfyanonymous/ComfyUI
    cd ComfyUI
fi

echo ""
echo "📦 Installing ComfyUI dependencies..."
uv pip install -r requirements.txt

echo ""
echo "📦 Installing ComfyUI-Manager..."
cd custom_nodes
if [ -d "ComfyUI-Manager" ]; then
    echo "⚠️  ComfyUI-Manager already exists, skipping clone"
else
    git clone https://github.com/Comfy-Org/ComfyUI-Manager
fi
cd ComfyUI-Manager
uv pip install -r requirements.txt

echo ""
echo "📦 Installing custom nodes..."
cd ../

# Array of custom node repositories
CUSTOM_NODES=(
    "https://github.com/Suzie1/ComfyUI_Comfyroll_CustomNodes"
    "https://github.com/kijai/ComfyUI-KJNodes"
    "https://github.com/visualbruno/ComfyUI-Hunyuan3d-2-1"
    "https://github.com/john-mnz/ComfyUI-Inspyrenet-Rembg"
    "https://github.com/chflame163/ComfyUI_LayerStyle"
    "https://github.com/huagetai/ComfyUI_LightGradient"
)

for repo in "${CUSTOM_NODES[@]}"; do
    repo_name=$(basename "$repo")
    if [ -d "$repo_name" ]; then
        echo "⚠️  $repo_name already exists, skipping"
    else
        echo "📥 Cloning $repo_name..."
        git clone "$repo"
    fi
done

echo ""
echo "📦 Installing custom node dependencies..."

# Hunyuan3D dependencies
if [ -f "ComfyUI-Hunyuan3d-2-1/requirements.txt" ]; then
    echo "Installing ComfyUI-Hunyuan3d-2-1 requirements..."
    uv pip install -r ComfyUI-Hunyuan3d-2-1/requirements.txt
fi

# Inspyrenet-Rembg dependencies
if [ -f "ComfyUI-Inspyrenet-Rembg/requirements.txt" ]; then
    echo "Installing ComfyUI-Inspyrenet-Rembg requirements..."
    uv pip install -r ComfyUI-Inspyrenet-Rembg/requirements.txt
fi

echo "Installing rembg with GPU support..."
uv pip install "rembg[gpu]"

# LayerStyle dependencies
if [ -f "ComfyUI_LayerStyle/requirements.txt" ]; then
    echo "Installing ComfyUI_LayerStyle requirements..."
    uv pip install -r ComfyUI_LayerStyle/requirements.txt
fi

echo ""
echo "🔧 Building custom rasterizer extensions..."
# Build Hunyuan3D custom rasterizer
if [ -d "ComfyUI-Hunyuan3d-2-1/hy3dpaint/custom_rasterizer" ]; then
    cd ComfyUI-Hunyuan3d-2-1/hy3dpaint/custom_rasterizer/
    python -m setup install
    cd ../../..
fi

# Build DifferentiableRenderer
if [ -d "ComfyUI-Hunyuan3d-2-1/hy3dpaint/DifferentiableRenderer" ]; then
    cd ComfyUI-Hunyuan3d-2-1/hy3dpaint/DifferentiableRenderer/
    python -m setup install
    cd ../../..
fi

echo ""
echo "📋 Copying custom node configurations..."
cd "$SCRIPT_DIR"

# Copy andrea-nodes
if [ -d "andrea-nodes" ]; then
    cp -r andrea-nodes ComfyUI/custom_nodes/andrea-nodes
    echo "✅ Copied andrea-nodes"
fi

# Copy optimized node files
if [ -f "optnodes/hunyan_opt_nodes.py" ]; then
    cp optnodes/hunyan_opt_nodes.py ComfyUI/custom_nodes/ComfyUI-Hunyuan3d-2-1/nodes.py
    echo "✅ Copied hunyan_opt_nodes.py"
fi

if [ -f "optnodes/textureGenPipeline.py" ]; then
    cp optnodes/textureGenPipeline.py ComfyUI/custom_nodes/ComfyUI-Hunyuan3d-2-1/hy3dpaint/textureGenPipeline.py
    echo "✅ Copied textureGenPipeline.py"
fi

if [ -f "optnodes/Inspyrenet_Rembg.py" ]; then
    cp optnodes/Inspyrenet_Rembg.py ComfyUI/custom_nodes/ComfyUI-Inspyrenet-Rembg/Inspyrenet_Rembg.py
    echo "✅ Copied Inspyrenet_Rembg.py"
fi

echo ""
echo "📦 Installing final dependencies..."
uv pip install transformers==4.46.3
uv pip install pynanoinstantmeshes
uv pip install fastapi python-multipart uvicorn
echo ""
echo "✅ ComfyUI setup complete!"
echo "=========================================================="
echo ""
echo "Next steps:"
echo "1. Activate the environment:"
echo "   cd 3d_gen && source .venv/bin/activate"
echo ""
echo "2. Download models:"
echo "   bash modeldownload.sh"
echo ""
echo "3. Start ComfyUI:"
echo "   cd ComfyUI && python main.py --listen 0.0.0.0 --port 8188"
echo ""
echo "4. Start the API server (in another terminal):"
echo "   cd 3d_gen && source .venv/bin/activate && python server.py"
echo ""
