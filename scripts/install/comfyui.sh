#!/bin/bash
set -e  # Stop on first error

# Track installation status for summary
INSTALL_WARNINGS=()
INSTALL_FAILURES=()

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
    "https://github.com/PozzettiAndrea/ComfyUI-Grounding"
    "https://github.com/kijai/ComfyUI-segment-anything-2"
    "https://github.com/rgthree/rgthree-comfy"
    "https://github.com/john-mnz/ComfyUI-Inspyrenet-Rembg"
    "https://github.com/ZHO-ZHO-ZHO/ComfyUI-Gemini"
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

# Aggressively remove all OpenCV variants
set +e
uv pip uninstall -y opencv-python opencv-python-headless opencv-contrib-python 2>/dev/null
set -e

# Pin to 4.10.0.84 - version 4.12.x is broken (missing cv2.__init__.py)
# Force reinstall to ensure clean installation
echo "   Installing opencv-contrib-python==4.10.0.84..."
uv pip install --reinstall opencv-contrib-python==4.10.0.84

# Verify installation
echo "   Verifying OpenCV installation..."
if python -c "import cv2; assert hasattr(cv2, 'INTER_CUBIC'), 'Missing INTER_CUBIC'; assert hasattr(cv2, 'BORDER_DEFAULT'), 'Missing BORDER_DEFAULT'; print(f'OpenCV {cv2.__version__} verified')" 2>/dev/null; then
    echo "   ✅ OpenCV configured with contrib modules (version 4.10.0.84)"
else
    echo "   ⚠️  OpenCV verification failed"
fi

echo ""
echo "🔧 Checking C++ compiler (required for CUDA extensions)..."

# Helper function to fix apt repository issues
fix_apt_sources() {
    echo "   Attempting to fix apt repository issues..."

    # Check if we have the problematic massedcompute mirror
    if grep -r "mcache-dsm.massedcompute.com" /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null | grep -q .; then
        echo "   Found problematic mirror (mcache-dsm.massedcompute.com)"
        echo "   Switching to official Ubuntu mirrors..."

        # Backup existing sources
        sudo cp /etc/apt/sources.list /etc/apt/sources.list.backup 2>/dev/null || true

        # Replace massedcompute mirror with official Ubuntu mirror
        sudo sed -i 's|http[s]*://mcache-dsm.massedcompute.com/debian-archive/|http://archive.ubuntu.com/ubuntu/|g' /etc/apt/sources.list 2>/dev/null || true
        sudo sed -i 's|http[s]*://mcache-dsm.massedcompute.com/debian-security/|http://security.ubuntu.com/ubuntu/|g' /etc/apt/sources.list 2>/dev/null || true

        # Try to update again
        if sudo apt-get update -qq 2>&1 | grep -q "certificate"; then
            echo "   Still having certificate issues, trying with different security settings..."
            # Create apt config to be more lenient with certificates for this session
            echo 'Acquire::https::Verify-Peer "false";' | sudo tee /etc/apt/apt.conf.d/99temp-no-verify >/dev/null
            sudo apt-get update -qq
            sudo rm /etc/apt/apt.conf.d/99temp-no-verify 2>/dev/null || true
        fi
        return 0
    fi

    return 1
}

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

    # Try apt-get update, if it fails try to fix sources
    if ! sudo apt-get update -qq 2>&1; then
        echo "   apt-get update failed, attempting to fix repository issues..."
        fix_apt_sources

        # Try update one more time after fix
        if ! sudo apt-get update -qq 2>&1; then
            echo "⚠️  Still having issues with apt-get update"
            echo "   Proceeding with installation anyway..."
        fi
    fi

    # Install missing packages (don't remove existing ones)
    if sudo apt-get install -y $INSTALL_PKGS 2>&1; then
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
        INSTALL_WARNINGS+=("C++ compiler: Installation failed")
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

        # Try update with fix if needed
        if ! sudo apt-get update -qq 2>&1; then
            echo "   apt-get update failed, attempting to fix repository issues..."
            fix_apt_sources
            sudo apt-get update -qq 2>&1 || true
        fi
    fi

    # Install CUDA Toolkit
    echo "   Installing cuda-toolkit-12-8 (this may take a few minutes)..."
    if sudo apt-get install -y cuda-toolkit-12-8 2>&1 | tee /tmp/cuda_install.log | grep -v "^Get:\|^Hit:\|^Ign:" | grep -v "^$"; then
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
        INSTALL_WARNINGS+=("CUDA Toolkit: Installation failed")
    fi
fi

# Re-check compiler availability after CUDA installation
# CUDA toolkit often installs build-essential as a dependency
echo ""
echo "🔧 Verifying final compiler setup..."
if [ "$SKIP_CUDA_EXTENSIONS" = true ]; then
    if command -v g++ &> /dev/null && test_cpp_compilation; then
        echo "✅ C++ compiler is now available (installed via CUDA dependencies)"
        echo "   Compiler: $(g++ --version | head -n1)"

        # Clear the skip flag - we can build extensions now!
        SKIP_CUDA_EXTENSIONS=false

        # Remove the warning about compiler failure
        INSTALL_WARNINGS=("${INSTALL_WARNINGS[@]/C++ compiler: Installation failed/}")
        INSTALL_WARNINGS=("${INSTALL_WARNINGS[@]/ /}")  # Remove empty elements
    else
        echo "⚠️  C++ compiler still not available after CUDA installation"
    fi
fi

echo ""
echo "🔧 Building custom rasterizer extensions..."

# Skip extension building if CUDA Toolkit installation failed
if [ "$SKIP_CUDA_EXTENSIONS" = true ]; then
    echo "⚠️  Skipping CUDA extension building (CUDA Toolkit not available)"
    echo "   ComfyUI will work but may have reduced functionality"
    INSTALL_WARNINGS+=("CUDA extensions: Skipped (C++ compiler or CUDA toolkit unavailable)")
else
    # Build MeshCraft custom rasterizer
    if [ -d "ComfyUI-MeshCraft/hy3dpaint/custom_rasterizer" ]; then
        echo "   Building custom_rasterizer..."
        cd ComfyUI-MeshCraft/hy3dpaint/custom_rasterizer/

        set +e
        python -m setup install 2>&1 | grep -v "^$"
        RASTERIZER_EXIT=$?
        set -e

        cd ../../..

        if [ $RASTERIZER_EXIT -ne 0 ]; then
            INSTALL_WARNINGS+=("MeshCraft custom_rasterizer: Build failed")
        fi
    fi

    # Build MeshCraft DifferentiableRenderer
    if [ -d "ComfyUI-MeshCraft/hy3dpaint/DifferentiableRenderer" ]; then
        echo "   Building DifferentiableRenderer..."
        cd ComfyUI-MeshCraft/hy3dpaint/DifferentiableRenderer/

        set +e
        python -m setup install 2>&1 | grep -v "^$"
        RENDERER_EXIT=$?
        set -e

        cd ../../..

        if [ $RENDERER_EXIT -ne 0 ]; then
            INSTALL_WARNINGS+=("MeshCraft DifferentiableRenderer: Build failed")
        fi
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

    # Temporarily disable exit on error (snap may produce harmless warnings)
    set +e
    # Redirect stderr, filter out mkdir warnings and empty lines
    sudo snap install blender --classic 2>&1 | grep -v "^$\|^mkdir:" || true
    BLENDER_EXIT_CODE=$?
    set -e

    # Verify installation (actual check - ignore exit code from snap)
    if command -v blender &> /dev/null; then
        echo "✅ Blender installed successfully: $(blender --version | head -n1)"
    else
        echo "⚠️  Blender installation failed. MeshCraft UV unwrapping may not work."
        echo "   Please install Blender manually: sudo snap install blender --classic"
        INSTALL_WARNINGS+=("Blender: Installation failed or not in PATH")
    fi
fi

echo ""
echo "📦 Installing final dependencies..."

# Install core dependencies (these should not fail)
uv pip install transformers==4.46.3
uv pip install pynanoinstantmeshes
uv pip install hf_transfer

# Install diso (optional CUDA extension - may fail if C++ compiler issues)
echo ""
echo "📦 Installing diso (CUDA mesh processing extension)..."
if [ "$SKIP_CUDA_EXTENSIONS" = true ]; then
    echo "⚠️  Skipping diso installation (CUDA extensions disabled)"
    INSTALL_WARNINGS+=("diso: Skipped due to missing CUDA toolchain")
else
    # Temporarily disable exit on error for this optional package
    set +e
    uv pip install diso --no-build-isolation 2>&1 | tee /tmp/diso_install.log
    DISO_EXIT_CODE=$?
    set -e

    if [ $DISO_EXIT_CODE -eq 0 ]; then
        echo "✅ diso installed successfully"
    else
        echo "⚠️  Failed to install diso (optional CUDA extension)"
        echo "   This is used for advanced mesh processing in MeshCraft"
        echo "   ComfyUI will work without it but some features may be unavailable"
        echo ""
        INSTALL_WARNINGS+=("diso: Installation failed (C++ compiler or CUDA issues)")

        # Check the error log for specific issues
        if grep -q "cannot execute 'cc1plus'" /tmp/diso_install.log; then
            echo "   Issue: C++ compiler (g++) not working properly"
            echo "   Fix: Run 'sudo apt-get install --reinstall build-essential g++'"
        elif grep -q "nvcc fatal" /tmp/diso_install.log; then
            echo "   Issue: CUDA compilation failed"
            echo "   Fix: Ensure CUDA Toolkit is properly installed"
        fi
        echo ""
    fi
    rm -f /tmp/diso_install.log
fi

# Install server dependencies
uv pip install fastapi python-multipart uvicorn

echo ""
echo "✅ ComfyUI setup complete!"
echo "=========================================================="

# Print installation summary if there were any warnings or failures
if [ ${#INSTALL_WARNINGS[@]} -gt 0 ] || [ ${#INSTALL_FAILURES[@]} -gt 0 ]; then
    echo ""
    echo "📋 Installation Summary"
    echo "=========================================================="

    if [ ${#INSTALL_FAILURES[@]} -gt 0 ]; then
        echo ""
        echo "❌ Critical Failures:"
        for failure in "${INSTALL_FAILURES[@]}"; do
            echo "   • $failure"
        done
    fi

    if [ ${#INSTALL_WARNINGS[@]} -gt 0 ]; then
        echo ""
        echo "⚠️  Warnings (non-critical):"
        for warning in "${INSTALL_WARNINGS[@]}"; do
            echo "   • $warning"
        done
        echo ""
        echo "Note: ComfyUI will work, but some optional features may be unavailable."
    fi

    echo "=========================================================="
fi

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
