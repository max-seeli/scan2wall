#!/bin/bash
set -e  # Exit on error

echo "=========================================="
echo "Isaac Sim + Isaac Lab Installation Script"
echo "=========================================="
echo ""
echo "This script will:"
echo "  1. Install uv (if needed)"
echo "  2. Install Python 3.11 (if needed)"
echo "  3. Create virtual environment at /workspace/isaac_venv"
echo "  4. Install Isaac Sim 5.0.0 via uv"
echo "  5. Clone Isaac Lab to /workspace/IsaacLab"
echo "  6. Install Isaac Lab dependencies"
echo ""

# Check for minimal install flag
MINIMAL_INSTALL=true
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Installation directories
VENV_DIR="/workspace/isaac_venv"
ISAAC_LAB_DIR="/workspace/IsaacLab"
WORKSPACE_DIR="/workspace"

# ============================================================================
# Prerequisites Check
# ============================================================================

echo "Checking prerequisites..."
echo ""

# Check if running on Linux
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    echo -e "${RED}✗ Error: This script only supports Linux${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} Operating system: Linux"

# Check for NVIDIA GPU
if ! command -v nvidia-smi &> /dev/null; then
    echo -e "${RED}✗ Error: nvidia-smi not found. NVIDIA GPU required${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} NVIDIA GPU detected:"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader | head -1

# Check disk space (need at least 150GB for full installation)
AVAILABLE_SPACE=$(df -BG "$WORKSPACE_DIR" | tail -1 | awk '{print $4}' | sed 's/G//')
if [ "$AVAILABLE_SPACE" -lt 150 ]; then
    echo -e "${YELLOW}⚠${NC} Warning: Low disk space. Have ${AVAILABLE_SPACE}GB, recommend 150GB+"
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo -e "${GREEN}✓${NC} Disk space: ${AVAILABLE_SPACE}GB available"
fi

echo ""
echo -e "${GREEN}All prerequisites satisfied!${NC}"
echo ""

# ============================================================================
# Install uv
# ============================================================================

echo "Checking uv..."
if command -v uv &> /dev/null; then
    UV_VERSION=$(uv --version)
    echo -e "${GREEN}✓${NC} uv already installed: $UV_VERSION"
else
    echo "uv not found. Installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Add uv to PATH for current session
    export PATH="$HOME/.local/bin:$PATH"
    echo -e "${GREEN}✓${NC} uv installed"
fi

echo ""

# ============================================================================
# Install Python 3.11
# ============================================================================

echo "Checking Python 3.11..."
if command -v python3.11 &> /dev/null; then
    PYTHON_VERSION=$(python3.11 --version)
    echo -e "${GREEN}✓${NC} Python 3.11 already installed: $PYTHON_VERSION"
else
    echo "Python 3.11 not found. Installing..."
    sudo apt-get update -qq
    sudo apt-get install -y python3.11 python3.11-venv python3.11-dev
    echo -e "${GREEN}✓${NC} Python 3.11 installed"
fi

echo ""

# ============================================================================
# Create Virtual Environment with uv
# ============================================================================

if [ -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}⚠${NC} Virtual environment already exists at $VENV_DIR"
    echo "Removing existing venv..."
    rm -rf "$VENV_DIR"
fi

echo "Creating Python 3.11 virtual environment with uv at $VENV_DIR..."
uv venv "$VENV_DIR" --python 3.11
echo -e "${GREEN}✓${NC} Virtual environment created"

# Activate virtual environment
source "$VENV_DIR/bin/activate"

echo ""

# ============================================================================
# Install Isaac Sim via uv pip
# ============================================================================

echo "Installing Isaac Sim 5.0.0 via uv pip..."
echo -e "${YELLOW}This will download several GB of dependencies (much faster with uv!)${NC}"
echo ""

uv pip install isaacsim[all,extscache]==5.0.0.0 --extra-index-url https://pypi.nvidia.com

echo ""
echo -e "${GREEN}✓${NC} Isaac Sim installed"
echo ""

# Verify Isaac Sim installation
echo "Verifying Isaac Sim installation..."
python -c 'import isaacsim; print("Isaac Sim version:", isaacsim.__version__)' || {
    echo -e "${RED}✗ Error: Isaac Sim import failed${NC}"
    exit 1
}
echo -e "${GREEN}✓${NC} Isaac Sim import successful"
echo ""

# ============================================================================
# Clone Isaac Lab
# ============================================================================

echo "Installing Isaac Lab..."
echo ""

if [ -d "$ISAAC_LAB_DIR" ]; then
    echo -e "${YELLOW}⚠${NC} Isaac Lab directory already exists at $ISAAC_LAB_DIR"
    read -p "Remove and reinstall? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Removing existing installation..."
        rm -rf "$ISAAC_LAB_DIR"
    else
        echo "Keeping existing installation. Skipping Isaac Lab clone."
        cd "$ISAAC_LAB_DIR"
    fi
fi

if [ ! -d "$ISAAC_LAB_DIR" ]; then
    cd "$WORKSPACE_DIR"
    echo "Cloning Isaac Lab repository..."
    git clone --depth 1 https://github.com/isaac-sim/IsaacLab.git
    cd "$ISAAC_LAB_DIR"
    echo -e "${GREEN}✓${NC} Isaac Lab cloned to $ISAAC_LAB_DIR"
else
    cd "$ISAAC_LAB_DIR"
fi

echo ""

# ============================================================================
# Run Isaac Lab Installation
# ============================================================================

echo "Running Isaac Lab installation..."

if [ "$MINIMAL_INSTALL" = "true" ]; then
    echo "Installing minimal Isaac Lab (core only, no RL/ML extensions)..."
    echo ""
    echo -e "${YELLOW}This may take 3-5 minutes...${NC}"
    echo ""

    # Make sure venv is still activated
    source "$VENV_DIR/bin/activate"

    # Install only the core Isaac Lab package
    pip install -e source/isaaclab

    # Install minimal additional dependencies needed by scan2wall scripts
    pip install warp-lang opencv-python

    echo ""
    echo -e "${GREEN}✓${NC} Minimal Isaac Lab installation complete"
else
    echo "This will:"
    echo "  - Install Isaac Lab Python dependencies"
    echo "  - Install PyTorch, Warp, and other tools"
    echo "  - Sync Isaac Lab extensions (includes RL/ML frameworks)"
    echo ""
    echo -e "${YELLOW}This may take 20-25 minutes...${NC}"
    echo ""
    echo "Tip: For scan2wall, you only need minimal install:"
    echo "  ./setup_isaac.sh --minimal"
    echo ""

    # Make sure venv is still activated
    source "$VENV_DIR/bin/activate"

    # Run the full Isaac Lab installer
    ./isaaclab.sh --install
fi

echo ""
echo -e "${GREEN}✓${NC} Isaac Lab installation complete"
echo ""

# ============================================================================
# Install ffmpeg (for video encoding)
# ============================================================================

echo "Installing ffmpeg..."
if command -v ffmpeg &> /dev/null; then
    echo -e "${GREEN}✓${NC} ffmpeg already installed: $(ffmpeg -version | head -1)"
else
    sudo apt-get update -qq
    sudo apt-get install -y ffmpeg
    echo -e "${GREEN}✓${NC} ffmpeg installed"
fi

echo ""

# ============================================================================
# Configure scan2wall paths
# ============================================================================

echo "Configuring scan2wall environment..."
cd /workspace/scan2wall

# Update .env if it exists, otherwise update .env.example
if [ -f ".env" ]; then
    ENV_FILE=".env"
else
    ENV_FILE=".env.example"
fi

# Update Isaac workspace path
if grep -q "^ISAAC_WORKSPACE=" "$ENV_FILE"; then
    sed -i "s|^ISAAC_WORKSPACE=.*|ISAAC_WORKSPACE=$ISAAC_LAB_DIR|" "$ENV_FILE"
else
    echo "ISAAC_WORKSPACE=$ISAAC_LAB_DIR" >> "$ENV_FILE"
fi

# Update USD output directory
if grep -q "^USD_OUTPUT_DIR=" "$ENV_FILE"; then
    sed -i "s|^USD_OUTPUT_DIR=.*|USD_OUTPUT_DIR=$ISAAC_LAB_DIR/usd_files|" "$ENV_FILE"
else
    echo "USD_OUTPUT_DIR=$ISAAC_LAB_DIR/usd_files" >> "$ENV_FILE"
fi

# Create USD output directory
mkdir -p "$ISAAC_LAB_DIR/usd_files"

echo -e "${GREEN}✓${NC} Paths configured in $ENV_FILE"
echo ""

# ============================================================================
# Verification
# ============================================================================

echo "Verifying installation..."
echo ""

# Test Isaac Lab can be invoked
if [ -f "$ISAAC_LAB_DIR/isaaclab.sh" ]; then
    echo -e "${GREEN}✓${NC} Isaac Lab executable found"
else
    echo -e "${RED}✗${NC} Isaac Lab executable not found"
    exit 1
fi

# Verify venv has Isaac Sim
source "$VENV_DIR/bin/activate"
if python -c "import isaacsim" 2>/dev/null; then
    echo -e "${GREEN}✓${NC} Isaac Sim accessible from venv"
else
    echo -e "${RED}✗${NC} Isaac Sim not accessible from venv"
    exit 1
fi

echo ""

# ============================================================================
# Success Message
# ============================================================================

echo "=========================================="
echo -e "${GREEN}Installation Complete!${NC}"
echo "=========================================="
echo ""
echo "Installation summary:"
echo "  • Python venv:  $VENV_DIR"
echo "  • Isaac Sim:    Installed via pip (isaacsim==5.0.0.0)"
echo "  • Isaac Lab:    $ISAAC_LAB_DIR"
echo "  • USD files:    $ISAAC_LAB_DIR/usd_files"
echo ""
echo "Next steps:"
echo ""
echo "1. Activate the virtual environment:"
echo "   source $VENV_DIR/bin/activate"
echo ""
echo "2. Test Isaac Lab:"
echo "   cd $ISAAC_LAB_DIR"
echo "   ./isaaclab.sh -p"
echo ""
echo "3. Continue scan2wall setup:"
echo "   cd /workspace/scan2wall"
echo "   ./setup_scan2wall.sh"
echo ""
echo -e "${YELLOW}Note:${NC} Always activate the venv before running Isaac scripts:"
echo "      source /workspace/isaac_venv/bin/activate"
echo ""
