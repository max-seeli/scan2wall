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
python 3d_gen/image_collection/run.py  # Runs on port 49100
```

**Isaac Worker** (runs automatically in Docker container):
- Persistent FastAPI service on port 8090 inside `vscode` container
- Started automatically by `start.sh`
- Handles mesh conversion and simulation requests
- Logs: `data/logs/isaac_worker.log`

### Testing and Development

**Test without phone (desktop upload):**
```bash
python 3d_gen/image_collection/run_desktop.py
```

**Test material property inference:**
```bash
cd 3d_gen/material_properties
python get_object_properties.py <image_path>
```

**View path configuration:**
```bash
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

### Isaac Worker API (Docker-based)

The Isaac worker is a persistent FastAPI service running inside the Docker container on port 8090.

**Check worker status:**
```bash
curl http://localhost:8090/
```

**Trigger mesh conversion manually:**
```bash
curl -X POST http://localhost:8090/convert \
  -H "Content-Type: application/json" \
  -d '{
    "asset_path": "/workspace/s2w-data/reconstructed_geoms/object.glb",
    "usd_dir": "/workspace/s2w-data/usd_files",
    "mass": 1.0,
    "static_friction": 0.6,
    "dynamic_friction": 0.5
  }'
```

**Trigger simulation manually:**
```bash
curl -X POST http://localhost:8090/run_simulation \
  -H "Content-Type: application/json" \
  -d '{
    "usd_path": "/workspace/s2w-data/usd_files/object.usd",
    "out_dir": "/workspace/s2w-data/recordings",
    "video": true,
    "video_length": 200,
    "fps": 50,
    "scaling_factor": 1.0
  }'
```

**View Isaac worker logs:**
```bash
docker exec vscode tail -f /workspace/s2w-data/logs/isaac_worker.log
```

**Check Docker containers:**
```bash
docker ps  # List running containers (should see vscode, web-viewer, nginx)
docker logs vscode  # View Isaac Lab logs
docker logs web-viewer  # View streaming viewer logs
```

**Restart Docker containers:**
```bash
cd isaac/isaac-launchable/isaac-lab
docker compose down
docker compose up -d
```

## Architecture

### Pipeline Flow

```
Phone Upload (port 49100)
    ↓
FastAPI Server (3d_gen/image_collection/app/server.py)
    ↓
ML Pipeline (ml_pipeline.py)
    ├─→ [Parallel] Gemini 2.0 Flash API (material properties)
    └─→ ComfyUI API (port 8188) - Direct integration
        └─→ Hunyuan 3D 2.1 (GLB mesh generation, ~30-60s)
            ↓
Isaac Worker API (port 8090, inside Docker)
    ├─→ POST /convert (GLB → USD with physics)
    └─→ POST /run_simulation (throw simulation + video)
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
- Talks directly to ComfyUI API (port 8188) - no wrapper needed
- Calls Gemini API for material inference
- Communicates with Isaac Worker API (port 8090) for conversion and simulation
- Key functions:
  - `process_image(job_id, image_path, jobs_dict)` - Main orchestration
  - `generate_mesh_via_comfyui(image_path, job_id)` - Direct ComfyUI integration
  - `convert_mesh(out_file, fname, mass, df, ds)` - Calls Isaac worker `/convert`
  - `make_throwing_anim(file, scaling, job_id)` - Calls Isaac worker `/run_simulation`

**3. Material Inference** (`3d_gen/material_properties/get_object_properties.py`)
- Uses Gemini 2.0 Flash multimodal LLM
- Returns JSON with: mass, dimensions, friction coefficients, object type
- Controlled by `USE_LLM` flag in ml_pipeline.py

**4. ComfyUI Integration** (Direct API)
- ML pipeline posts workflow JSON directly to ComfyUI's `/prompt` endpoint
- Polls `/history/{prompt_id}` for completion
- Retrieves GLB from output directory
- Uses workflow: `3d_gen/workflows/image-to-texture-mesh.json`

**5. Isaac Worker** (`isaac/isaac_scripts/isaac_worker.py`)
- Persistent FastAPI service running inside Docker `vscode` container
- Listens on port 8090 (accessible from host)
- Manages Isaac Lab's main Kit loop for GPU-accelerated physics
- **Endpoints:**
  - `GET /` - Health check (returns status and queue size)
  - `POST /convert` - Convert GLB → USD with physics properties
  - `POST /run_simulation` - Run throw simulation and generate video
- Processes jobs sequentially on Isaac's main thread
- Reuses camera between simulations for efficiency

**6. Mesh Conversion** (via Isaac Worker `/convert`)
- Converts GLB → USD using Isaac Lab's `MeshConverter`
- Applies physics properties from Gemini inference
- Sets collision mesh, mass, friction coefficients
- Saves to container path: `/workspace/s2w-data/usd_files/`

**7. Simulation** (via Isaac Worker `/run_simulation`)
- Loads USD object into Isaac Sim scene
- Creates 20-level pyramid target (blue cubes)
- Applies throwing velocity: 17 m/s forward
- Records 200 physics steps (~4 seconds) at 1920×1080
- Skips first 10 frames (warmup period)
- Encodes with ffmpeg (H.264) to `recordings/sim_run.mp4`

### Path Configuration

The project uses a centralized path management system (`3d_gen/utils/paths.py`):

- **PROJECT_ROOT**: Auto-detected from repo structure
- **ISAAC_WORKSPACE**: Where Isaac Lab is installed (default: `/workspace/isaac`)
- **ISAAC_SCRIPTS_DIR**: Location of convert_mesh.py and simulation scripts
- **USD_OUTPUT_DIR**: Where converted USD meshes go (default: `/workspace/isaac/usd_files`)
- **RECORDINGS_DIR**: Video output directory (default: `{PROJECT_ROOT}/recordings`)
- **ASSETS_CSV**: Tracks generated objects (default: `{PROJECT_ROOT}/assets.csv`)

All paths support environment variable overrides via `.env` file.

### Single-Machine Setup (Default - Docker-based)

**All components run on one machine:**
- ComfyUI on port 8188 (3D generation)
- Upload server on port 49100 (web interface)
- Isaac Worker on port 8090 (inside Docker, accessible from host)
- Isaac Lab runs in Docker containers (physics simulation)
  - **vscode** container: Isaac Lab environment with Isaac Sim + Isaac Worker
  - **web-viewer** container: Streaming interface for visualizations
  - **nginx** container: Reverse proxy for web services
- GPU: 16GB+ VRAM recommended
- Managed by `./start.sh` script

**Docker Architecture:**
- Isaac Lab cloned to: `isaac/isaac-launchable/`
- Docker Compose file: `isaac/isaac-launchable/isaac-lab/docker-compose.yml`
- Container mounts:
  - Host `/home/ubuntu/scan2wall/isaac/isaac_scripts` → Container `/workspace/s2w-scripts`
  - Host `/home/ubuntu/scan2wall/data` → Container `/workspace/s2w-data`
  - Host `/home/ubuntu/scan2wall/isaac/usd_files` → Container `/workspace/usd_files`
- Isaac Lab inside container at: `/workspace/isaaclab`

**Key Path Mappings (Host → Container):**
- `/home/ubuntu/scan2wall/data/uploaded_pictures` → `/workspace/s2w-data/uploaded_pictures`
- `/home/ubuntu/scan2wall/data/reconstructed_geoms` → `/workspace/s2w-data/reconstructed_geoms`
- `/home/ubuntu/scan2wall/data/usd_files` → `/workspace/s2w-data/usd_files`
- `/home/ubuntu/scan2wall/data/recordings` → `/workspace/s2w-data/recordings`
- `/home/ubuntu/scan2wall/isaac/isaac_scripts` → `/workspace/s2w-scripts`

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
- `ISAAC_WORKSPACE`: Isaac Lab path **inside Docker container** (default: /workspace/isaaclab)
- `ISAAC_WORKER_URL`: Isaac Worker API URL (default: http://localhost:8090)
- `USD_OUTPUT_DIR`: Where USD files are saved on host (default: /home/ubuntu/scan2wall/isaac/usd_files)
- All other path variables (see "Path Configuration" section above)

**Important for Docker setup:**
- `ISAAC_WORKSPACE` refers to the container path (`/workspace/isaaclab`)
- Host paths get converted to container paths in `ml_pipeline.py` using pattern:
  - Host: `/home/ubuntu/scan2wall/data/*` → Container: `/workspace/s2w-data/*`
  - Host: `/home/ubuntu/scan2wall` → Container: `/workspace`
- The ML pipeline communicates with Isaac Worker via HTTP API (port 8090)
- Isaac Worker runs inside the `vscode` container, started by `start.sh`

See `.env.example` for complete configuration template.

## Common Issues

**Port conflicts:** Use `lsof -ti:<port> | xargs kill -9` to kill existing processes

**Models not found:** Re-run `cd 3d_gen && bash modeldownload.sh`

**CUDA out of memory:** Close other GPU applications, restart ComfyUI

**Path errors:** Run `python 3d_gen/utils/paths.py` to debug configuration

**Import errors (ModuleNotFoundError):**
The codebase uses direct imports within the `3d_gen/` directory. Imports are handled via `sys.path.insert()` in:
- `3d_gen/image_collection/ml_pipeline.py`
- `3d_gen/standalone_video.py`

No package installation required - imports resolve at runtime.

**Missing dependencies for upload server:**
If you get `ModuleNotFoundError` for qrcode, fastapi, etc., install:
```bash
pip install fastapi uvicorn python-multipart python-dotenv pillow requests google-generativeai qrcode
```

**Can't connect from phone:** Ensure same WiFi network, check firewall allows port 49100

**Isaac Sim crashes:** Check VRAM with `nvidia-smi`, reduce simulation resolution

**Job stuck in processing:** Check ComfyUI logs, verify API server is running

**Docker containers not running:**
```bash
cd isaac/isaac-launchable/isaac-lab
docker compose ps  # Check container status
docker compose up -d  # Start containers
docker compose logs vscode  # View logs
```

**Isaac Worker not responding:**
- Check if worker is running: `curl http://localhost:8090/`
- View worker logs: `docker exec vscode tail -f /workspace/s2w-data/logs/isaac_worker.log`
- Restart worker: Kill existing process and restart via `start.sh`
- Check if vscode container is running: `docker ps | grep vscode`

**Docker containers not running:**
- List containers: `docker ps -a`
- Start containers: `cd isaac/isaac-launchable/isaac-lab && docker compose up -d`
- Check logs: `docker logs vscode` or `docker logs web-viewer`

**Path errors in Docker:**
- Host paths: `/home/ubuntu/scan2wall/data/*`
- Container paths: `/workspace/s2w-data/*`
- The ML pipeline automatically converts host → container paths
- Isaac Lab inside container: `/workspace/isaaclab`
- Isaac Worker expects container paths in API requests

## Development Tips

- First 3D generation takes ~60s (model loading), subsequent ones ~30s (cached)
- Set `USE_LLM = False` in ml_pipeline.py to skip Gemini inference (faster testing with default physics)
- Set `USE_SCALING = False` to disable object scaling (use 1.0)
- Videos saved to `data/recordings/` directory
- Frame sequences temporarily saved to `recordings/frames/` then deleted after encoding
- Simulation skips first 10 frames to avoid warmup artifacts
- Isaac Worker runs persistently - it reuses the camera and scene between jobs for efficiency
- Path conversion happens automatically in ML pipeline (host paths → container paths)
- The Isaac Worker API allows parallel development: you can test conversion/simulation independently
- Check worker queue status with `curl http://localhost:8090/` to see if jobs are pending

## Project Structure Note

The source code is in `3d_gen/`. Imports now use direct relative imports within the `3d_gen/` directory structure (the `scan2wall` package import dependency has been removed). Key files:
- `3d_gen/image_collection/` - Upload server and web UI
- `3d_gen/material_properties/` - Gemini integration
- `3d_gen/utils/` - Path configuration utilities
- `isaac_scripts/` - Isaac Sim integration scripts
- `3d_gen/workflows/` - ComfyUI workflow JSON files

## Tech Stack Summary
- **Python**: 3.10+ (managed via `uv` package manager)
- **3D Generation**: Hunyuan 3D 2.1 via ComfyUI
- **Material Analysis**: Google Gemini 2.0 Flash
- **Physics**: NVIDIA Isaac Sim (Isaac Lab) - Docker-based deployment
- **Backend**: FastAPI (upload server + Isaac Worker API)
- **Frontend**: HTML5 + vanilla JavaScript
- **Container Runtime**: Docker + Docker Compose
- **Video Encoding**: FFmpeg

## System Ports

| Port | Service | Location | Purpose |
|------|---------|----------|---------|
| 8188 | ComfyUI | Host | 3D mesh generation API |
| 49100 | Upload Server | Host | Web interface & image uploads |
| 8090 | Isaac Worker | Docker (vscode) | Mesh conversion & simulation API |
| 49110 | Web Viewer | Docker | Isaac Lab streaming interface |
| 49111 | Nginx | Docker | Reverse proxy for web services |
