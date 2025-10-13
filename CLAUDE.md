# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**scan2wall** is a multi-stage AI pipeline that converts 2D phone photos into 3D physics simulations. Users photograph objects, which are then:
1. Converted to 3D meshes using Hunyuan 3D 2.1
2. Analyzed for physical properties using Gemini 2.0 Flash
3. Simulated being thrown at a pyramid in NVIDIA Isaac Sim

Total processing time: ~50-100 seconds per object.

## Development Commands

### Starting the Application

**Quick Start:**
```bash
./start.sh auto     # Automated with tmux
# OR
./start.sh          # Manual instructions for 3 terminals
```

**Manual Terminal Setup:**

**Terminal 1 - ComfyUI Backend:**
```bash
cd 3d_gen
source .venv/bin/activate
cd ComfyUI
python main.py --listen 0.0.0.0 --port 8188
```

**Terminal 2 - Upload Server:**
```bash
uv run 3d_gen/image_collection/run.py  # Runs on port 49100
```

**Terminal 3 - Isaac Lab (for running scripts):**
```bash
cd /workspace/isaac
./isaaclab.sh -p
```

### Testing and Development

**Test without phone (desktop upload):**
```bash
uv run 3d_gen/image_collection/run_desktop.py
```

**Test material property inference:**
```bash
cd 3d_gen/material_properties
python get_object_properties.py <image_path>
```

**View path configuration:**
```bash
python -m scan2wall.utils.paths
# Or directly:
python 3d_gen/utils/paths.py
```

**View all jobs (admin):**
```
http://localhost:49100/jobs
```

### ComfyUI Management

**Kill port conflicts:**
```bash
lsof -ti:8188 | xargs kill -9  # ComfyUI
lsof -ti:49100 | xargs kill -9 # Upload server
```

**Re-download models if missing:**
```bash
cd 3d_gen
bash modeldownload.sh
```

### Isaac Sim Commands

**Run mesh conversion manually:**
```bash
python isaac_scripts/convert_mesh.py <input.glb> <output.usd> \
  --mass 0.5 --static-friction 0.6 --dynamic-friction 0.5 \
  --collision-approximation convexHull --kit_args='--headless'
```

**Run simulation manually:**
```bash
python isaac_scripts/test_place_obj_video.py \
  --video --usd_path_abs /path/to/object.usd \
  --scaling_factor 1.0 --kit_args='--no-window'
```

## Architecture

### Pipeline Flow

```
Phone Upload
    ↓
FastAPI Server (port 49100)
    ↓
[Parallel] → Gemini 2.0 Flash (material properties)
    ↓
ComfyUI API (port 8188) - Direct integration, no wrapper!
    ↓
Hunyuan 3D 2.1 (GLB mesh generation, ~30-60s)
    ↓
convert_mesh.py (GLB → USD with physics)
    ↓
Isaac Lab (throw simulation + video recording)
    ↓
recordings/sim_run.mp4
```

### Key Components

**1. Upload Server** (`3d_gen/image_collection/app/server.py`)
- FastAPI web server on port 49100
- Handles image uploads, validation, job tracking
- In-memory job storage (JOBS dict)
- Background task processing via `ml_pipeline.py`
- Endpoints: `/`, `/upload`, `/job/{job_id}`, `/jobs`

**2. ML Pipeline** (`3d_gen/image_collection/ml_pipeline.py`)
- Orchestrates the entire processing flow
- **NEW**: Talks directly to ComfyUI API (no wrapper needed!)
- Calls Gemini for material inference
- Triggers mesh conversion and simulation
- Key function: `process_image(job_id, image_path)`
- Key function: `generate_mesh_via_comfyui(image_path, job_id)` - Direct ComfyUI integration

**3. Material Inference** (`3d_gen/material_properties/get_object_properties.py`)
- Uses Gemini 2.0 Flash multimodal LLM
- Returns JSON with: mass, dimensions, friction coefficients, object type
- Controlled by `USE_LLM` flag in ml_pipeline.py

**4. ComfyUI Integration** (Direct API, no wrapper)
- ML pipeline posts workflow JSON directly to ComfyUI's `/prompt` endpoint
- Polls `/history/{prompt_id}` for completion
- Retrieves GLB from output directory
- Uses workflow: `3d_gen/workflows/api_prompt_strcnst.json`

**5. Mesh Converter** (`isaac_scripts/convert_mesh.py`)
- Converts GLB → USD using Isaac Lab utilities
- Applies physics properties from Gemini inference
- Sets collision mesh, mass, friction, inertia
- Saves to `USD_OUTPUT_DIR` (default: `/workspace/isaaclab`)

**5. Simulation** (`isaac_scripts/test_place_obj_video.py`)
- Loads USD object into Isaac Sim scene
- Creates 20-level pyramid target
- Throws object at 17 m/s
- Records 200 physics steps to MP4
- Skips first 10 frames (warmup)
- Outputs to `recordings/sim_run.mp4`

### Path Configuration

The project uses a centralized path management system (`3d_gen/utils/paths.py`):

- **PROJECT_ROOT**: Auto-detected from repo structure
- **ISAAC_WORKSPACE**: Where Isaac Lab is installed (default: `/workspace/isaac`)
- **ISAAC_SCRIPTS_DIR**: Location of convert_mesh.py and simulation scripts
- **USD_OUTPUT_DIR**: Where converted USD meshes go (default: `/workspace/isaac/usd_files`)
- **RECORDINGS_DIR**: Video output directory (default: `{PROJECT_ROOT}/recordings`)
- **ASSETS_CSV**: Tracks generated objects (default: `{PROJECT_ROOT}/assets.csv`)

All paths support environment variable overrides via `.env` file.

### Single-Machine Setup (Default)

**All components run on one machine:**
- ComfyUI on port 8188 (3D generation)
- Upload server on port 49100 (web interface)
- Isaac Lab at `/workspace/isaac` (physics simulation)
- GPU: 16GB+ VRAM recommended
- Managed by `./start.sh` script

## Important Technical Details

### ComfyUI Workflow
- Node 112: Load Image
- Node 89: Save Model (GLB output)
- Custom nodes include: Hunyuan3d-2-1, Inspyrenet-Rembg, LayerStyle, KJNodes
- Models stored in `3d_gen/ComfyUI/models/` (~8GB)

### Physics Configuration
- Default mass: 1.0 kg (overridden by Gemini)
- Collision approximation: convexDecomposition (configurable)
- Physics timestep: 0.01s (100 FPS)
- Video output: 1920×1080, H.264, 50 FPS

### Job States
Jobs flow through: `queued` → `processing` → `done` / `error`

### File Validation
Upload server performs two-stage validation:
1. Signature check via `imghdr` (accepts: JPEG, PNG, WEBP, GIF)
2. Pillow `.verify()` to detect corruption

### Performance Bottlenecks
- 3D generation: 30-60s (GPU-bound, largest bottleneck)
- Material inference: 2-5s (API latency)
- Mesh conversion: 5-10s (CPU + I/O)
- Simulation: 10-20s (GPU-bound)

## Configuration

### Required Environment Variables
- `GOOGLE_API_KEY`: Gemini API key from Google AI Studio

### Optional Environment Variables (with defaults)
- `PORT`: Upload server port (default: 49100)
- `COMFY_URL`: ComfyUI API URL (default: http://127.0.0.1:8188)
- `COMFY_INPUT_DIR`: Where ComfyUI reads images (default: auto-detected)
- `COMFY_OUTPUT_DIR`: Where ComfyUI writes GLB files (default: auto-detected)
- `ISAAC_WORKSPACE`: Isaac Lab installation directory (default: /workspace/isaac)
- `USD_OUTPUT_DIR`: Where USD files are saved (default: /workspace/isaac/usd_files)
- All other path variables (see "Path Configuration" section above)

See `.env.example` for complete configuration template.

## Common Issues

**Port conflicts:** Use `lsof -ti:<port> | xargs kill -9` to kill existing processes

**Models not found:** Re-run `cd 3d_gen && bash modeldownload.sh`

**CUDA out of memory:** Close other GPU applications, restart ComfyUI

**Path errors:** Run `python -m scan2wall.utils.paths` to debug configuration

**Can't connect from phone:** Ensure same WiFi network, check firewall allows port 49100

**Isaac Sim crashes:** Check VRAM with `nvidia-smi`, reduce simulation resolution

**Job stuck in processing:** Check ComfyUI logs, verify API server is running

## Development Tips

- First 3D generation takes ~60s (model loading), subsequent ones ~30s (cached)
- The `--real-time` flag in simulation slows it to real-time playback
- Set `USE_LLM = False` in ml_pipeline.py to skip Gemini inference (faster testing)
- Set `USE_SCALING = False` to disable object scaling (use 1.0)
- Videos saved to `recordings/` directory in project root
- Frame sequences temporarily saved to `recordings/frames/` then deleted after encoding
- Simulation skips first 10 frames to avoid warmup artifacts
- Subprocess calls use `/bin/bash -lic` to ensure environment is loaded

## Project Structure Note

The actual source code is in `3d_gen/` not `src/scan2wall/`. The `scan2wall` Python package appears to be imported from `3d_gen/` subdirectories. Key files:
- `3d_gen/image_collection/` - Upload server and web UI
- `3d_gen/material_properties/` - Gemini integration
- `3d_gen/utils/` - Path configuration utilities
- `isaac_scripts/` - Isaac Sim integration scripts
- `3d_gen/workflows/` - ComfyUI workflow JSON files

## Tech Stack Summary
- **Python**: 3.10+ (managed via `uv` package manager)
- **3D Generation**: Hunyuan 3D 2.1 via ComfyUI
- **Material Analysis**: Google Gemini 2.0 Flash
- **Physics**: NVIDIA Isaac Sim (Isaac Lab)
- **Backend**: FastAPI
- **Frontend**: HTML5 + vanilla JavaScript
