#!/bin/bash
set -e  # Stop on first error

echo "🚀 Setting up ComfyUI with uv (fast Python package manager)"
echo "=========================================================="

# Navigate to 3d_gen directory (where ComfyUI should be installed)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
THREEGEN_DIR="$PROJECT_ROOT/3d_gen"

echo "Installing ComfyUI in: $THREEGEN_DIR"
cd "$THREEGEN_DIR"

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
    "https://github.com/chflame163/ComfyUI_LayerStyle"
    "https://github.com/huagetai/ComfyUI_LightGradient"
    "https://github.com/PozzettiAndrea/ComfyUI-MeshCraft"
    "https://github.com/kijai/ComfyUI-Florence2"
    "https://github.com/neverbiasu/ComfyUI-SAM2"
    "https://github.com/rgthree/rgthree-comfy"
    "https://github.com/kijai/ComfyUI-segment-anything-2"
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

# MeshCraft dependencies
if [ -f "ComfyUI-MeshCraft/requirements.txt" ]; then
    echo "Installing ComfyUI-MeshCraft requirements..."
    uv pip install -r ComfyUI-MeshCraft/requirements.txt
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
# Build MeshCraft custom rasterizer
if [ -d "ComfyUI-MeshCraft/hy3dpaint/custom_rasterizer" ]; then
    cd ComfyUI-MeshCraft/hy3dpaint/custom_rasterizer/
    python -m setup install
    cd ../../..
fi

# Build MeshCraft DifferentiableRenderer
if [ -d "ComfyUI-MeshCraft/hy3dpaint/DifferentiableRenderer" ]; then
    cd ComfyUI-MeshCraft/hy3dpaint/DifferentiableRenderer/
    python -m setup install
    cd ../../..
fi

echo ""
echo "📋 Copying custom node configurations..."
cd "$THREEGEN_DIR"

# No more copy-paste! Everything is now in ComfyUI-MeshCraft

echo ""
echo "🎨 Installing Blender (required for MeshCraft UV unwrapping)..."
if command -v blender &> /dev/null; then
    echo "✅ Blender already installed: $(blender --version | head -n1)"
else
    echo "📥 Installing Blender via snap..."
    sudo snap install blender --classic

    # Verify installation
    if command -v blender &> /dev/null; then
        echo "✅ Blender installed successfully: $(blender --version | head -n1)"
    else
        echo "⚠️  Blender installation failed. MeshCraft UV unwrapping may not work."
        echo "   Please install Blender manually: sudo snap install blender --classic"
    fi
fi

echo ""
echo "📦 Installing final dependencies..."
uv pip install transformers==4.46.3
uv pip install pynanoinstantmeshes
uv pip install hf_transfer
uv pip install diso --no-build-isolation
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
