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
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ISAAC_DIR="$PROJECT_ROOT/isaac"
ISAAC_LAUNCHABLE_DIR="$ISAAC_DIR/isaac-launchable"
ISAAC_LAB_COMPOSE_DIR="$ISAAC_LAUNCHABLE_DIR/isaac-lab"

echo "Installing Isaac Lab (Docker) in: $ISAAC_DIR"
echo ""

# Create isaac directory
mkdir -p "$ISAAC_DIR"

# ============================================================================
# Auto-Installation Functions
# ============================================================================

# Helper function to check if user has docker group access
check_docker_group_access() {
    docker ps &> /dev/null
    return $?
}

# Helper function to restart script with docker group privileges
restart_with_docker_group() {
    echo ""
    echo "=========================================="
    echo "Docker Group Activation"
    echo "=========================================="
    echo ""
    echo "The script needs to restart with docker group privileges."
    echo "This will re-execute the script with proper permissions."
    echo ""
    echo "Command to run: exec sg docker -c \"$0 $*\""
    echo ""

    if [ "$NON_INTERACTIVE" = true ]; then
        echo "Running in non-interactive mode - restarting automatically..."
        exec sg docker -c "$0 $*"
    fi

    read -p "Restart script with docker group? (Y/n): " -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        echo "Restarting script with docker group..."
        exec sg docker -c "$0 $*"
    else
        echo ""
        echo "To continue manually, run ONE of the following:"
        echo "  1. ${GREEN}exec sg docker -c \"$0 \$*\"${NC}"
        echo "  2. ${GREEN}newgrp docker${NC}, then re-run: $0 $*"
        echo "  3. Log out and log back in, then re-run: $0 $*"
        echo ""
        exit 1
    fi
}

# Helper function to add docker group auto-activation to .bashrc
add_docker_group_helper_to_bashrc() {
    local bashrc="$HOME/.bashrc"
    local marker="# scan2wall: docker group auto-activation"

    # Check if already added
    if grep -q "$marker" "$bashrc" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} Docker group helper already in .bashrc"
        return 0
    fi

    echo "Adding docker group helper to .bashrc..."

    cat >> "$bashrc" << 'EOF'

# scan2wall: docker group auto-activation
# Auto-activates docker group if user is member but shell doesn't have access
if command -v docker &> /dev/null; then
    if groups | grep -q docker && ! docker ps &> /dev/null 2>&1; then
        # Prevent infinite loop
        if [ "$DOCKER_GROUP_ACTIVATED" != "true" ]; then
            echo "Activating docker group for this shell..."
            export DOCKER_GROUP_ACTIVATED=true
            exec sg docker -c "DOCKER_GROUP_ACTIVATED=true bash"
        fi
    fi
fi
EOF

    echo -e "${GREEN}✓${NC} Added docker group helper to .bashrc"
    echo "  Future terminal sessions will auto-activate docker group"
}

install_docker() {
    echo ""
    echo "=========================================="
    echo "Docker Installation"
    echo "=========================================="
    echo ""
    echo -e "${YELLOW}Docker is not installed. Installing Docker automatically...${NC}"
    echo ""

    # Download and run Docker installation script
    echo "Downloading Docker installation script..."
    if ! curl -fsSL https://get.docker.com -o /tmp/get-docker.sh; then
        echo -e "${RED}✗ Failed to download Docker installation script${NC}"
        echo ""
        echo "Please install Docker manually:"
        echo "  curl -fsSL https://get.docker.com | sh"
        echo "  sudo usermod -aG docker \$USER"
        echo "  newgrp docker"
        exit 1
    fi

    echo "Running Docker installation script (requires sudo)..."
    if ! sudo sh /tmp/get-docker.sh; then
        echo -e "${RED}✗ Docker installation failed${NC}"
        echo ""
        echo "Please install Docker manually:"
        echo "  curl -fsSL https://get.docker.com | sh"
        echo "  sudo usermod -aG docker \$USER"
        echo "  newgrp docker"
        exit 1
    fi

    # Clean up installation script
    rm -f /tmp/get-docker.sh

    # Add current user to docker group
    echo "Adding user to docker group..."
    sudo usermod -aG docker "$USER"

    # Add helper to .bashrc for future shells
    add_docker_group_helper_to_bashrc

    # Activate docker group for current shell
    echo "Activating docker group..."
    # Restart docker service to ensure it's running with updated configuration
    sudo systemctl restart docker 2>/dev/null || sudo service docker restart 2>/dev/null

    # Wait for Docker to be ready
    sleep 3

    # Verify installation
    echo ""
    echo "Verifying Docker installation..."
    if command -v docker &> /dev/null; then
        # Test Docker without sudo by checking if we can run docker commands
        if docker ps &> /dev/null; then
            echo -e "${GREEN}✓${NC} Docker installed successfully: $(docker --version)"
            echo ""
            return 0
        else
            echo -e "${YELLOW}⚠${NC} Docker installed but current shell doesn't have docker group access"
            restart_with_docker_group
        fi
    else
        echo -e "${RED}✗ Docker installation verification failed${NC}"
        exit 1
    fi
}

install_nvidia_container_toolkit() {
    echo ""
    echo "=========================================="
    echo "NVIDIA Container Toolkit Installation"
    echo "=========================================="
    echo ""
    echo -e "${YELLOW}NVIDIA Container Toolkit is not installed. Installing automatically...${NC}"
    echo ""

    # Add NVIDIA Container Toolkit repository
    echo "Adding NVIDIA Container Toolkit repository (requires sudo)..."

    # Configure the repository
    if ! curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg; then
        echo -e "${RED}✗ Failed to add NVIDIA GPG key${NC}"
        echo ""
        echo "Please install NVIDIA Container Toolkit manually:"
        echo "  Visit: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
        exit 1
    fi

    if ! curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
        sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null; then
        echo -e "${RED}✗ Failed to add NVIDIA Container Toolkit repository${NC}"
        echo ""
        echo "Please install NVIDIA Container Toolkit manually:"
        echo "  Visit: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
        exit 1
    fi

    # Update apt cache
    echo "Updating package list..."
    if ! sudo apt-get update -qq; then
        echo -e "${YELLOW}⚠${NC} apt-get update had warnings, continuing anyway..."
    fi

    # Install nvidia-container-toolkit
    echo "Installing nvidia-container-toolkit..."
    if ! sudo apt-get install -y nvidia-container-toolkit; then
        echo -e "${RED}✗ Failed to install nvidia-container-toolkit${NC}"
        echo ""
        echo "Please install NVIDIA Container Toolkit manually:"
        echo "  sudo apt-get update"
        echo "  sudo apt-get install -y nvidia-container-toolkit"
        echo "  sudo systemctl restart docker"
        exit 1
    fi

    # Configure Docker to use NVIDIA runtime
    echo "Configuring Docker to use NVIDIA runtime..."
    sudo nvidia-ctk runtime configure --runtime=docker

    # Restart Docker
    echo "Restarting Docker service..."
    sudo systemctl restart docker 2>/dev/null || sudo service docker restart 2>/dev/null

    # Wait for Docker to be ready (longer wait for NVIDIA runtime to initialize)
    echo "Waiting for Docker and NVIDIA runtime to initialize (30 seconds)..."
    sleep 30

    # Verify installation
    echo ""
    echo "Verifying NVIDIA Container Toolkit installation..."
    echo "Running CUDA test container (this may take a minute on first run)..."
    if docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi &> /dev/null; then
        echo -e "${GREEN}✓${NC} NVIDIA Container Toolkit installed and configured successfully"
        echo ""
        return 0
    else
        echo -e "${RED}✗ NVIDIA Container Toolkit verification failed${NC}"
        echo ""
        echo "The toolkit was installed but the CUDA test failed."
        echo "This may indicate an issue with your NVIDIA drivers or Docker configuration."
        echo ""
        echo "Try these troubleshooting steps:"
        echo "  1. Verify NVIDIA drivers: nvidia-smi"
        echo "  2. Check Docker service: sudo systemctl status docker"
        echo "  3. Test manually: docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi"
        exit 1
    fi
}

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
    echo -e "${YELLOW}⚠${NC} Docker not found"
    install_docker
else
    echo -e "${GREEN}✓${NC} Docker installed: $(docker --version)"

    # Check if user has docker group access
    if ! check_docker_group_access; then
        echo -e "${YELLOW}⚠${NC} Docker installed but current user lacks docker group access"

        # Add user to docker group
        echo "Adding user to docker group..."
        sudo usermod -aG docker "$USER"

        # Add helper to .bashrc for future shells
        add_docker_group_helper_to_bashrc

        # Restart docker service to ensure it's running with updated configuration
        echo "Restarting Docker service..."
        sudo systemctl restart docker 2>/dev/null || sudo service docker restart 2>/dev/null
        sleep 3

        # Restart script with docker group
        restart_with_docker_group
    fi
fi

# Check for nvidia-container-toolkit
echo "Testing NVIDIA Container Toolkit..."

# First check if the package is installed
if dpkg -l | grep -q nvidia-container-toolkit && [ -f /etc/docker/daemon.json ] && grep -q "nvidia" /etc/docker/daemon.json; then
    echo -e "${GREEN}✓${NC} NVIDIA Container Toolkit package installed"

    # Quick test to verify it's working
    echo "Verifying GPU access in Docker..."
    if docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi &> /dev/null; then
        echo -e "${GREEN}✓${NC} NVIDIA Container Toolkit configured and working"
    else
        echo -e "${YELLOW}⚠${NC} Toolkit installed but test failed - this may be temporary"
        echo "Waiting 5 seconds and retrying..."
        sleep 5
        if docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi &> /dev/null; then
            echo -e "${GREEN}✓${NC} NVIDIA Container Toolkit working after retry"
        else
            echo -e "${YELLOW}⚠${NC} Test still failing, but toolkit is installed. Continuing..."
            echo "You can verify manually later with: docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi"
        fi
    fi
else
    echo -e "${YELLOW}⚠${NC} NVIDIA Container Toolkit not installed"
    install_nvidia_container_toolkit
fi

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
      - '$PROJECT_ROOT/src:/workspace/src:rw'
      - '$PROJECT_ROOT/src/scan2wall/simulation:/workspace/s2w-scripts:rw'
      - '$PROJECT_ROOT/data:/workspace/s2w-data:rw'
    environment:
      - PYTHONPATH=/workspace/src:\${PYTHONPATH:-}
    ports:
      - "8080:8080"
      - "8090:8090"
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
    echo "  • Volume mounts:"
    echo "    - scan2wall/src → /workspace/src (for Python imports)"
    echo "    - scan2wall/src/scan2wall/simulation → /workspace/s2w-scripts"
    echo "    - scan2wall/data → /workspace/s2w-data"
    echo "  • Environment: PYTHONPATH=/workspace/src"
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
# Install ffmpeg with NVENC support in Container
# ============================================================================

echo "Installing ffmpeg with NVENC support in vscode container..."
docker exec vscode bash -c '
    set -e
    apt-get update -qq

    # Install ffmpeg with NVENC support
    # The default Ubuntu ffmpeg has NVENC support if nvidia drivers are present
    apt-get install -y ffmpeg

    # Verify NVENC support
    if ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_nvenc; then
        echo "✓ ffmpeg with NVENC support installed"
    else
        echo "⚠ ffmpeg installed but NVENC not detected (will fallback to CPU)"
    fi
' > /dev/null 2>&1

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} ffmpeg with NVENC support installed in vscode container"

    # Verify NVENC is available
    if docker exec vscode bash -c "ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_nvenc"; then
        echo -e "${GREEN}✓${NC} NVENC encoder detected and ready"
    else
        echo -e "${YELLOW}⚠${NC} NVENC encoder not detected - GPU encoding will fallback to CPU"
        echo "    This is normal if NVIDIA drivers are not properly passed to the container"
    fi
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
