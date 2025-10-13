#!/bin/bash

# scan2wall startup script
# Launches ComfyUI and upload server

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "=========================================="
echo "       scan2wall Startup"
echo "=========================================="
echo ""

# Check if .env exists
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠  .env file not found. Creating from .env.example...${NC}"
    cp .env.example .env
    echo ""
    echo -e "${YELLOW}Please edit .env and add your GOOGLE_API_KEY${NC}"
    echo "Get it from: https://makersuite.google.com/app/apikey"
    echo ""
    read -p "Press Enter after you've added your API key..."
fi

# Check if setup was done
if [ ! -d "3d_gen/ComfyUI" ]; then
    echo -e "${YELLOW}⚠  ComfyUI not found. Please run setup first:${NC}"
    echo "   cd 3d_gen && bash setup_comfyui.sh && bash modeldownload.sh???"
    exit 1
fi

if [ ! -d "/workspace/isaac" ]; then
    echo -e "${YELLOW}⚠  Isaac Lab not found. Please run setup first:${NC}"
    echo "   bash setup_isaac.sh"
    exit 1
fi

echo -e "${GREEN}✓${NC} Prerequisites verified"
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

        # Create new session with ComfyUI
        tmux new-session -d -s $SESSION -n "comfyui" "cd $SCRIPT_DIR/3d_gen && source .venv/bin/activate && cd ComfyUI && python main.py --listen 0.0.0.0 --port 8188"

        # Create new window for upload server
        tmux new-window -t $SESSION -n "upload" "cd $SCRIPT_DIR && python 3d_gen/image_collection/run.py"

        # Create status window
        tmux new-window -t $SESSION -n "status" "cd $SCRIPT_DIR && bash -c 'echo \"scan2wall Services\"; echo \"\"; echo \"ComfyUI:      http://localhost:8188\"; echo \"Upload:       http://localhost:49100\"; echo \"\"; echo \"Switch windows: Ctrl+B then number key\"; echo \"  0: ComfyUI\"; echo \"  1: Upload Server\"; echo \"  2: This status\"; echo \"\"; echo \"Press Ctrl+B then D to detach\"; echo \"Press Ctrl+C to stop all services\"; echo \"\"; tail -f /dev/null'"

        # Attach to session
        echo -e "${GREEN}✓${NC} Services started in tmux"
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

if [ "$MODE" = "manual" ]; then
    # Manual mode - print instructions
    echo -e "${BLUE}Manual Mode${NC}"
    echo "Open 3 separate terminal windows and run:"
    echo ""
    echo -e "${GREEN}Terminal 1 - ComfyUI:${NC}"
    echo "  cd $(pwd)/3d_gen"
    echo "  source .venv/bin/activate"
    echo "  cd ComfyUI"
    echo "  python main.py --listen 0.0.0.0 --port 8188"
    echo ""
    echo -e "${GREEN}Terminal 2 - Upload Server:${NC}"
    echo "  cd $(pwd)"
    echo "  python 3d_gen/image_collection/run.py"
    echo ""
    echo -e "${GREEN}Terminal 3 - Isaac Lab (ready for scripts):${NC}"
    echo "  cd /workspace/isaac"
    echo "  ./isaaclab.sh -p"
    echo ""
    echo "=========================================="
    echo "Once started, access the app at:"
    echo "  http://localhost:49100"
    echo "=========================================="
    echo ""
    echo "Tip: Run './start.sh auto' for automatic startup with tmux"
    exit 0
fi

# Background mode (not recommended but available)
if [ "$MODE" = "background" ]; then
    echo "Starting services in background..."

    # Start ComfyUI
    cd "$SCRIPT_DIR/3d_gen"
    source .venv/bin/activate
    cd ComfyUI
    nohup python main.py --listen 0.0.0.0 --port 8188 > "$SCRIPT_DIR/logs/comfyui.log" 2>&1 &
    COMFYUI_PID=$!
    echo -e "${GREEN}✓${NC} ComfyUI started (PID: $COMFYUI_PID)"

    # Start upload server
    cd "$SCRIPT_DIR"
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
    echo "Access the app at: http://localhost:49100"

    # Save PIDs
    echo "$COMFYUI_PID" > "$SCRIPT_DIR/.comfyui.pid"
    echo "$UPLOAD_PID" > "$SCRIPT_DIR/.upload.pid"

    exit 0
fi

echo "Unknown mode: $MODE"
echo "Usage: ./start.sh [manual|auto|background]"
exit 1
