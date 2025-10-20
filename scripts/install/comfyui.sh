#!/bin/bash
set -e  # Stop on first error

echo "🚀 Setting up ComfyUI with uv (fast Python package manager)"
echo "=========================================================="

# Navigate to 3d_gen directory (where ComfyUI should be installed)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
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

# Install dependencies for all custom nodes
for repo in "${CUSTOM_NODES[@]}"; do
    repo_name=$(basename "$repo")
    if [ -f "$repo_name/requirements.txt" ]; then
        echo "📦 Installing $repo_name dependencies..."
        uv pip install -r "$repo_name/requirements.txt"
    else
        echo "   ℹ️  No requirements.txt found for $repo_name"
    fi
done

# Additional dependencies
echo ""
echo "Installing rembg with GPU support..."
uv pip install "rembg[gpu]"

echo ""
echo "🔧 Fixing OpenCV package conflicts..."
echo "   Some custom nodes require opencv-contrib-python (includes extra modules)"
echo "   while others specify opencv-python (basic version)."
echo "   Installing opencv-contrib-python which satisfies both requirements..."
uv pip uninstall opencv-python opencv-python-headless 2>/dev/null || true
# Pin to 4.10.0.84 - version 4.12.x is broken (missing cv2.__init__.py, breaks MeshCraft)
uv pip install opencv-contrib-python==4.10.0.84
echo "   ✅ OpenCV configured with contrib modules (pinned to 4.10.0.84)"

echo ""
echo "🔧 Checking C++ compiler (required for CUDA extensions)..."

# Test if g++ can actually compile (not just if command exists)
test_cpp_compilation() {
    # Create a simple test program
    cat > /tmp/test_gcc.cpp << 'EOF'
#include <iostream>
int main() { std::cout << "test"; return 0; }
EOF

    # Try to compile it
    if g++ /tmp/test_gcc.cpp -o /tmp/test_gcc &> /dev/null; then
        rm -f /tmp/test_gcc.cpp /tmp/test_gcc
        return 0
    else
        rm -f /tmp/test_gcc.cpp /tmp/test_gcc
        return 1
    fi
}

# Find all installed gcc versions and check for corresponding g++
NEEDS_INSTALL=false
MISSING_GPP_VERSIONS=()

# Check for gcc versions (11, 12, etc.)
for gcc_bin in /usr/bin/gcc-[0-9]*; do
    if [ -x "$gcc_bin" ]; then
        VERSION=$(basename "$gcc_bin" | sed 's/gcc-//')
        if [ ! -x "/usr/bin/g++-$VERSION" ]; then
            echo "⚠️  Found gcc-$VERSION but missing g++-$VERSION"
            MISSING_GPP_VERSIONS+=("$VERSION")
            NEEDS_INSTALL=true
        fi
    fi
done

# Check if g++ exists and can compile
if command -v g++ &> /dev/null && test_cpp_compilation && [ "$NEEDS_INSTALL" = false ]; then
    echo "✅ C++ compiler working: $(g++ --version | head -n1)"
else
    if [ "$NEEDS_INSTALL" = true ]; then
        echo "⚠️  C++ toolchain incomplete (missing g++ for some gcc versions)"
    elif command -v g++ &> /dev/null; then
        echo "⚠️  C++ compiler found but broken (compilation test failed)"
    else
        echo "⚠️  C++ compiler (g++) not found"
    fi
    echo "   This is required to compile CUDA extensions"
    echo ""
    echo "📥 Installing/reinstalling C++ compiler toolchain..."

    # Build install command with all needed g++ versions
    INSTALL_PKGS="build-essential g++"
    for ver in "${MISSING_GPP_VERSIONS[@]}"; do
        INSTALL_PKGS="$INSTALL_PKGS g++-$ver"
    done

    if sudo apt-get update -qq && sudo apt-get install --reinstall -y $INSTALL_PKGS > /dev/null 2>&1; then
        echo "✅ C++ toolchain installed successfully"

        # Test compilation again
        if command -v g++ &> /dev/null && test_cpp_compilation; then
            echo "✅ C++ compiler now working: $(g++ --version | head -n1)"
        else
            echo "⚠️  C++ compiler still not working after installation"
            echo "   You may need to restart your shell or manually fix the installation"
            echo ""
            echo "   Skipping CUDA extension building..."
            SKIP_CUDA_EXTENSIONS=true
        fi
    else
        echo "❌ Failed to install C++ toolchain"
        echo ""
        echo "⚠️  WARNING: Cannot build custom CUDA extensions without C++ compiler"
        echo "   Please install manually with:"
        echo "   sudo apt-get update && sudo apt-get install --reinstall -y $INSTALL_PKGS"
        echo ""
        echo "   Skipping CUDA extension building..."
        # Set flag to skip extension building
        SKIP_CUDA_EXTENSIONS=true
    fi
fi

echo ""
echo "🔧 Setting up CUDA Toolkit for building extensions..."

# Check if CUDA Toolkit is installed (needed for building CUDA extensions)
if command -v nvcc &> /dev/null; then
    echo "✅ CUDA Toolkit already installed: $(nvcc --version | grep release | awk '{print $5,$6}')"
    # Try to detect CUDA_HOME
    if [ -z "$CUDA_HOME" ]; then
        NVCC_PATH=$(which nvcc)
        CUDA_HOME=$(dirname $(dirname $NVCC_PATH))
        export CUDA_HOME
        echo "✅ Set CUDA_HOME=$CUDA_HOME"
    fi
else
    echo "⚠️  CUDA Toolkit (nvcc compiler) not found"
    echo "   This is required to build ComfyUI-MeshCraft extensions"
    echo ""
    echo "📥 Installing CUDA Toolkit 12.8 (matches PyTorch)..."

    # Add NVIDIA CUDA repository if not already present
    if ! apt-cache policy | grep -q "cuda"; then
        echo "   Adding NVIDIA CUDA repository..."
        wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
        sudo dpkg -i cuda-keyring_1.1-1_all.deb
        rm cuda-keyring_1.1-1_all.deb
        sudo apt-get update -qq
    fi

    # Install CUDA Toolkit
    echo "   Installing cuda-toolkit-12-8 (this may take a few minutes)..."
    if sudo apt-get install -y cuda-toolkit-12-8 > /dev/null 2>&1; then
        echo "✅ CUDA Toolkit installed successfully"

        # Set CUDA_HOME
        if [ -d "/usr/local/cuda-12.8" ]; then
            export CUDA_HOME="/usr/local/cuda-12.8"
        elif [ -d "/usr/local/cuda" ]; then
            export CUDA_HOME="/usr/local/cuda"
        fi

        # Add to PATH
        export PATH="$CUDA_HOME/bin:$PATH"

        echo "✅ Set CUDA_HOME=$CUDA_HOME"

        # Verify nvcc is now accessible
        if command -v nvcc &> /dev/null; then
            echo "✅ nvcc compiler is now available: $(nvcc --version | grep release | awk '{print $5,$6}')"
        else
            echo "⚠️  nvcc not found in PATH after installation"
            echo "   You may need to restart your shell or manually set:"
            echo "   export PATH=/usr/local/cuda/bin:\$PATH"
        fi
    else
        echo "❌ Failed to install CUDA Toolkit"
        echo ""
        echo "⚠️  WARNING: Cannot build custom CUDA extensions without CUDA Toolkit"
        echo "   You can try installing manually with:"
        echo "   sudo apt-get install cuda-toolkit-12-8"
        echo ""
        echo "   Skipping CUDA extension building..."
        # Set flag to skip extension building
        SKIP_CUDA_EXTENSIONS=true
    fi
fi

echo ""
echo "🔧 Building custom rasterizer extensions..."

# Skip extension building if CUDA Toolkit installation failed
if [ "$SKIP_CUDA_EXTENSIONS" = true ]; then
    echo "⚠️  Skipping CUDA extension building (CUDA Toolkit not available)"
    echo "   ComfyUI will work but may have reduced functionality"
else
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
