#!/bin/bash
set -e  # Exit on error

echo "=========================================="
echo "Isaac Sim + Isaac Lab Docker Setup"
echo "=========================================="
echo ""
echo "This script will:"
echo "  1. Check Docker prerequisites"
echo "  2. Clone isaac-launchable (if needed)"
echo "  3. Start Isaac Lab Docker containers"
echo "  4. Verify containers are running"
echo "  5. Configure environment variables"
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running non-interactively (from setup.sh or piped input)
NON_INTERACTIVE=false
if [ ! -t 0 ]; then
    NON_INTERACTIVE=true
fi

# Installation directories (within project)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
ISAAC_DIR="$PROJECT_ROOT/isaac"
ISAAC_LAUNCHABLE_DIR="$ISAAC_DIR/isaac-launchable"
ISAAC_LAB_COMPOSE_DIR="$ISAAC_LAUNCHABLE_DIR/isaac-lab"

echo "Installing Isaac Lab (Docker) in: $ISAAC_DIR"
echo ""

# Create isaac directory
mkdir -p "$ISAAC_DIR"

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

# Check for Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Error: Docker not found${NC}"
    echo ""
    echo "Please install Docker:"
    echo "  curl -fsSL https://get.docker.com | sh"
    echo "  sudo usermod -aG docker \$USER"
    echo "  newgrp docker"
    exit 1
fi
echo -e "${GREEN}✓${NC} Docker installed: $(docker --version)"

# Check for nvidia-container-toolkit
if ! docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi &> /dev/null; then
    echo -e "${RED}✗ Error: NVIDIA Container Toolkit not properly configured${NC}"
    echo ""
    echo "Please install NVIDIA Container Toolkit:"
    echo "  sudo apt-get update"
    echo "  sudo apt-get install -y nvidia-container-toolkit"
    echo "  sudo systemctl restart docker"
    exit 1
fi
echo -e "${GREEN}✓${NC} NVIDIA Container Toolkit configured"

# Check disk space (need at least 50GB for Docker images)
AVAILABLE_SPACE=$(df -BG "$PROJECT_ROOT" | tail -1 | awk '{print $4}' | sed 's/G//')
if [ "$AVAILABLE_SPACE" -lt 50 ]; then
    echo -e "${YELLOW}⚠${NC} Warning: Low disk space. Have ${AVAILABLE_SPACE}GB, recommend 50GB+"
    if [ "$NON_INTERACTIVE" = true ]; then
        echo "Continuing anyway (non-interactive mode)..."
    else
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
else
    echo -e "${GREEN}✓${NC} Disk space: ${AVAILABLE_SPACE}GB available"
fi

echo ""
echo -e "${GREEN}All prerequisites satisfied!${NC}"
echo ""

# ============================================================================
# Clone isaac-launchable
# ============================================================================

if [ -d "$ISAAC_LAUNCHABLE_DIR" ]; then
    echo -e "${GREEN}✓${NC} isaac-launchable already exists at $ISAAC_LAUNCHABLE_DIR"
    cd "$ISAAC_LAUNCHABLE_DIR"

    # Check if it's a git repo and optionally pull updates
    if [ -d ".git" ]; then
        echo "Checking for updates..."
        git fetch origin --quiet
        LOCAL=$(git rev-parse HEAD)
        REMOTE=$(git rev-parse origin/main 2>/dev/null || git rev-parse origin/master 2>/dev/null)

        if [ "$LOCAL" != "$REMOTE" ]; then
            if [ "$NON_INTERACTIVE" = true ]; then
                echo "Updates available - skipping (non-interactive mode)"
            else
                echo -e "${YELLOW}Updates available. Pull latest changes? (y/N)${NC}"
                read -p "> " -n 1 -r
                echo
                if [[ $REPLY =~ ^[Yy]$ ]]; then
                    git pull
                    echo -e "${GREEN}✓${NC} Updated to latest version"
                fi
            fi
        else
            echo -e "${GREEN}✓${NC} Already up to date"
        fi
    fi
else
    echo "Cloning isaac-launchable repository..."
    cd "$ISAAC_DIR"
    git clone https://github.com/isaac-sim/isaac-launchable.git
    echo -e "${GREEN}✓${NC} isaac-launchable cloned to $ISAAC_LAUNCHABLE_DIR"
fi

echo ""

# ============================================================================
# Configure Docker Compose for localhost
# ============================================================================

echo "Configuring Docker Compose for localhost..."
cd "$ISAAC_LAB_COMPOSE_DIR"

# Update ENV=brev to ENV=localhost in docker-compose.yml
if grep -q "ENV=brev" docker-compose.yml; then
    sed -i 's/ENV=brev/ENV=localhost/' docker-compose.yml
    echo -e "${GREEN}✓${NC} Updated docker-compose.yml for localhost"
else
    echo -e "${GREEN}✓${NC} docker-compose.yml already configured for localhost"
fi

echo ""

# ============================================================================
# Configure Docker Logging
# ============================================================================

echo "Configuring Docker container logging and volume mounts..."

# Create data directory for Docker mount (prevents Docker from creating it as root)
mkdir -p "$PROJECT_ROOT/data"
echo -e "${GREEN}✓${NC} Created data directory for Docker volume mount"

# Check if docker-compose.override.yml is already properly configured
if [ -f "$ISAAC_LAB_COMPOSE_DIR/docker-compose.override.yml" ] && \
   grep -q "logging:" "$ISAAC_LAB_COMPOSE_DIR/docker-compose.override.yml" && \
   grep -q "/workspace/scan2wall" "$ISAAC_LAB_COMPOSE_DIR/docker-compose.override.yml"; then
    echo -e "${GREEN}✓${NC} Docker configuration already complete"
else
    # Backup existing file if it exists
    if [ -f "$ISAAC_LAB_COMPOSE_DIR/docker-compose.override.yml" ]; then
        echo -e "${YELLOW}⚠${NC} Backing up existing docker-compose.override.yml"
        cp "$ISAAC_LAB_COMPOSE_DIR/docker-compose.override.yml" "$ISAAC_LAB_COMPOSE_DIR/docker-compose.override.yml.backup.$(date +%s)"
    fi

    # Create simplified override file with s2w-data mount and logging
    cat > "$ISAAC_LAB_COMPOSE_DIR/docker-compose.override.yml" << EOF
# Auto-generated by scan2wall setup
# Configures s2w-data volume and persistent logging for containers

services:
  vscode:
    build:
      context: ./vscode
      network: host
    volumes:
      - '$PROJECT_ROOT/isaac/isaac_scripts:/workspace/s2w-scripts:rw'
      - '$PROJECT_ROOT/data:/workspace/s2w-data:rw'
    ports:
      - "8080:8080"
    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "3"

  web-viewer:
    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "3"

  nginx:
    build:
      context: ./nginx
      network: host
    ports:
      - \$DEV_NGINX_PORT:80
    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "3"
EOF

    echo -e "${GREEN}✓${NC} Docker configuration complete:"
    echo "  • Volume mount: scan2wall/data → /workspace/s2w-data"
    echo "  • Logging: 50MB × 3 files per container"
fi
echo ""

# ============================================================================
# Start Docker Containers
# ============================================================================

echo "Starting Isaac Lab Docker containers..."
echo -e "${YELLOW}This will download Docker images (~10-15GB) on first run${NC}"
echo ""

# Check if containers are already running
if docker ps | grep -q "vscode"; then
    if [ "$NON_INTERACTIVE" = true ]; then
        echo "Containers already running - keeping existing containers"
    else
        echo -e "${YELLOW}Containers already running. Restart? (y/N)${NC}"
        read -p "> " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "Stopping existing containers..."
            docker compose down
            echo "Starting fresh containers..."
            docker compose up -d
        else
            echo "Keeping existing containers running"
        fi
    fi
else
    docker compose up -d
fi

echo ""
echo -e "${GREEN}✓${NC} Docker containers started"
echo ""

# Wait for containers to be ready
echo "Waiting for containers to be ready..."
sleep 5

# ============================================================================
# Verify Containers
# ============================================================================

echo "Verifying containers..."
echo ""

REQUIRED_CONTAINERS=("vscode" "web-viewer")
ALL_RUNNING=true

for container in "${REQUIRED_CONTAINERS[@]}"; do
    if docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        echo -e "${GREEN}✓${NC} Container running: $container"
    else
        echo -e "${RED}✗${NC} Container not running: $container"
        ALL_RUNNING=false
    fi
done

# Check for nginx container (has isaac-lab prefix)
if docker ps --format '{{.Names}}' | grep -q "nginx"; then
    echo -e "${GREEN}✓${NC} Container running: nginx (isaac-lab-nginx-1)"
else
    echo -e "${RED}✗${NC} Container not running: nginx"
    ALL_RUNNING=false
fi

if [ "$ALL_RUNNING" = false ]; then
    echo ""
    echo -e "${RED}Some containers failed to start. Check logs:${NC}"
    echo "  docker logs vscode"
    echo "  docker logs web-viewer"
    echo "  docker logs nginx"
    exit 1
fi

echo ""

# ============================================================================
# Install ffmpeg in Container
# ============================================================================

echo "Installing ffmpeg in vscode container for video encoding..."
docker exec vscode bash -c "apt-get update -qq && apt-get install -y ffmpeg" > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} ffmpeg installed in vscode container"
else
    echo -e "${YELLOW}⚠${NC} Could not install ffmpeg automatically. You may need to install it manually."
fi
echo ""

# ============================================================================
# Configure scan2wall Environment
# ============================================================================

echo "Configuring scan2wall environment..."
cd "$PROJECT_ROOT"

# Update .env if it exists, otherwise update .env.example
if [ -f ".env" ]; then
    ENV_FILE=".env"
else
    ENV_FILE=".env.example"
fi

# Update Isaac workspace path (Docker container path)
if grep -q "^ISAAC_WORKSPACE=" "$ENV_FILE"; then
    sed -i "s|^ISAAC_WORKSPACE=.*|ISAAC_WORKSPACE=/workspace/isaaclab|" "$ENV_FILE"
else
    echo "ISAAC_WORKSPACE=/workspace/isaaclab" >> "$ENV_FILE"
fi

echo -e "${GREEN}✓${NC} Environment configured in $ENV_FILE"
echo ""

# ============================================================================
# Verification
# ============================================================================

echo "Verifying installation..."
echo ""

# Test if we can exec into the container
if docker exec vscode bash -c "ls /workspace/isaaclab" &> /dev/null; then
    echo -e "${GREEN}✓${NC} Can access Isaac Lab in container"
else
    echo -e "${RED}✗${NC} Cannot access Isaac Lab in container"
    echo "Check container logs: docker logs vscode"
    exit 1
fi

# Test if isaaclab.sh exists
if docker exec vscode bash -c "test -f /workspace/isaaclab/isaaclab.sh" &> /dev/null; then
    echo -e "${GREEN}✓${NC} Isaac Lab executable found in container"
else
    echo -e "${RED}✗${NC} Isaac Lab executable not found in container"
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
echo "  • Docker containers: Running"
echo "    - vscode: Development environment"
echo "    - web-viewer: Streaming UI"
echo "    - nginx: Reverse proxy"
echo "  • Isaac Sim: Pre-installed in container at /isaac-sim"
echo "  • Isaac Lab: Pre-installed at /workspace/isaaclab"
echo ""
echo "Container management:"
echo ""
echo "  Start containers:"
echo "    cd $ISAAC_LAB_COMPOSE_DIR"
echo "    docker compose up -d"
echo ""
echo "  Stop containers:"
echo "    docker compose down"
echo ""
echo "  Access Isaac Lab environment:"
echo "    docker exec -it vscode bash"
echo ""
echo "  View logs:"
echo "    docker logs vscode"
echo "    docker logs web-viewer"
echo ""
echo "Next steps:"
echo ""
echo "1. Test Isaac Lab in container:"
echo "   docker exec -it vscode bash"
echo "   cd /workspace/isaaclab"
echo "   ./isaaclab.sh --help"
echo ""
echo "2. Continue scan2wall setup:"
echo "   cd $PROJECT_ROOT"
echo "   ./scan2wall/scripts/install/scan2wall.sh"
echo ""
echo -e "${YELLOW}Note:${NC} Isaac Lab now runs in Docker containers"
echo "      Access via: docker exec -it vscode bash"
echo ""
