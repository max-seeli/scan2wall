# scan2wall Setup Guide

Complete installation guide for scan2wall - a tool that generates 3D meshes from phone photos and simulates throwing them at a wall using NVIDIA Isaac Sim.

---

## Architecture Overview

scan2wall supports two deployment modes:

### Two-Instance Setup (Recommended for production)

1. **Instance 1**: Linux + NVIDIA GPU - runs ComfyUI for 3D generation
2. **Instance 2**: Isaac Sim - runs physics simulation

Benefits: Distributed processing, easier to scale, specialized environments

### Single-Instance Setup (For development/demos)

1. **One powerful machine**: Runs both ComfyUI and Isaac Sim

Requirements:
- NVIDIA GPU with **16GB+ VRAM** (RTX 4080/4090, A4000+)
- **32GB+ RAM**
- Isaac Sim fully installed

Benefits: Simpler setup, no network latency, lower cost

**Choose the setup that matches your hardware!** This guide covers both.

---

## Prerequisites

### Instance 1 (ComfyUI + 3D Generation)

**Hardware**:
- NVIDIA GPU with 8GB+ VRAM (RTX series recommended)
- 16GB+ RAM
- 50GB free storage (for models)

**Software**:
- Linux (tested on Ubuntu 20.04+)
- CUDA Toolkit (11.8 or 12.x)
- Python 3.10 or 3.11

### Instance 2 (Isaac Sim)

**Hardware**:
- NVIDIA GPU with 6GB+ VRAM
- 16GB+ RAM

**Software**:
- Isaac Sim 2023.1.1+ (follow [isaac-launchable guide](https://github.com/isaac-sim/isaac-launchable))
- ffmpeg
- Python 3.11

---

## Installation

### Instance 1: ComfyUI + 3D Generation

#### 1. Clone Repository

```bash
git clone https://github.com/max-seeli/scan2wall.git
cd scan2wall
```

#### 2. Install Core Dependencies

```bash
# Install uv package manager
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install main dependencies
uv sync
uv pip install -e .
```

#### 3. Setup ComfyUI

```bash
cd 3d_gen

# Run setup script (creates venv, installs PyTorch, ComfyUI, custom nodes)
bash setup_comfyui.sh

# Download Hunyuan 3D 2.1 models (~8GB)
bash modeldownload.sh
```

**Time**: ~15-20 minutes total

#### 4. Verify ComfyUI

```bash
source .venv/bin/activate
cd ComfyUI
python main.py --listen 0.0.0.0 --port 8188
```

Open `http://localhost:8188` in your browser. You should see the ComfyUI interface. Load and test the workflow at `3d_gen/workflows/image_to_3D_fast.json`.

### Instance 2: Isaac Sim

#### 1. Install Isaac Sim

Follow the [isaac-launchable tutorial](https://github.com/isaac-sim/isaac-launchable) to set up your Isaac Sim instance.

#### 2. Clone Repository

```bash
# Inside Isaac workspace
git clone https://github.com/max-seeli/scan2wall
cd scan2wall
```

#### 3. Install Dependencies

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install project dependencies
uv sync
uv pip install -e .

# Install ffmpeg (required for video encoding)
sudo apt-get install ffmpeg
```

---

## Configuration

### 1. Create Environment File

```bash
cd scan2wall
cp .env.example .env
```

### 2. Configure Environment Variables

Edit `.env` with your settings:

#### Required Variables

**`GOOGLE_API_KEY`**
- **Purpose**: Authentication for Gemini 2.0 Flash (material property inference)
- **Get it**: [Google AI Studio](https://makersuite.google.com/app/apikey)
- **Example**: `GOOGLE_API_KEY=AIzaSyD...your_key_here`

**`ISAAC_INSTANCE_ADDRESS`**
- **Purpose**: URL of your Isaac Sim instance running the ComfyUI API
- **Format**: `https://<PORT>-<INSTANCE_NAME>.brevlab.com/process`
- **Example**: `ISAAC_INSTANCE_ADDRESS=https://8012-myinstance.brevlab.com/process`

#### Optional Variables

**`PORT`**
- **Purpose**: Port for the upload server
- **Default**: 49100
- **Example**: `PORT=49100`

**`COMFY_SERVER_URL`**
- **Purpose**: URL of ComfyUI API server
- **Default**: http://127.0.0.1:8012
- **Change if**: Running ComfyUI on a different machine
- **Example**: `COMFY_SERVER_URL=http://192.168.1.100:8012`

**`COMFY_INPUT_DIR`**
- **Purpose**: Directory where images are copied for ComfyUI processing
- **Default**: ~/scan2wall/3d_gen/input
- **Example**: `COMFY_INPUT_DIR=/home/user/scan2wall/3d_gen/input`

### Complete .env Example (Two-Instance Setup)

```bash
# Required
GOOGLE_API_KEY=AIzaSyD...your_key_here
ISAAC_INSTANCE_ADDRESS=https://8012-myinstance.brevlab.com/process

# Optional (uncomment to customize)
# PORT=49100
# COMFY_SERVER_URL=http://127.0.0.1:8012
# COMFY_INPUT_DIR=~/scan2wall/3d_gen/input
```

### Single-Instance Configuration

If running everything on one machine, update your `.env`:

```bash
# Required
GOOGLE_API_KEY=AIzaSyD...your_key_here

# Point to local ComfyUI API (not remote instance)
ISAAC_INSTANCE_ADDRESS=http://127.0.0.1:8012/process

# Optional: Custom paths
# PROJECT_ROOT=/home/user/scan2wall
# ISAAC_WORKSPACE=/home/user/isaac_workspace
# USD_OUTPUT_DIR=/home/user/isaac_workspace
```

**Key difference**: `ISAAC_INSTANCE_ADDRESS` uses `127.0.0.1` (localhost) instead of a remote URL.

**Path configuration**: All paths auto-detect from your repository location. Only set custom paths if:
- Using non-standard directory structure
- Isaac Sim installed in custom location
- Want USD files saved to specific directory

---

## Running the Application

**Note**: These steps work for both single-instance and two-instance setups. For single-instance, run all terminals on the same machine.

You need **three terminal sessions** running simultaneously:

### Instance 1 - Terminal 1: ComfyUI Backend

```bash
cd scan2wall/3d_gen
source .venv/bin/activate
cd ComfyUI
python main.py --listen 0.0.0.0 --port 8188
```

**What it does**: Runs the ComfyUI web interface and workflow engine

### Instance 1 - Terminal 2: ComfyUI API Server

```bash
cd scan2wall/3d_gen
source .venv/bin/activate
python server.py
```

**What it does**: HTTP wrapper around ComfyUI for image-to-3D conversion (runs on port 8012)

### Instance 2 - Terminal 3: Upload Server

```bash
cd scan2wall
python 3d_gen/image_collection/run.py
```

**What it does**: Main upload server that coordinates the entire pipeline (runs on port 49100)

### Accessing the Application

The server will:
1. Print a URL (e.g., `http://192.168.1.100:49100`)
2. Generate a QR code saved as `upload_page_qr.png`

**From your phone**:
- Scan the QR code, or
- Type the URL directly

**For testing without phone**:
```bash
python 3d_gen/image_collection/run_desktop.py
```

---

## Pipeline Flow

Once running, here's what happens when you upload an image:

1. **Upload** (1-5s) - Image sent to server, job created
2. **Material Inference** (2-5s) - Gemini analyzes physical properties
3. **3D Generation** (30-60s) - Hunyuan 2.1 creates 3D mesh
4. **Mesh Conversion** (5-10s) - GLB converted to USD with physics
5. **Simulation** (10-20s) - Isaac Sim runs throwing simulation
6. **Video Output** - Result saved to `recordings/sim_run.mp4`

**Total time: 50-100 seconds**

---

## Troubleshooting

### ComfyUI Issues

**Problem**: Model not found error

**Solution**:
```bash
cd 3d_gen
bash modeldownload.sh
# Verify models exist in ComfyUI/models/hunyuan3d_dit/
```

**Problem**: CUDA out of memory

**Solution**:
- Close other GPU applications
- Restart ComfyUI
- Consider using smaller batch size in workflow

**Problem**: Port 8188 already in use

**Solution**:
```bash
lsof -ti:8188 | xargs kill -9
```

### Isaac Sim Issues

**Problem**: Cannot open display error

**Solution**:
- Use headless mode with `--kit_args='--headless'` flag
- Or ensure X11 is configured if running with GUI

**Problem**: Isaac Sim crashes during simulation

**Solution**:
- Check VRAM usage with `nvidia-smi`
- Close other GPU applications
- Reduce simulation resolution in `test_place_obj_video.py`

### Server Issues

**Problem**: Can't connect from phone

**Solution**:
1. Verify phone and server are on same WiFi network
2. Check firewall allows port 49100:
   ```bash
   sudo ufw allow 49100
   ```
3. Use actual IP address (not localhost)
4. Try accessing from phone browser directly: `http://<server-ip>:49100`

**Problem**: Port already in use

**Solution**:
```bash
# Change PORT in .env, or kill existing process:
lsof -ti:49100 | xargs kill -9
```

**Problem**: Job stuck in "processing" status

**Solution**:
1. Check ComfyUI server logs in Terminal 2
2. Verify ComfyUI API server is running
3. Check `/jobs` endpoint for error details: `http://localhost:49100/jobs`

### Pipeline Issues

**Problem**: Invalid mesh generated

**Solution**:
- Use clear, well-lit photos
- Ensure object is centered and visible
- Avoid blurry or dark images
- Try a different angle

**Problem**: Gemini API errors

**Solution**:
- Verify `GOOGLE_API_KEY` is set correctly in `.env`
- Check API key is active at [Google AI Studio](https://makersuite.google.com/app/apikey)
- Check API quota/rate limits

### Path Configuration Issues

**Problem**: "File not found" errors for isaac_scripts or assets.csv

**Solution**:
1. Check path configuration:
   ```bash
   python 3d_gen/utils/paths.py
   ```
2. Verify all paths exist and are correct
3. If using custom paths, ensure they're set in `.env`:
   ```bash
   PROJECT_ROOT=/your/custom/path
   ISAAC_WORKSPACE=/your/isaac/path
   ```

**Problem**: USD files not found by Isaac Sim

**Solution**:
- Check `USD_OUTPUT_DIR` matches where Isaac Sim expects files
- Default is `/workspace/isaaclab` - change if Isaac is elsewhere
- Ensure output directory has write permissions

**Problem**: Can't find convert_mesh.py or test_place_obj_video.py

**Solution**:
- Verify `ISAAC_SCRIPTS_DIR` points to `isaac_scripts/` directory
- Default auto-detects from project root
- Set manually if using custom layout:
  ```bash
  ISAAC_SCRIPTS_DIR=/path/to/scan2wall/isaac_scripts
  ```

---

## Development Tips

### Check Job Status

Visit `http://localhost:49100/jobs` to see all jobs and their current status.

### Test Without Phone

Use the desktop version for local testing:
```bash
python 3d_gen/image_collection/run_desktop.py
```

### Debug ML Pipeline

Test pipeline components individually:
```bash
cd 3d_gen/image_collection
python ml_pipeline.py
```

### Video Output Location

Simulation videos are saved to `recordings/` in the project root.

### Check Logs

All three terminals show live logs. Watch for:
- Upload confirmations
- Gemini API responses
- ComfyUI progress
- Isaac Sim simulation status

---

## Performance Optimization

**ComfyUI**:
- Use `--highvram` flag if you have 24GB+ VRAM
- Models are cached in memory after first load (~20s speedup)

**Isaac Sim**:
- Reduce simulation steps in `test_place_obj_video.py` for faster processing
- Lower video resolution for smaller file sizes

**Caching**:
- ComfyUI keeps models loaded between generations
- First generation takes longer (~60s), subsequent ones faster (~30s)

---

## Next Steps

After successful setup:

- Read **[ARCHITECTURE.md](ARCHITECTURE.md)** for technical details
- Check **[README.md](README.md)** for quick reference
- See **[EMAIL_INTEGRATION.md](EMAIL_INTEGRATION.md)** for planned features

---

## Getting Help

- **Issues**: [GitHub Issues](https://github.com/max-seeli/scan2wall/issues)
- **Isaac Sim Docs**: https://docs.omniverse.nvidia.com/isaacsim/
- **ComfyUI Docs**: https://github.com/comfyanonymous/ComfyUI
- **Hunyuan 3D**: https://github.com/Tencent/Hunyuan3D-2
