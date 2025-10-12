# scan2wall Setup Guide

Complete installation and setup instructions for the scan2wall project - a tool that generates 3D meshes from phone photos and simulates throwing them at a wall using NVIDIA Isaac Sim.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Installation](#installation)
  - [1. Core Project Setup](#1-core-project-setup)
  - [2. ComfyUI and Hunyuan 2.1 Setup](#2-comfyui-and-hunyuan-21-setup)
  - [3. NVIDIA Isaac Sim Setup](#3-nvidia-isaac-sim-setup)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### System Requirements
- **OS**: Linux (tested on Ubuntu 20.04+)
- **GPU**: NVIDIA GPU with CUDA support (RTX series recommended)
  - Minimum 8GB VRAM for Hunyuan 2.1
  - 12GB+ VRAM recommended for optimal performance
- **RAM**: 16GB minimum, 32GB+ recommended
- **Storage**: ~50GB free space (models + dependencies)

### Software Requirements
- Python 3.10 or 3.11
- CUDA Toolkit (11.8 or 12.x)
- [NVIDIA Isaac Sim](https://developer.nvidia.com/isaac-sim) (2023.1.1 or later)
- Conda or Miniconda
- ffmpeg (for video encoding)
- uv (Python package manager)

---

## Installation

### 1. Core Project Setup

Clone the repository and set up the main Python environment:

```bash
# Clone the repository
git clone https://github.com/yourusername/scan2wall.git
cd scan2wall

# Install uv package manager
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
uv sync
uv pip install -e .
```

### 2. ComfyUI and Hunyuan 2.1 Setup

The 3D mesh generation uses ComfyUI with the Hunyuan 2.1 model.

#### Step 1: Create Conda Environment

```bash
cd 3d_gen

# Option A: Use the provided script
chmod +x minic.sh
./minic.sh

# Option B: Manual setup
conda create -n comfyui python=3.10 -y
```

**IMPORTANT**: Close and reopen your terminal after creating the environment.

#### Step 2: Install ComfyUI

```bash
# Activate the environment
conda activate comfyui

# Run the ComfyUI installation script
chmod +x comfy.sh
bash comfy.sh
```

This script will:
- Clone ComfyUI repository
- Install PyTorch with CUDA support
- Install all required dependencies

#### Step 3: Download Models

```bash
# Still in 3d_gen directory with comfyui environment active
chmod +x modeldownload.sh
bash modeldownload.sh
```

This downloads the Hunyuan 2.1 model weights (~8GB). The script will place them in the correct ComfyUI directories.

#### Step 4: Test ComfyUI

```bash
cd ComfyUI
python main.py --listen 0.0.0.0 --port 8188
```

Open `http://localhost:8188` in your browser. You should see the ComfyUI interface.

Load the workflow file:
- Click "Load" in ComfyUI
- Navigate to `3d_gen/workflows/image_to_3D_fast.json`
- Load it

Try generating a 3D mesh with a test image to verify everything works.

### 3. NVIDIA Isaac Sim Setup

#### Step 1: Install Isaac Sim

1. Download Isaac Sim from the [NVIDIA Developer Portal](https://developer.nvidia.com/isaac-sim)
2. Follow the [official installation guide](https://docs.omniverse.nvidia.com/isaacsim/latest/installation/index.html)
3. Install to `/workspace/isaaclab` or update paths in the code

#### Step 2: Install IsaacLab

```bash
# Clone IsaacLab (if not already installed with Isaac Sim)
cd /workspace
git clone https://github.com/isaac-sim/IsaacLab.git isaaclab
cd isaaclab

# Run the installation script
./isaaclab.sh --install
```

#### Step 3: Verify Isaac Sim

```bash
cd /workspace/isaaclab
./isaaclab.sh -p scripts/tutorials/00_sim/create_empty.py
```

You should see a window with an empty Isaac Sim scene.

---

## Configuration

### Environment Variables

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` and add your API keys:

```bash
# Google Gemini API (for material property inference)
GOOGLE_API_KEY=your_gemini_api_key_here

# Server configuration
PORT=49100

# ComfyUI server URL (change if running remotely)
COMFY_SERVER_URL=http://127.0.0.1:8012

# ComfyUI input directory
COMFY_INPUT_DIR=~/scan2wall/3d_gen/input
```

### Getting API Keys

**Google Gemini API**:
1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create an API key
3. Add to `.env` file

### Server URLs

If running ComfyUI on a different machine (e.g., cloud GPU):
1. Update `COMFY_SERVER_URL` in `.env`
2. Update the hardcoded URL in `src/scan2wall/image_collection/ml_pipeline.py` line 24

---

## Running the Application

The application has three main components that need to run simultaneously:

### Terminal 1: ComfyUI Backend

```bash
cd 3d_gen
conda activate comfyui
cd ComfyUI
python main.py --listen 0.0.0.0 --port 8188
```

### Terminal 2: ComfyUI API Server

```bash
cd 3d_gen
conda activate comfyui
python server.py
```

This runs on port 8012 and handles image-to-3D conversion requests.

### Terminal 3: Main Upload Server

```bash
cd scan2wall
source .venv/bin/activate  # or: uv shell
uv run src/scan2wall/image_collection/run.py
```

This starts the main web server on port 49100 (configurable via PORT env var).

### Accessing the Application

1. The server will print a URL and generate a QR code
2. Scan the QR code with your phone or visit the URL
3. Take a photo and it will automatically upload and process

**Alternative**: Use `run_desktop.py` for testing without a phone:
```bash
uv run src/scan2wall/image_collection/run_desktop.py
```

---

## How It Works

1. **Capture**: User takes photo on phone via web interface
2. **Upload**: Image automatically uploads to FastAPI server
3. **Material Inference**: Gemini 2.0 Flash analyzes image for physical properties (mass, friction, etc.)
4. **3D Generation**: ComfyUI + Hunyuan 2.1 generates 3D mesh (GLB format)
5. **Mesh Conversion**: GLB → USD with physics properties for Isaac Sim
6. **Simulation**: Isaac Sim throws object at pyramid of blocks
7. **Recording**: Simulation recorded to MP4 video (saved to `recordings/`)

---

## Troubleshooting

### ComfyUI Issues

**Problem**: "Model not found" error
- **Solution**: Re-run `modeldownload.sh` and ensure models are in `ComfyUI/models/`

**Problem**: CUDA out of memory
- **Solution**: Reduce batch size or use smaller model variant in workflow

### Isaac Sim Issues

**Problem**: "Cannot open display" error
- **Solution**: Isaac Sim needs X11 or use headless mode with `--headless` flag

**Problem**: Isaac Sim crashes during simulation
- **Solution**: Check VRAM usage. Close other GPU applications.

### Server Issues

**Problem**: Port already in use
- **Solution**: Change PORT in `.env` or kill process using the port:
  ```bash
  lsof -ti:49100 | xargs kill -9
  ```

**Problem**: Can't connect from phone
- **Solution**:
  - Ensure phone and server are on same WiFi network
  - Check firewall allows port 49100
  - Try using the public IP instead of local IP

### Pipeline Issues

**Problem**: Job stuck in "processing" status
- **Solution**:
  - Check ComfyUI server logs
  - Verify 3D_gen server is running
  - Check `/jobs` endpoint for error details

**Problem**: Invalid mesh generated
- **Solution**:
  - Try a different photo with better lighting
  - Ensure object is clearly visible and centered
  - Avoid blurry or dark images

---

## Development Tips

### Checking Job Status

Visit `http://localhost:49100/jobs` to see all processing jobs and their statuses.

### Testing Without Phone

Use `run_desktop.py` for local testing with file upload dialog:
```bash
uv run src/scan2wall/image_collection/run_desktop.py
```

### Debugging ML Pipeline

Test the pipeline directly:
```python
cd src/scan2wall/image_collection
python ml_pipeline.py
```

### Video Output Location

Simulation videos are saved to `recordings/` in the project root.

---

## Performance Optimization

- **ComfyUI**: Use `--highvram` flag if you have 24GB+ VRAM
- **Isaac Sim**: Reduce simulation steps or resolution for faster processing
- **Caching**: ComfyUI caches models in memory after first load

---

## Getting Help

- **Issues**: [GitHub Issues](https://github.com/yourusername/scan2wall/issues)
- **Isaac Sim Docs**: https://docs.omniverse.nvidia.com/isaacsim/
- **ComfyUI Docs**: https://github.com/comfyanonymous/ComfyUI

---

## Next Steps

After setup, see:
- `ARCHITECTURE.md` - System architecture and data flow
- `EMAIL_INTEGRATION.md` - Future email-to-simulation feature
- `README.md` - Quick start guide
