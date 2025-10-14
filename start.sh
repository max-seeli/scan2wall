#!/bin/bash

# scan2wall startup script
# Launches ComfyUI and upload server

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Paths
VENV_DIR="/workspace/scan2wall/isaac/venv"
ISAAC_LAB_DIR="/workspace/scan2wall/isaac/IsaacLab"

echo "=========================================="
echo "       scan2wall Startup"
echo "=========================================="
echo ""

# ============================================================================
# Environment Validation
# ============================================================================

echo "Validating environment..."
echo ""

# Check if .env exists
if [ ! -f ".env" ]; then
    echo -e "${RED}✗ .env file not found${NC}"

    if [ -f ".env.example" ]; then
        echo ""
        echo "Creating .env from .env.example..."
        cp .env.example .env
        echo ""
        echo -e "${YELLOW}Please edit .env and add your GOOGLE_API_KEY${NC}"
        echo "Get it from: https://aistudio.google.com/app/apikey"
        echo ""
        echo "Then run this script again."
        exit 1
    else
        echo -e "${RED}✗ .env.example not found${NC}"
        echo "Please run setup first: ./setup.sh"
        exit 1
    fi
fi

# Check if GOOGLE_API_KEY is set
if ! grep -q "^GOOGLE_API_KEY=.*[a-zA-Z0-9]" ".env"; then
    echo -e "${RED}✗ GOOGLE_API_KEY not set in .env${NC}"
    echo ""
    echo "Please edit .env and add your Gemini API key:"
    echo "  nano .env"
    echo ""
    echo "Get your key from: https://aistudio.google.com/app/apikey"
    exit 1
fi

echo -e "${GREEN}✓${NC} Environment configured"

# Check if ComfyUI is set up
if [ ! -d "3d_gen/ComfyUI" ]; then
    echo -e "${RED}✗ ComfyUI not found${NC}"
    echo ""
    echo "Please run setup first:"
    echo "  cd 3d_gen && bash setup_comfyui.sh && bash modeldownload.sh"
    echo ""
    echo "Or run complete setup:"
    echo "  ./setup.sh"
    exit 1
fi

echo -e "${GREEN}✓${NC} ComfyUI found"

# Check if Isaac Lab is set up
if [ ! -d "$ISAAC_LAB_DIR" ]; then
    echo -e "${RED}✗ Isaac Lab not found at $ISAAC_LAB_DIR${NC}"
    echo ""
    echo "Please run setup first:"
    echo "  ./setup_isaac.sh"
    echo ""
    echo "Or run complete setup:"
    echo "  ./setup.sh"
    exit 1
fi

echo -e "${GREEN}✓${NC} Isaac Lab found"

# Check if isaac_venv exists
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${RED}✗ isaac_venv not found at $VENV_DIR${NC}"
    echo ""
    echo "Please run setup first:"
    echo "  ./setup_isaac.sh"
    exit 1
fi

echo -e "${GREEN}✓${NC} isaac_venv found"

# Check if ComfyUI venv exists
if [ ! -d "3d_gen/.venv" ]; then
    echo -e "${RED}✗ ComfyUI venv not found${NC}"
    echo ""
    echo "Please run: cd 3d_gen && bash setup_comfyui.sh"
    exit 1
fi

echo -e "${GREEN}✓${NC} ComfyUI venv found"

# Check port availability
check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        return 1  # Port is in use
    fi
    return 0  # Port is free
}

if ! check_port 8188; then
    echo -e "${YELLOW}⚠ Port 8188 is already in use (ComfyUI)${NC}"
    echo "Kill existing process? (y/N)"
    read -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        lsof -ti:8188 | xargs kill -9 2>/dev/null || true
        sleep 1
        echo -e "${GREEN}✓${NC} Port 8188 freed"
    else
        echo "Please free port 8188 manually and try again"
        exit 1
    fi
else
    echo -e "${GREEN}✓${NC} Port 8188 available"
fi

if ! check_port 49100; then
    echo -e "${YELLOW}⚠ Port 49100 is already in use (Upload server)${NC}"
    echo "Kill existing process? (y/N)"
    read -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        lsof -ti:49100 | xargs kill -9 2>/dev/null || true
        sleep 1
        echo -e "${GREEN}✓${NC} Port 49100 freed"
    else
        echo "Please free port 49100 manually and try again"
        exit 1
    fi
else
    echo -e "${GREEN}✓${NC} Port 49100 available"
fi

echo ""
echo -e "${GREEN}All validations passed!${NC}"
echo ""

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "Shutting down scan2wall..."
    # Kill background processes
    jobs -p | xargs -r kill 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start services based on mode
MODE="${1:-manual}"

if [ "$MODE" = "auto" ] || [ "$MODE" = "tmux" ]; then
    # Automated mode with tmux
    echo "Starting services in tmux session..."

    if ! command -v tmux &> /dev/null; then
        echo -e "${YELLOW}⚠  tmux not installed. Falling back to manual mode.${NC}"
        MODE="manual"
    else
        # Create new tmux session
        SESSION="scan2wall"

        # Kill existing session if it exists
        tmux kill-session -t $SESSION 2>/dev/null || true

        echo "Starting ComfyUI..."
        # Create new session with ComfyUI
        tmux new-session -d -s $SESSION -n "comfyui" "cd $SCRIPT_DIR/3d_gen && source .venv/bin/activate && cd ComfyUI && python main.py --listen 0.0.0.0 --port 8188"

        # Wait for ComfyUI to be ready
        echo "Waiting for ComfyUI to start..."
        MAX_WAIT=60
        WAITED=0
        while [ $WAITED -lt $MAX_WAIT ]; do
            if curl -s http://localhost:8188 > /dev/null 2>&1; then
                echo -e "${GREEN}✓${NC} ComfyUI is ready"
                break
            fi
            sleep 2
            WAITED=$((WAITED + 2))
            echo -n "."
        done
        echo ""

        if [ $WAITED -ge $MAX_WAIT ]; then
            echo -e "${YELLOW}⚠ ComfyUI took longer than expected to start${NC}"
            echo "Continuing anyway..."
        fi

        echo "Starting upload server..."
        # Create new window for upload server (using isaac_venv)
        tmux new-window -t $SESSION -n "upload" "cd $SCRIPT_DIR && source $VENV_DIR/bin/activate && python 3d_gen/image_collection/run.py"

        # Wait a moment for upload server to start
        sleep 3

        # Create status window
        tmux new-window -t $SESSION -n "status" "cd $SCRIPT_DIR && bash -c 'echo \"=========================================\"; echo \"scan2wall Services Running\"; echo \"=========================================\"; echo \"\"; echo \"ComfyUI:      http://localhost:8188\"; echo \"Upload:       http://localhost:49100\"; echo \"\"; echo \"Switch windows: Ctrl+B then number key\"; echo \"  0: ComfyUI\"; echo \"  1: Upload Server\"; echo \"  2: This status\"; echo \"\"; echo \"Press Ctrl+B then D to detach\"; echo \"Press Ctrl+C to stop all services\"; echo \"\"; echo \"Checking service health...\"; echo \"\"; curl -s http://localhost:8188 > /dev/null && echo \"✓ ComfyUI:  OK\" || echo \"✗ ComfyUI:  DOWN\"; curl -s http://localhost:49100 > /dev/null && echo \"✓ Upload:   OK\" || echo \"✗ Upload:   DOWN\"; echo \"\"; tail -f /dev/null'"

        # Attach to session
        echo ""
        echo -e "${GREEN}✓${NC} Services started in tmux"
        echo ""
        echo "Services:"
        echo "  • ComfyUI:       http://localhost:8188"
        echo "  • Upload server: http://localhost:49100"
        echo ""
        echo "Attaching to tmux session..."
        echo "Use Ctrl+B then number to switch windows"
        echo "Use Ctrl+B then D to detach (services keep running)"
        echo ""
        sleep 2
        tmux attach-session -t $SESSION
        exit 0
    fi
fi

# Background mode (not recommended but available)
if [ "$MODE" = "background" ]; then
    echo "Starting services in background..."

    # Create logs directory
    mkdir -p "$SCRIPT_DIR/logs"

    # Start ComfyUI
    cd "$SCRIPT_DIR/3d_gen"
    source .venv/bin/activate
    cd ComfyUI
    nohup python main.py --listen 0.0.0.0 --port 8188 > "$SCRIPT_DIR/logs/comfyui.log" 2>&1 &
    COMFYUI_PID=$!
    echo -e "${GREEN}✓${NC} ComfyUI started (PID: $COMFYUI_PID)"

    # Start upload server (using scan2wall)
    cd "$SCRIPT_DIR"
    source "$VENV_DIR/bin/activate"
    nohup python 3d_gen/image_collection/run.py > "$SCRIPT_DIR/logs/upload.log" 2>&1 &
    UPLOAD_PID=$!
    echo -e "${GREEN}✓${NC} Upload server started (PID: $UPLOAD_PID)"

    echo ""
    echo "Services running in background"
    echo "Logs:"
    echo "  ComfyUI: $SCRIPT_DIR/logs/comfyui.log"
    echo "  Upload:  $SCRIPT_DIR/logs/upload.log"
    echo ""
    echo "To stop services:"
    echo "  kill $COMFYUI_PID $UPLOAD_PID"
    echo ""
    echo "Access:"
    echo "  • ComfyUI:  http://localhost:8188"
    echo "  • Upload:   http://localhost:49100"

    # Save PIDs
    echo "$COMFYUI_PID" > "$SCRIPT_DIR/.comfyui.pid"
    echo "$UPLOAD_PID" > "$SCRIPT_DIR/.upload.pid"

    exit 0
fi

echo "Unknown mode: $MODE"
echo "Usage: ./start.sh [manual|auto|background]"
exit 1
