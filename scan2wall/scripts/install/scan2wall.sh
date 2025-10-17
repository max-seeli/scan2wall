#!/bin/bash
set -e  # Exit on error

echo "=========================================="
echo "scan2wall Package Setup"
echo "=========================================="
echo ""
echo "This script will:"
echo "  1. Install scan2wall as editable package"
echo "  2. Create required directories"
echo "  3. Validate environment configuration"
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Paths
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
ISAAC_DIR="$PROJECT_DIR/isaac"

# ============================================================================
# Check Prerequisites
# ============================================================================

echo "Checking prerequisites..."
echo ""

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}⚠${NC} uv not found. Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    echo -e "${GREEN}✓${NC} uv installed"
else
    echo -e "${GREEN}✓${NC} uv found: $(uv --version)"
fi

echo ""

# ============================================================================
# Install scan2wall Package
# ============================================================================

cd "$PROJECT_DIR"

# Create virtual environment for scan2wall
echo "Creating virtual environment for scan2wall..."
if [ -d ".venv" ]; then
    echo -e "${GREEN}✓${NC} Virtual environment already exists"
else
    uv venv
    echo -e "${GREEN}✓${NC} Virtual environment created"
fi

echo ""
echo "Installing scan2wall package in editable mode..."
source .venv/bin/activate
uv pip install -e .

echo ""
echo -e "${GREEN}✓${NC} scan2wall package installed"
echo ""

# ============================================================================
# Create Required Directories
# ============================================================================

echo "Creating required directories..."

# USD files directory (mounted into Docker)
mkdir -p "$ISAAC_DIR/usd_files"
echo -e "${GREEN}✓${NC} Created: $ISAAC_DIR/usd_files"

# Recordings directory (for simulation videos)
mkdir -p "$PROJECT_DIR/data/recordings"
echo -e "${GREEN}✓${NC} Created: $PROJECT_DIR/data/recordings"

# ComfyUI input directory
mkdir -p "$PROJECT_DIR/3d_gen/input"
echo -e "${GREEN}✓${NC} Created: $PROJECT_DIR/3d_gen/input"

# Logs directory (for application logs)
mkdir -p "$PROJECT_DIR/data/logs"
echo -e "${GREEN}✓${NC} Created: $PROJECT_DIR/data/logs"

echo ""

# ============================================================================
# Environment Configuration
# ============================================================================

echo "Checking environment configuration..."
echo ""

# Check if .env exists
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo -e "${YELLOW}⚠${NC} .env file not found"

    if [ -f "$PROJECT_DIR/.env.example" ]; then
        echo "Creating .env from .env.example..."
        cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
        echo -e "${GREEN}✓${NC} Created .env file"
        echo ""
        echo -e "${YELLOW}IMPORTANT: You should edit .env and add your GOOGLE_API_KEY${NC}"
        echo ""
        echo "Get your key from: https://aistudio.google.com/app/apikey"
        echo ""
        echo "Then edit the file:"
        echo "  nano .env"
        echo ""
    else
        echo -e "${RED}✗ Error: .env.example not found${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓${NC} .env file exists"
fi

# Check if GOOGLE_API_KEY is set (warning only, not blocking)
if grep -q "^GOOGLE_API_KEY=.*[a-zA-Z0-9]" "$PROJECT_DIR/.env" && ! grep -q "your_gemini_api_key_here" "$PROJECT_DIR/.env"; then
    echo -e "${GREEN}✓${NC} GOOGLE_API_KEY is configured"
else
    echo -e "${YELLOW}⚠${NC} GOOGLE_API_KEY not configured in .env"
    echo "  You'll need to add it before running the pipeline"
    echo "  Get your key from: https://aistudio.google.com/app/apikey"
fi

echo ""

# ============================================================================
# Validate Installation
# ============================================================================

echo "Validating installation..."
echo ""

# Activate venv for validation
source .venv/bin/activate

# Test scan2wall import
if python -c "import scan2wall; print(f'scan2wall version: {scan2wall.__version__}')" 2>/dev/null; then
    echo -e "${GREEN}✓${NC} scan2wall package import successful"
else
    echo -e "${YELLOW}⚠${NC} scan2wall package import had issues (this may be okay if dependencies aren't fully installed yet)"
fi

# Test path configuration
if python -c "from scan2wall.utils.paths import get_project_root, get_isaac_workspace; print(f'Project root: {get_project_root()}'); print(f'Isaac workspace: {get_isaac_workspace()}')" 2>/dev/null; then
    echo -e "${GREEN}✓${NC} Path configuration successful"
else
    echo -e "${YELLOW}⚠${NC} Path configuration check skipped"
fi

echo ""

# ============================================================================
# Success Message
# ============================================================================

echo "=========================================="
echo -e "${GREEN}scan2wall Setup Complete!${NC}"
echo "=========================================="
echo ""
echo "Summary:"
echo "  • scan2wall package installed in editable mode"
echo "  • All required directories created"
echo "  • Environment file configured"
echo ""
echo "Next steps:"
echo ""
echo "1. Setup ComfyUI (if not already done):"
echo "   cd $PROJECT_DIR"
echo "   bash scan2wall/scripts/install/comfyui.sh"
echo "   cd 3d_gen && bash modeldownload.sh"
echo ""
echo "2. Add your Gemini API key to .env:"
echo "   nano .env"
echo ""
echo "3. Start the application:"
echo "   cd $PROJECT_DIR"
echo "   ./start.sh auto"
echo ""
echo -e "${YELLOW}Note:${NC} Isaac Lab runs in Docker containers"
echo "      Containers should already be running from isaac.sh"
echo ""
