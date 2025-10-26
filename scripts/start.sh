#!/bin/bash

# scan2wall startup script
# Launches ComfyUI and upload server

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Paths
ISAAC_DIR="$PROJECT_ROOT/isaac"
ISAAC_LAUNCHABLE_DIR="$ISAAC_DIR/isaac-launchable"
ISAAC_LAB_COMPOSE_DIR="$ISAAC_LAUNCHABLE_DIR/isaac-lab"

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

# Check if Isaac Lab Docker setup exists
if [ ! -d "$ISAAC_LAB_COMPOSE_DIR" ]; then
    echo -e "${RED}✗ Isaac Lab Docker setup not found at $ISAAC_LAB_COMPOSE_DIR${NC}"
    echo ""
    echo "Please run setup first:"
    echo "  ./scan2wall/scripts/install/isaac.sh"
    echo ""
    echo "Or run complete setup:"
    echo "  ./setup.sh"
    exit 1
fi

echo -e "${GREEN}✓${NC} Isaac Lab Docker setup found"

# Check if Docker containers are running
REQUIRED_CONTAINERS=("vscode" "web-viewer")
ALL_RUNNING=true

for container in "${REQUIRED_CONTAINERS[@]}"; do
    if ! docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        echo -e "${YELLOW}⚠ Docker container not running: $container${NC}"
        ALL_RUNNING=false
    fi
done

# Check nginx (has isaac-lab prefix)
if ! docker ps --format '{{.Names}}' | grep -q "nginx"; then
    echo -e "${YELLOW}⚠ Docker container not running: nginx${NC}"
    ALL_RUNNING=false
fi

if [ "$ALL_RUNNING" = false ]; then
    echo ""
    echo "Starting Isaac Lab Docker containers..."
    cd "$ISAAC_LAB_COMPOSE_DIR"
    docker compose up -d
    sleep 5
    echo -e "${GREEN}✓${NC} Docker containers started"
    cd "$PROJECT_ROOT"
else
    echo -e "${GREEN}✓${NC} Isaac Lab Docker containers running"
fi

# ------------------------------------------------------------------------------
# Start persistent Isaac worker (FastAPI)
# ------------------------------------------------------------------------------
echo ""
echo "Starting persistent Isaac worker (FastAPI)..."

# Kill any existing Isaac workers first
echo "Checking for existing Isaac workers..."
if docker exec vscode pgrep -f isaac_worker.py > /dev/null 2>&1; then
    echo "Killing existing Isaac worker..."
    docker exec vscode pkill -9 -f isaac_worker.py
    sleep 3
fi

# Now start fresh
docker exec -d vscode bash -c \
"cd /workspace/s2w-scripts && nohup /workspace/isaaclab/isaaclab.sh -p isaac_worker.py > /workspace/s2w-data/logs/isaac_worker.log 2>&1 &"

# Give it a few seconds to initialize
sleep 5

# Ensure ffmpeg is installed
echo "Checking for ffmpeg in Isaac container..."
if ! docker exec vscode which ffmpeg > /dev/null 2>&1; then
    echo "Installing ffmpeg..."
    docker exec vscode bash -c "apt-get update -qq && apt-get install -y ffmpeg"
    echo -e "${GREEN}✓${NC} ffmpeg installed"
else
    echo -e "${GREEN}✓${NC} ffmpeg already installed"
fi

# ------------------------------------------------------------------------------
# ComfyUI
# ------------------------------------------------------------------------------
# Check if ComfyUI venv exists
if [ ! -d "3d_gen/.venv" ]; then
    echo -e "${RED}✗ ComfyUI venv not found${NC}"
    echo ""
    echo "Please run: cd 3d_gen && bash setup_comfyui.sh"
    exit 1
fi

echo -e "${GREEN}✓${NC} ComfyUI venv found"

# Check port availability (detects all usage: LISTEN + ESTABLISHED)
check_port() {
    local port=$1
    if lsof -Pi :$port -t >/dev/null 2>&1; then
        return 1  # Port is in use
    fi
    return 0  # Port is free
}

# Find next available port starting from a base
find_free_port() {
    local base_port=$1
    local max_tries=${2:-10}

    for ((i=0; i<max_tries; i++)); do
        local port=$((base_port + i))
        if check_port $port; then
            echo $port
            return 0
        fi
    done

    return 1  # No free port found
}

# Check ComfyUI port
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

# Check upload server port (auto-find if 49100 is busy)
UPLOAD_PORT=49100
if ! check_port 49100; then
    # Get what's using the port
    BLOCKING_PROCESS=$(lsof -Pi :49100 -t 2>/dev/null | head -1)
    BLOCKING_NAME=$(ps -p $BLOCKING_PROCESS -o comm= 2>/dev/null || echo "unknown")

    echo -e "${YELLOW}⚠ Port 49100 is in use by $BLOCKING_NAME (PID: $BLOCKING_PROCESS)${NC}"
    echo "Finding next available port..."

    UPLOAD_PORT=$(find_free_port 49101)
    if [ -z "$UPLOAD_PORT" ]; then
        echo -e "${RED}✗ Could not find free port in range 49101-49110${NC}"
        exit 1
    fi

    echo -e "${GREEN}✓${NC} Using port $UPLOAD_PORT instead"

    # Update .env with new port
    if [ -f ".env" ]; then
        if grep -q "^PORT=" ".env"; then
            sed -i "s/^PORT=.*/PORT=$UPLOAD_PORT/" ".env"
        else
            echo "PORT=$UPLOAD_PORT" >> ".env"
        fi
        echo -e "${GREEN}✓${NC} Updated .env with PORT=$UPLOAD_PORT"
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
    # Kill background processes (including Docker log capture)
    jobs -p | xargs -r kill 2>/dev/null || true
    # Kill any docker logs -f processes
    pkill -f "docker logs -f" 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

# Check if tmux is installed, if not install it
if ! command -v tmux &> /dev/null; then
    echo -e "${YELLOW}⚠  tmux not installed. Installing...${NC}"
    if command -v apt-get &> /dev/null; then
        sudo apt-get update -qq && sudo apt-get install -y tmux
    elif command -v yum &> /dev/null; then
        sudo yum install -y tmux
    else
        echo -e "${RED}✗ Could not install tmux automatically${NC}"
        echo "Please install tmux manually: sudo apt-get install tmux"
        exit 1
    fi
    echo -e "${GREEN}✓${NC} tmux installed"
fi

echo "Starting services in tmux session..."
echo ""

# Start services with tmux
# Create new tmux session
SESSION="scan2wall"

# Kill existing session if it exists
tmux kill-session -t $SESSION 2>/dev/null || true

# Create logs directory
mkdir -p "$PROJECT_ROOT/data/logs"

# Create test directories for scan2wall test pipeline
mkdir -p "$PROJECT_ROOT/data/test"/{images,segmented,meshes,texturedmeshes,usd,videos}

echo "Starting ComfyUI..."
# Create new session with ComfyUI (with logging)
tmux new-session -d -s $SESSION -n "comfyui" "cd $PROJECT_ROOT/3d_gen && source .venv/bin/activate && cd ComfyUI && python main.py --listen 0.0.0.0 --port 8188 2>&1 | tee $PROJECT_ROOT/data/logs/comfyui.log"

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
# Create new window for upload server (with logging)
tmux new-window -t $SESSION -n "upload" "cd $PROJECT_ROOT && source .venv/bin/activate && PORT=$UPLOAD_PORT python -m scan2wall.server.run 2>&1 | tee $PROJECT_ROOT/data/logs/upload.log"

# Wait a moment for upload server to start
sleep 3

# Start Docker log capture in background
echo "Starting Docker log capture..."
docker logs -f vscode >> "$PROJECT_ROOT/data/logs/isaac_vscode.log" 2>&1 &
docker logs -f web-viewer >> "$PROJECT_ROOT/data/logs/isaac_webviewer.log" 2>&1 &
docker logs -f isaac-lab-nginx-1 >> "$PROJECT_ROOT/data/logs/isaac_nginx.log" 2>&1 &

# Create status window
tmux new-window -t $SESSION -n "status" "cd $PROJECT_ROOT && bash -c 'echo \"=========================================\"; echo \"scan2wall Services Running\"; echo \"=========================================\"; echo \"\"; echo \"ComfyUI:      http://localhost:8188\"; echo \"Upload:       http://localhost:$UPLOAD_PORT\"; echo \"\"; echo \"Switch windows: Ctrl+B then number key\"; echo \"  0: ComfyUI\"; echo \"  1: Upload Server\"; echo \"  2: This status\"; echo \"\"; echo \"Press Ctrl+B then D to detach\"; echo \"Press Ctrl+C to stop all services\"; echo \"\"; echo \"Checking service health...\"; echo \"\"; curl -s http://localhost:8188 > /dev/null && echo \"✓ ComfyUI:  OK\" || echo \"✗ ComfyUI:  DOWN\"; curl -s http://localhost:$UPLOAD_PORT > /dev/null && echo \"✓ Upload:   OK\" || echo \"✗ Upload:   DOWN\"; echo \"\"; echo \"Docker logs available:\"; echo \"  docker logs vscode\"; echo \"  docker logs web-viewer\"; echo \"  docker logs isaac-lab-nginx-1\"; echo \"\"; tail -f /dev/null'"

# Attach to session
echo ""
echo -e "${GREEN}✓${NC} Services started in tmux"
echo ""
echo "Services:"
echo "  • ComfyUI:       http://localhost:8188"
echo "  • Upload server: http://localhost:$UPLOAD_PORT"
echo ""
echo "Application logs:"
echo "  • $PROJECT_ROOT/data/logs/comfyui.log"
echo "  • $PROJECT_ROOT/data/logs/upload.log"
echo "  • $PROJECT_ROOT/data/logs/isaac_vscode.log"
echo "  • $PROJECT_ROOT/data/logs/isaac_webviewer.log"
echo "  • $PROJECT_ROOT/data/logs/isaac_nginx.log"
echo ""
echo "Docker logs (persistent with rotation):"
echo "  • docker logs vscode"
echo "  • docker logs web-viewer"
echo "  • docker logs isaac-lab-nginx-1"
echo ""
echo "Attaching to tmux session..."
echo "Use Ctrl+B then number to switch windows"
echo "Use Ctrl+B then D to detach (services keep running)"
echo ""
sleep 2
tmux attach-session -t $SESSION