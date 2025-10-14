#!/bin/bash
set -e  # Exit on error

# Check for minimal install flag
MINIMAL_INSTALL_FLAG=""
if [ "$1" = "--minimal" ]; then
    MINIMAL_INSTALL_FLAG="--minimal"
fi

echo "=========================================="
echo "scan2wall - Complete Installation"
echo "=========================================="
echo ""
echo "This master script will install everything needed for scan2wall:"
echo ""
echo "  Phase 1: Isaac Sim + Isaac Lab"
echo "    • Install Python 3.11"
echo "    • Create virtual environment"
echo "    • Install Isaac Sim via pip"
echo "    • Clone and setup Isaac Lab"
echo ""
echo "  Phase 2: ComfyUI (3D Generation)"
echo "    • Setup ComfyUI"
echo "    • Download Hunyuan3D models (~8GB)"
echo ""
echo "  Phase 3: scan2wall Package"
echo "    • Install scan2wall as Python package"
echo "    • Create required directories"
echo "    • Configure environment"
echo ""

if [ "$MINIMAL_INSTALL_FLAG" = "--minimal" ]; then
    echo "Estimated total time: 20-25 minutes (minimal)"
else
    echo "Estimated total time: 30-40 minutes (full)"
fi

echo "Required disk space: ~150GB"
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Ask for confirmation
read -p "Continue with installation? (y/N): " -n 1 -r
echo
echo

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Installation cancelled."
    exit 0
fi

# Track start time
START_TIME=$(date +%s)

# ============================================================================
# Phase 1: Isaac Sim + Isaac Lab
# ============================================================================

echo ""
echo "=========================================="
echo "Phase 1: Isaac Sim + Isaac Lab"
echo "=========================================="
echo ""

if [ -f "./scripts/install/isaac.sh" ]; then
    bash ./scripts/install/isaac.sh
else
    echo -e "${RED}✗ Error: scripts/install/isaac.sh not found${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}✓ Phase 1 Complete${NC}"
echo ""

# ============================================================================
# Phase 2: ComfyUI Setup
# ============================================================================

echo ""
echo "=========================================="
echo "Phase 2: ComfyUI (3D Generation)"
echo "=========================================="
echo ""

if [ -f "./scripts/install/comfyui.sh" ]; then
    bash ./scripts/install/comfyui.sh
    

    echo ""
    echo "Downloading Hunyuan3D models..."
    if [ -f "./3d_gen/modeldownload.sh" ]; then
        cd 3d_gen
        bash modeldownload.sh
        cd ..
    else
        echo -e "${YELLOW}⚠ Warning: 3d_gen/modeldownload.sh not found${NC}"
        echo "You may need to download models manually later"
    fi

else
    echo -e "${YELLOW}⚠ Warning: scripts/install/comfyui.sh not found${NC}"
    echo "Skipping ComfyUI setup. You'll need to set it up manually."
fi

echo ""
echo -e "${GREEN}✓ Phase 2 Complete${NC}"
echo ""

# ============================================================================
# Phase 3: scan2wall Package
# ============================================================================

echo ""
echo "=========================================="
echo "Phase 3: scan2wall Package"
echo "=========================================="
echo ""

if [ -f "./scripts/install/scan2wall.sh" ]; then
    bash ./scripts/install/scan2wall.sh
else
    echo -e "${RED}✗ Error: scripts/install/scan2wall.sh not found${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}✓ Phase 3 Complete${NC}"
echo ""

# ============================================================================
# Final Summary
# ============================================================================

# Calculate elapsed time
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
MINUTES=$((ELAPSED / 60))
SECONDS=$((ELAPSED % 60))

echo ""
echo "=========================================="
echo -e "${GREEN}Installation Complete!${NC}"
echo "=========================================="
echo ""
echo "Total installation time: ${MINUTES}m ${SECONDS}s"
echo ""
echo "What was installed:"
echo "  ✓ Python 3.11 virtual environment (/workspace/isaac_venv)"
echo "  ✓ Isaac Sim 5.0.0 (pip installation)"
echo "  ✓ Isaac Lab (/workspace/IsaacLab)"
echo "  ✓ ComfyUI with Hunyuan3D models"
echo "  ✓ scan2wall Python package"
echo ""
echo "Quick Start:"
echo "============"
echo ""
echo "Start all services with tmux:"
echo "  ./start.sh auto"
echo ""
echo "Or start manually in 3 terminals:"
echo ""
echo "  Terminal 1 (ComfyUI):"
echo "    cd 3d_gen"
echo "    source .venv/bin/activate"
echo "    cd ComfyUI"
echo "    python main.py --listen 0.0.0.0 --port 8188"
echo ""
echo "  Terminal 2 (Upload Server):"
echo "    source /workspace/isaac_venv/bin/activate"
echo "    python 3d_gen/image_collection/run.py"
echo ""
echo "  Terminal 3 (Isaac Lab - for testing):"
echo "    source /workspace/isaac_venv/bin/activate"
echo "    cd /workspace/IsaacLab"
echo "    ./isaaclab.sh -p"
echo ""
echo "Access the web interface:"
echo "  http://localhost:49100"
echo ""
echo -e "${YELLOW}Documentation:${NC}"
echo "  • README.md - Project overview"
echo "  • CLAUDE.md - Development guide"
echo "  • SINGLE_INSTANCE_SETUP.md - Setup reference"
echo ""
echo "Have fun converting photos to 3D physics simulations!"
echo ""
