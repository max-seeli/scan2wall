#!/bin/bash
set -e  # Exit on error

echo "=========================================="
echo "Isaac Lab Installation Script"
echo "=========================================="
echo ""
echo "This script will install Isaac Lab at /workspace/isaac"
echo "Isaac Lab is an open-source robotics simulation framework built on NVIDIA Isaac Sim"
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Installation directory
ISAAC_DIR="/workspace/isaac"
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

# Check CUDA
if ! command -v nvcc &> /dev/null; then
    echo -e "${YELLOW}⚠${NC} Warning: CUDA toolkit not found (nvcc). Isaac Lab will attempt to install it."
else
    echo -e "${GREEN}✓${NC} CUDA version: $(nvcc --version | grep release | awk '{print $5}' | sed 's/,//')"
fi

# Check disk space (need at least 50GB)
AVAILABLE_SPACE=$(df -BG "$WORKSPACE_DIR" | tail -1 | awk '{print $4}' | sed 's/G//')
if [ "$AVAILABLE_SPACE" -lt 50 ]; then
    echo -e "${RED}✗ Error: Insufficient disk space. Need at least 50GB, have ${AVAILABLE_SPACE}GB${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} Disk space: ${AVAILABLE_SPACE}GB available"

echo ""
echo -e "${GREEN}All prerequisites satisfied!${NC}"
echo ""

# ============================================================================
# Install Miniforge (if not present)
# ============================================================================

if ! command -v conda &> /dev/null; then
    echo "Installing Miniforge (conda)..."
    cd /tmp
    wget -q https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
    bash Miniforge3-Linux-x86_64.sh -b -p $HOME/miniforge3

    # Initialize conda for current shell
    eval "$($HOME/miniforge3/bin/conda shell.bash hook)"

    # Initialize conda for future shells
    $HOME/miniforge3/bin/conda init bash

    echo -e "${GREEN}✓${NC} Miniforge installed"
else
    echo -e "${GREEN}✓${NC} Conda already installed: $(conda --version)"
fi

echo ""

# ============================================================================
# Clone Isaac Lab
# ============================================================================

echo "Installing Isaac Lab..."
echo ""

if [ -d "$ISAAC_DIR" ]; then
    echo -e "${YELLOW}⚠${NC} Isaac Lab directory already exists at $ISAAC_DIR"
    read -p "Remove and reinstall? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Removing existing installation..."
        rm -rf "$ISAAC_DIR"
    else
        echo "Keeping existing installation. Skipping Isaac Lab setup."
        echo "If you want a fresh install, delete $ISAAC_DIR manually."
        exit 0
    fi
fi

cd "$WORKSPACE_DIR"
echo "Cloning Isaac Lab repository..."
git clone https://github.com/isaac-sim/IsaacLab.git isaac

cd "$ISAAC_DIR"

echo -e "${GREEN}✓${NC} Isaac Lab cloned to $ISAAC_DIR"
echo ""

# ============================================================================
# Run Isaac Lab Installation
# ============================================================================

echo "Running Isaac Lab installation script..."
echo "This will:"
echo "  - Create a conda environment (isaac-lab)"
echo "  - Download Isaac Sim (~10GB)"
echo "  - Install all dependencies"
echo ""
echo -e "${YELLOW}This may take 20-30 minutes...${NC}"
echo ""

# Run the Isaac Lab installer
./isaaclab.sh --install

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
    sed -i "s|^ISAAC_WORKSPACE=.*|ISAAC_WORKSPACE=$ISAAC_DIR|" "$ENV_FILE"
else
    echo "ISAAC_WORKSPACE=$ISAAC_DIR" >> "$ENV_FILE"
fi

# Update USD output directory
if grep -q "^USD_OUTPUT_DIR=" "$ENV_FILE"; then
    sed -i "s|^USD_OUTPUT_DIR=.*|USD_OUTPUT_DIR=$ISAAC_DIR/usd_files|" "$ENV_FILE"
else
    echo "USD_OUTPUT_DIR=$ISAAC_DIR/usd_files" >> "$ENV_FILE"
fi

# Create USD output directory
mkdir -p "$ISAAC_DIR/usd_files"

echo -e "${GREEN}✓${NC} Paths configured in $ENV_FILE"
echo ""

# ============================================================================
# Verification
# ============================================================================

echo "Verifying installation..."
echo ""

# Test Isaac Lab can be invoked
if [ -f "$ISAAC_DIR/isaaclab.sh" ]; then
    echo -e "${GREEN}✓${NC} Isaac Lab executable found"
else
    echo -e "${RED}✗${NC} Isaac Lab executable not found"
    exit 1
fi

# Check if Isaac Sim was downloaded
if [ -d "$ISAAC_DIR/_isaac_sim" ]; then
    echo -e "${GREEN}✓${NC} Isaac Sim downloaded"
else
    echo -e "${YELLOW}⚠${NC} Isaac Sim not found (may install on first run)"
fi

echo ""

# ============================================================================
# Success Message
# ============================================================================

echo "=========================================="
echo -e "${GREEN}Installation Complete!${NC}"
echo "=========================================="
echo ""
echo "Isaac Lab installed at: $ISAAC_DIR"
echo "USD files will be saved to: $ISAAC_DIR/usd_files"
echo ""
echo "Next steps:"
echo ""
echo "1. Test Isaac Lab:"
echo "   cd $ISAAC_DIR"
echo "   ./isaaclab.sh -p"
echo ""
echo "2. Return to scan2wall and continue setup:"
echo "   cd /workspace/scan2wall"
echo "   # Follow README.md for ComfyUI setup"
echo ""
echo "3. To run Isaac scripts, use the Isaac Lab Python:"
echo "   $ISAAC_DIR/isaaclab.sh -p isaac_scripts/convert_mesh.py ..."
echo ""
echo -e "${YELLOW}Note:${NC} The first time you run Isaac Lab, it may download additional"
echo "      assets and take a few minutes to initialize."
echo ""
