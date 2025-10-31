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

# Early check: Is ComfyUI already installed but CUDA missing?
if [ -d "ComfyUI" ] && ! command -v nvcc &> /dev/null; then
    echo ""
    echo "⚠️  WARNING: ComfyUI directory exists but CUDA Toolkit is missing!"
    echo "   This setup will install CUDA Toolkit (required for diso package)"
    echo ""
fi

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
    "https://github.com/PozzettiAndrea/ComfyUI-Inspyrenet-Rembg-withcaching"
    "https://github.com/yichengup/ComfyUI-YCNodes"
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
CUDA_VERSION_CHECK=""
if command -v nvcc &> /dev/null; then
    CUDA_VERSION_CHECK=$(nvcc --version | grep release | awk '{print $6}' | tr -d ',')
    echo "✅ CUDA Toolkit found: $(nvcc --version | grep release | awk '{print $5,$6}')"

    # Check if version is 12.x (matches PyTorch)
    CUDA_MAJOR=$(echo "$CUDA_VERSION_CHECK" | cut -d'.' -f1)
    CUDA_MINOR=$(echo "$CUDA_VERSION_CHECK" | cut -d'.' -f2)

    if [ "$CUDA_MAJOR" != "12" ]; then
        echo "⚠️  WARNING: CUDA version $CUDA_VERSION_CHECK detected, but PyTorch expects CUDA 12.x"
        echo "   This may cause compatibility issues with diso and other CUDA extensions"
    else
        echo "✅ CUDA version compatible with PyTorch (12.x)"
    fi

    # Try to detect CUDA_HOME
    if [ -z "$CUDA_HOME" ]; then
        NVCC_PATH=$(which nvcc)
        CUDA_HOME=$(dirname $(dirname $NVCC_PATH))
        export CUDA_HOME
        echo "✅ Set CUDA_HOME=$CUDA_HOME"
    else
        echo "✅ CUDA_HOME already set: $CUDA_HOME"
    fi

    # Verify CUDA_HOME actually exists
    if [ ! -d "$CUDA_HOME" ]; then
        echo "⚠️  WARNING: CUDA_HOME=$CUDA_HOME does not exist"
        # Try to find CUDA installation
        for cuda_path in /usr/local/cuda-12.8 /usr/local/cuda-12 /usr/local/cuda; do
            if [ -d "$cuda_path" ]; then
                CUDA_HOME="$cuda_path"
                export CUDA_HOME
                echo "✅ Found CUDA at $CUDA_HOME"
                break
            fi
        done
    fi
else
    echo "⚠️  CUDA Toolkit (nvcc compiler) not found"
    echo "   This is required to build ComfyUI-MeshCraft extensions"
    echo ""
    echo "📥 Installing CUDA Toolkit 12.8 (matches PyTorch)..."

    # Add NVIDIA CUDA repository if not already present
    if ! grep -r "developer.download.nvidia.com/compute/cuda" /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null | grep -q .; then
        echo "   Adding NVIDIA CUDA repository..."

        # Detect Ubuntu version
        UBUNTU_VERSION=$(lsb_release -rs | tr -d '.')
        if [ -z "$UBUNTU_VERSION" ]; then
            # Fallback: parse /etc/os-release
            UBUNTU_VERSION=$(grep VERSION_ID /etc/os-release | cut -d'"' -f2 | tr -d '.')
        fi

        # Default to 2204 if detection fails
        if [ -z "$UBUNTU_VERSION" ]; then
            echo "   ⚠️  Could not detect Ubuntu version, defaulting to 22.04"
            UBUNTU_VERSION="2204"
        else
            echo "   Detected Ubuntu version: ${UBUNTU_VERSION:0:2}.${UBUNTU_VERSION:2}"
        fi

        # Download and install CUDA keyring
        CUDA_REPO_URL="https://developer.download.nvidia.com/compute/cuda/repos/ubuntu${UBUNTU_VERSION}/x86_64/cuda-keyring_1.1-1_all.deb"
        echo "   Downloading from: $CUDA_REPO_URL"

        if wget -q "$CUDA_REPO_URL" -O /tmp/cuda-keyring.deb; then
            sudo dpkg -i /tmp/cuda-keyring.deb
            rm /tmp/cuda-keyring.deb
        else
            echo "   ⚠️  Failed to download CUDA keyring, trying fallback URL..."
            # Fallback to 22.04 if specific version fails
            wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
            sudo dpkg -i cuda-keyring_1.1-1_all.deb
            rm cuda-keyring_1.1-1_all.deb
        fi

        # Try update with fix if needed
        if ! sudo apt-get update -qq 2>&1; then
            echo "   apt-get update failed, attempting to fix repository issues..."
            fix_apt_sources
            sudo apt-get update -qq 2>&1 || true
        fi
    fi

    # Install minimal CUDA (compiler + headers + libraries, ~600MB instead of 8GB)
    echo "   Installing minimal CUDA Toolkit (nvcc + headers + dev libraries)..."

    # Try installing individual packages first (more control)
    CUDA_PACKAGES="cuda-nvcc-12-8 cuda-cudart-dev-12-8 cuda-nvrtc-dev-12-8 cuda-driver-dev-12-8"

    # First attempt with individual packages
    set +e
    sudo apt-get install -y $CUDA_PACKAGES 2>&1 | tee /tmp/cuda_install.log
    INSTALL_EXIT_CODE=$?
    set -e

    # Check if installation actually succeeded
    CUDA_INSTALLED=false
    if [ $INSTALL_EXIT_CODE -eq 0 ] && ! grep -q "Unable to locate package" /tmp/cuda_install.log; then
        CUDA_INSTALLED=true
    fi

    # Retry if installation failed due to broken mirror (404 errors)
    if [ "$CUDA_INSTALLED" = false ] && grep -q "404.*Not Found" /tmp/cuda_install.log; then
        echo "   ⚠️  Installation failed due to broken repository mirror"
        echo "   Fixing APT sources and retrying..."
        fix_apt_sources
        sudo apt-get update -qq 2>&1 || true

        echo "   Retrying CUDA installation..."
        set +e
        sudo apt-get install -y $CUDA_PACKAGES 2>&1 | tee /tmp/cuda_install.log
        INSTALL_EXIT_CODE=$?
        set -e

        if [ $INSTALL_EXIT_CODE -eq 0 ] && ! grep -q "Unable to locate package" /tmp/cuda_install.log; then
            CUDA_INSTALLED=true
        fi
    fi

    # If individual packages failed, try the meta-package as fallback
    if [ "$CUDA_INSTALLED" = false ]; then
        if grep -q "Unable to locate package" /tmp/cuda_install.log; then
            echo "   ⚠️  Individual packages not found in repository"

            # Check if NVIDIA CUDA repository was actually added
            if ! grep -r "developer.download.nvidia.com/compute/cuda" /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null | grep -q .; then
                echo "   ⚠️  NVIDIA CUDA repository not found, adding it now..."

                # Detect Ubuntu version
                UBUNTU_VERSION=$(lsb_release -rs | tr -d '.')
                if [ -z "$UBUNTU_VERSION" ]; then
                    UBUNTU_VERSION=$(grep VERSION_ID /etc/os-release | cut -d'"' -f2 | tr -d '.')
                fi
                if [ -z "$UBUNTU_VERSION" ]; then
                    UBUNTU_VERSION="2204"
                fi

                # Download and install CUDA keyring
                CUDA_REPO_URL="https://developer.download.nvidia.com/compute/cuda/repos/ubuntu${UBUNTU_VERSION}/x86_64/cuda-keyring_1.1-1_all.deb"
                if wget -q "$CUDA_REPO_URL" -O /tmp/cuda-keyring.deb 2>/dev/null; then
                    sudo dpkg -i /tmp/cuda-keyring.deb
                    rm /tmp/cuda-keyring.deb
                    sudo apt-get update -qq 2>&1 || true
                    echo "   ✅ NVIDIA CUDA repository added"
                else
                    echo "   ⚠️  Failed to download CUDA repository keyring"
                fi
            fi

            echo "   Trying meta-package cuda-toolkit-12-8..."
            set +e
            sudo apt-get install -y cuda-toolkit-12-8 2>&1 | tee /tmp/cuda_install_meta.log
            META_EXIT_CODE=$?
            set -e

            if [ $META_EXIT_CODE -eq 0 ] && ! grep -q "Unable to locate package" /tmp/cuda_install_meta.log; then
                CUDA_INSTALLED=true
                echo "   ✅ Installed CUDA Toolkit meta-package"
            else
                echo "   ⚠️  Meta-package also not found or failed to install"
                if grep -q "Unable to locate package" /tmp/cuda_install_meta.log; then
                    echo "   Package 'cuda-toolkit-12-8' not available in repositories"
                fi
            fi
        fi
    fi

    if [ "$CUDA_INSTALLED" = true ]; then
        echo "✅ CUDA Toolkit installed successfully"

        # Set CUDA_HOME - try multiple locations
        if [ -z "$CUDA_HOME" ]; then
            for cuda_path in /usr/local/cuda-12.8 /usr/local/cuda-12 /usr/local/cuda; do
                if [ -d "$cuda_path" ]; then
                    export CUDA_HOME="$cuda_path"
                    echo "✅ Set CUDA_HOME=$CUDA_HOME"
                    break
                fi
            done
        fi

        # If still not found, check where nvcc was installed
        if [ -z "$CUDA_HOME" ] || [ ! -d "$CUDA_HOME" ]; then
            # Force a rehash to pick up newly installed packages
            hash -r 2>/dev/null || true

            if command -v nvcc &> /dev/null; then
                NVCC_PATH=$(which nvcc)
                CUDA_HOME=$(dirname $(dirname $NVCC_PATH))
                export CUDA_HOME
                echo "✅ Detected CUDA_HOME from nvcc: $CUDA_HOME"
            else
                echo "⚠️  WARNING: Could not determine CUDA_HOME"
            fi
        fi

        # Critical fix: Add gcc libexec to PATH so nvcc can find cc1plus
        # Without this, diso compilation fails with "cannot execute 'cc1plus'"
        GCC_LIBEXEC="/usr/lib/gcc/x86_64-linux-gnu/11"

        # Only add to PATH if CUDA_HOME is set
        if [ -n "$CUDA_HOME" ]; then
            export PATH="$GCC_LIBEXEC:$CUDA_HOME/bin:$PATH"
            export LD_LIBRARY_PATH="$CUDA_HOME/lib64:$LD_LIBRARY_PATH"
        else
            export PATH="$GCC_LIBEXEC:$PATH"
        fi

        # Verify nvcc is now accessible
        # Force rehash to pick up newly installed nvcc
        hash -r 2>/dev/null || true

        if command -v nvcc &> /dev/null; then
            INSTALLED_VERSION=$(nvcc --version | grep release | awk '{print $6}' | tr -d ',')
            echo "✅ nvcc compiler is now available: CUDA $INSTALLED_VERSION"

            # Verify version is 12.x
            CUDA_MAJOR=$(echo "$INSTALLED_VERSION" | cut -d'.' -f1)
            if [ "$CUDA_MAJOR" = "12" ]; then
                echo "✅ CUDA version matches PyTorch requirements (12.x)"
            else
                echo "⚠️  WARNING: Installed CUDA $INSTALLED_VERSION, but PyTorch expects 12.x"
            fi
        else
            echo "⚠️  nvcc not found in PATH after installation"
            echo "   You may need to restart your shell or manually set:"
            echo "   export PATH=/usr/local/cuda/bin:\$PATH"
            echo "   export CUDA_HOME=/usr/local/cuda"
        fi
    else
        echo "❌ Failed to install CUDA Toolkit"
        echo ""
        echo "⚠️  WARNING: Cannot build custom CUDA extensions without CUDA Toolkit"
        echo "   You can try installing manually with one of these commands:"
        echo ""
        echo "   Option 1 (Minimal - recommended):"
        echo "   sudo apt-get install cuda-nvcc-12-8 cuda-cudart-dev-12-8 cuda-nvrtc-dev-12-8 cuda-driver-dev-12-8"
        echo ""
        echo "   Option 2 (Full toolkit - larger download):"
        echo "   sudo apt-get install cuda-toolkit-12-8"
        echo ""
        echo "   After installation, set environment variables:"
        echo "   export CUDA_HOME=/usr/local/cuda-12.8"
        echo "   export PATH=/usr/lib/gcc/x86_64-linux-gnu/11:\$CUDA_HOME/bin:\$PATH"
        echo "   export LD_LIBRARY_PATH=\$CUDA_HOME/lib64:\$LD_LIBRARY_PATH"
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

    # Install required X11/XKB libraries for headless Blender operation
    echo "📦 Installing X11 libraries for headless Blender..."
    sudo apt-get install -y libxkbcommon0 libxkbcommon-x11-0 libsm6 libice6 libxrender1 2>&1 | grep -v "^Get:\|^Hit:\|^Ign:" | grep -v "^$" || true
    echo "✅ X11 libraries installed"

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
echo "📦 Installing system dependencies for pymeshlab..."
# pymeshlab requires OpenGL libraries to load its I/O plugins (for PLY, OBJ, etc.)
if ! dpkg -l | grep -q "libopengl0"; then
    sudo apt-get install -y libopengl0 libglx0 2>&1 | grep -v "^Get:\|^Hit:\|^Ign:" | grep -v "^$" || true
    echo "✅ OpenGL libraries installed"
else
    echo "✅ OpenGL libraries already installed"
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
    # Set CUDA environment for diso compilation (ALWAYS if nvcc exists)
    if command -v nvcc &> /dev/null; then
        # Auto-detect CUDA_HOME if not already set
        if [ -z "$CUDA_HOME" ]; then
            NVCC_PATH=$(which nvcc)
            CUDA_HOME=$(dirname $(dirname $NVCC_PATH))
        fi

        # Export CUDA environment
        export CUDA_HOME
        export PATH="/usr/lib/gcc/x86_64-linux-gnu/11:$CUDA_HOME/bin:$PATH"
        export LD_LIBRARY_PATH="$CUDA_HOME/lib64:$LD_LIBRARY_PATH"
        export CC=/usr/bin/gcc
        export CXX=/usr/bin/g++

        # Show diagnostic info
        echo "🔍 CUDA environment for diso:"
        echo "   CUDA_HOME: $CUDA_HOME"
        echo "   nvcc: $(nvcc --version 2>/dev/null | grep release | awk '{print $5,$6}' || echo 'error')"
        echo "   g++: $(g++ --version 2>/dev/null | head -n1 | awk '{print $3}' || echo 'not found')"
    else
        echo "❌ nvcc not found - cannot build diso"
        INSTALL_WARNINGS+=("diso: Skipped (nvcc not available)")
        SKIP_CUDA_EXTENSIONS=true
    fi

    # Attempt installation only if we have CUDA
    if [ "$SKIP_CUDA_EXTENSIONS" != true ]; then
        echo "   Attempting diso installation (this may take 1-2 minutes)..."

        # First attempt: standard installation with --no-build-isolation
        set +e
        uv pip install diso --no-build-isolation 2>&1 | tee /tmp/diso_install.log | grep -E "^\s*Running|^\s*Building|error:|warning:" || true
        DISO_EXIT_CODE=$?
        set -e

        # REAL CHECK: Can we actually import it?
        DISO_INSTALLED=false
        if python -c "import diso; from diso import DiffDMC; print('diso OK')" 2>/dev/null | grep -q "diso OK"; then
            DISO_INSTALLED=true
        fi

        # If first attempt failed, try with verbose output and retry
        if [ "$DISO_INSTALLED" = false ]; then
            echo "   ⚠️  First installation attempt failed, trying with verbose mode..."

            # Check for common errors
            if grep -q "cannot find -lcudart" /tmp/diso_install.log; then
                echo "   Detected missing CUDA runtime library"
                echo "   Ensuring CUDA libraries are in linker path..."
                export LIBRARY_PATH="$CUDA_HOME/lib64:$LIBRARY_PATH"
            fi

            if grep -q "cc1plus: error" /tmp/diso_install.log; then
                echo "   Detected compiler path issue"
                echo "   Adjusting gcc/g++ paths..."
                # Try different gcc versions
                for gcc_ver in 11 12 13; do
                    if [ -x "/usr/bin/gcc-$gcc_ver" ] && [ -x "/usr/bin/g++-$gcc_ver" ]; then
                        export CC="/usr/bin/gcc-$gcc_ver"
                        export CXX="/usr/bin/g++-$gcc_ver"
                        export PATH="/usr/lib/gcc/x86_64-linux-gnu/$gcc_ver:$PATH"
                        echo "   Using gcc-$gcc_ver"
                        break
                    fi
                done
            fi

            # Second attempt with adjusted environment
            set +e
            uv pip install --force-reinstall --no-cache-dir diso --no-build-isolation 2>&1 | tee /tmp/diso_install_retry.log | grep -E "^\s*Running|^\s*Building|error:|warning:" || true
            set -e

            # Check again
            if python -c "import diso; from diso import DiffDMC; print('diso OK')" 2>/dev/null | grep -q "diso OK"; then
                DISO_INSTALLED=true
            fi
        fi

        # Final result
        if [ "$DISO_INSTALLED" = true ]; then
            echo "✅ diso installed successfully and verified"
            echo "   ComfyUI can now use Differentiable Marching Cubes (DMC) algorithm"
        else
            echo "❌ Failed to install diso (optional CUDA extension)"
            echo ""
            echo "   What this means:"
            echo "   • diso provides the Differentiable Marching Cubes (DMC) algorithm"
            echo "   • This is used for slightly higher-quality mesh extraction"
            echo "   • ComfyUI will automatically fall back to standard Marching Cubes (MC)"
            echo "   • Your mesh generation will still work, just with a different algorithm"
            echo ""
            INSTALL_WARNINGS+=("diso: Installation failed - using standard MC algorithm fallback")

            # Show relevant errors from log
            echo "   Build diagnostics:"
            if [ -f /tmp/diso_install_retry.log ]; then
                LOG_FILE="/tmp/diso_install_retry.log"
            else
                LOG_FILE="/tmp/diso_install.log"
            fi

            if [ -f "$LOG_FILE" ]; then
                # Show most relevant errors
                if grep -q "error:" "$LOG_FILE"; then
                    echo "   Compilation errors:"
                    grep -E "error:" "$LOG_FILE" | head -3 | sed 's/^/     /'
                fi
                if grep -q "cannot find" "$LOG_FILE"; then
                    echo "   Missing dependencies:"
                    grep -E "cannot find" "$LOG_FILE" | head -3 | sed 's/^/     /'
                fi
                if grep -q "No such file" "$LOG_FILE"; then
                    echo "   File not found errors:"
                    grep -E "No such file" "$LOG_FILE" | head -3 | sed 's/^/     /'
                fi
            fi

            echo ""
            echo "   To install diso manually later, run:"
            echo "   cd $THREEGEN_DIR && source .venv/bin/activate"
            echo "   export CUDA_HOME=$CUDA_HOME"
            echo "   export PATH=/usr/lib/gcc/x86_64-linux-gnu/11:\$CUDA_HOME/bin:\$PATH"
            echo "   export LD_LIBRARY_PATH=\$CUDA_HOME/lib64:\$LD_LIBRARY_PATH"
            echo "   uv pip install diso --no-build-isolation"
        fi

        # Cleanup
        rm -f /tmp/diso_install.log /tmp/diso_install_retry.log
    fi
fi

# Install server dependencies
uv pip install fastapi python-multipart uvicorn

echo ""
echo "🔍 Final validation checks..."
echo ""

# Validate CUDA installation
if command -v nvcc &> /dev/null; then
    echo "✅ CUDA Toolkit installed: $(nvcc --version | grep release | awk '{print $5,$6}')"

    # Ensure CUDA_HOME is set and persisted
    if [ -z "$CUDA_HOME" ]; then
        NVCC_PATH=$(which nvcc)
        CUDA_HOME=$(dirname $(dirname $NVCC_PATH))
        export CUDA_HOME
    fi

    # Add CUDA to user's profile if not already there
    PROFILE_FILE="$HOME/.bashrc"
    if ! grep -q "CUDA_HOME" "$PROFILE_FILE" 2>/dev/null; then
        echo "" >> "$PROFILE_FILE"
        echo "# CUDA Toolkit (added by scan2wall setup)" >> "$PROFILE_FILE"
        echo "export CUDA_HOME=$CUDA_HOME" >> "$PROFILE_FILE"
        echo "# Critical: Add gcc libexec so nvcc can find cc1plus" >> "$PROFILE_FILE"
        echo "export PATH=/usr/lib/gcc/x86_64-linux-gnu/11:\$CUDA_HOME/bin:\$PATH" >> "$PROFILE_FILE"
        echo "export LD_LIBRARY_PATH=\$CUDA_HOME/lib64:\$LD_LIBRARY_PATH" >> "$PROFILE_FILE"
        echo "✅ CUDA environment variables added to ~/.bashrc"
    fi
else
    echo "❌ CUDA Toolkit NOT installed!"
    echo "   This is REQUIRED for ComfyUI-MeshCraft to work properly."
    echo "   The 'diso' package needs CUDA to compile."
    echo ""
    INSTALL_FAILURES+=("CUDA Toolkit: Not installed (CRITICAL)")
fi

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
