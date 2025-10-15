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
echo "  Phase 1: Isaac Sim + Isaac Lab (Docker)"
echo "    • Check Docker prerequisites"
echo "    • Clone isaac-launchable repository"
echo "    • Start Isaac Lab Docker containers"
echo "    • Verify container health"
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

echo "Estimated total time: 25-35 minutes"
echo "  (first time: ~15min for Docker image download)"
echo "Required disk space: ~50GB (Docker images + models)"
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
# Phase 1: Isaac Sim + Isaac Lab (Docker)
# ============================================================================

echo ""
echo "=========================================="
echo "Phase 1: Isaac Sim + Isaac Lab (Docker)"
echo "=========================================="
echo ""

if [ -f "./scan2wall/scripts/install/isaac.sh" ]; then
    bash ./scan2wall/scripts/install/isaac.sh $MINIMAL_INSTALL_FLAG
else
    echo -e "${RED}✗ Error: scripts/install/isaac.sh not found${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}✓ Phase 1 Complete - Docker containers running${NC}"
echo ""

# ============================================================================
# Phase 2: ComfyUI Setup
# ============================================================================

echo ""
echo "=========================================="
echo "Phase 2: ComfyUI (3D Generation)"
echo "=========================================="
echo ""

if [ -f "./scan2wall/scripts/install/comfyui.sh" ]; then
    bash ./scan2wall/scripts/install/comfyui.sh
    

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

if [ -f "./scan2wall/scripts/install/scan2wall.sh" ]; then
    bash ./scan2wall/scripts/install/scan2wall.sh
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
echo "  ✓ Docker containers (Isaac Sim + Isaac Lab)"
echo "    - vscode container (development environment)"
echo "    - web-viewer container (streaming UI)"
echo "    - nginx container (reverse proxy)"
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
echo "    source .venv/bin/activate"
echo "    python 3d_gen/image_collection/run.py"
echo ""
echo "  Terminal 3 (Isaac Lab - for testing):"
echo "    docker exec -it vscode bash"
echo "    cd /workspace/isaaclab"
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
