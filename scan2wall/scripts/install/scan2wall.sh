#!/bin/bash
set -e  # Exit on error

echo "=========================================="
echo "scan2wall Package Setup"
echo "=========================================="
echo ""
echo "This script will:"
echo "  1. Activate isaac_venv"
echo "  2. Install scan2wall as editable package"
echo "  3. Create required directories"
echo "  4. Validate environment configuration"
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Paths (within project structure)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ISAAC_DIR="$PROJECT_DIR/isaac"
VENV_DIR="$ISAAC_DIR/venv"
ISAAC_LAB_DIR="$ISAAC_DIR/IsaacLab"

# ============================================================================
# Check Prerequisites
# ============================================================================

echo "Checking prerequisites..."
echo ""

# Check if isaac_venv exists
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${RED}✗ Error: isaac venv not found at $VENV_DIR${NC}"
    echo ""
    echo "Please run isaac installation first:"
    echo "  ./scripts/install/isaac.sh"
    exit 1
fi
echo -e "${GREEN}✓${NC} isaac_venv found"

# Check if Isaac Lab exists
if [ ! -d "$ISAAC_LAB_DIR" ]; then
    echo -e "${RED}✗ Error: Isaac Lab not found at $ISAAC_LAB_DIR${NC}"
    echo ""
    echo "Please run isaac installation first:"
    echo "  ./scripts/install/isaac.sh"
    exit 1
fi
echo -e "${GREEN}✓${NC} Isaac Lab found"

echo ""

# ============================================================================
# Activate Virtual Environment
# ============================================================================

echo "Activating isaac_venv..."
source "$VENV_DIR/bin/activate"

# Verify Python version
PYTHON_VERSION=$(python --version)
echo -e "${GREEN}✓${NC} Virtual environment activated: $PYTHON_VERSION"
echo ""

# ============================================================================
# Install scan2wall Package
# ============================================================================

cd "$PROJECT_DIR"

echo "Installing scan2wall package in editable mode..."
pip install -e .

echo ""
echo -e "${GREEN}✓${NC} scan2wall package installed"
echo ""

# ============================================================================
# Create Required Directories
# ============================================================================

echo "Creating required directories..."

mkdir -p "$ISAAC_LAB_DIR/usd_files"
echo -e "${GREEN}✓${NC} Created: $ISAAC_LAB_DIR/usd_files"

mkdir -p "$PROJECT_DIR/recordings"
echo -e "${GREEN}✓${NC} Created: $PROJECT_DIR/recordings"

mkdir -p "$PROJECT_DIR/3d_gen/input"
echo -e "${GREEN}✓${NC} Created: $PROJECT_DIR/3d_gen/input"

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
        echo -e "${RED}IMPORTANT: You must edit .env and add your GOOGLE_API_KEY${NC}"
        echo ""
        echo "Get your key from: https://aistudio.google.com/app/apikey"
        echo ""
        echo "Then edit the file:"
        echo "  nano .env"
        echo ""
        exit 1
    else
        echo -e "${RED}✗ Error: .env.example not found${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓${NC} .env file exists"
fi

# Check if GOOGLE_API_KEY is set
if grep -q "^GOOGLE_API_KEY=.*[a-zA-Z0-9]" "$PROJECT_DIR/.env"; then
    echo -e "${GREEN}✓${NC} GOOGLE_API_KEY is configured"
else
    echo -e "${RED}✗ Error: GOOGLE_API_KEY not set in .env${NC}"
    echo ""
    echo "Please edit .env and add your Gemini API key:"
    echo "  nano .env"
    echo ""
    echo "Get your key from: https://aistudio.google.com/app/apikey"
    exit 1
fi

echo ""

# ============================================================================
# Validate Installation
# ============================================================================

echo "Validating installation..."
echo ""

# Test scan2wall import
if python -c "import scan2wall; print(f'scan2wall version: {scan2wall.__version__}')" 2>/dev/null; then
    echo -e "${GREEN}✓${NC} scan2wall package import successful"
else
    echo -e "${RED}✗${NC} scan2wall package import failed"
    exit 1
fi

# Test path configuration
if python -c "from scan2wall import PROJECT_ROOT, ISAAC_WORKSPACE; print(f'Project root: {PROJECT_ROOT}'); print(f'Isaac workspace: {ISAAC_WORKSPACE}')" 2>/dev/null; then
    echo -e "${GREEN}✓${NC} Path configuration successful"
else
    echo -e "${RED}✗${NC} Path configuration failed"
    exit 1
fi

echo ""

# Run full path check
echo "Path Configuration:"
echo "==================="
python -m scan2wall --check

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
echo "  • Environment variables configured"
echo ""
echo "Next steps:"
echo ""
echo "1. Setup ComfyUI (if not already done):"
echo "   cd $PROJECT_DIR"
echo "   bash scripts/install/comfyui.sh"
echo "   cd 3d_gen && bash modeldownload.sh"
echo ""
echo "2. Start the application:"
echo "   cd $PROJECT_DIR"
echo "   ./start.sh auto"
echo ""
echo -e "${YELLOW}Note:${NC} Always activate isaac venv before running the app:"
echo "      source $VENV_DIR/bin/activate"
echo ""
