# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**scan2wall** is a multi-stage AI pipeline that converts 2D phone photos into 3D physics simulations. Users photograph objects, which are then:
1. Converted to 3D meshes using Hunyuan 3D 2.1
2. Analyzed for physical properties using Gemini 2.0 Flash
3. Simulated being thrown at a pyramid in NVIDIA Isaac Sim

Total processing time: **~150s first run**, **~65-75s subsequent runs** (model caching).

## Development Commands

### Starting the Application

**Quick Start:**
```bash
./scripts/start.sh auto     # Automated with tmux
# OR
./scripts/start.sh          # Manual instructions for 3 terminals
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
source .venv/bin/activate
python -m scan2wall.server.run  # Runs on port 49100
```

**Isaac Worker** (runs automatically in Docker container):
- Persistent HTTP server on port 8090 inside `vscode` container (uses Python's http.server)
- Started automatically by `scripts/start.sh`
- Handles mesh conversion and simulation requests
- Logs: `data/logs/isaac_worker.log`

### Testing and Development

**Test without phone (desktop upload):**
```bash
source .venv/bin/activate
python -m scan2wall.server.run_desktop
```

**Test material property inference:**
```bash
source .venv/bin/activate
python -m scan2wall.inference.get_object_properties <image_path>
```

**Simple video viewer for testing:**
```bash
source .venv/bin/activate
python -m scan2wall.server.test  # Video viewer on port 8000
```

**View all jobs (admin):**
```
http://localhost:49100/jobs
```

**Watch simulation video:**
- Videos automatically display on upload page when job completes
- Or access directly: `http://localhost:49100/video/{job_id}`
- Videos saved as: `data/recordings/{job_id}_sim.mp4`

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
FastAPI Server (src/scan2wall/server/server.py)
    ↓
Pipeline Coordinator (src/scan2wall/pipeline/coordinator.py)
    ├─→ [Parallel] Gemini 2.0 Flash API (material properties)
    └─→ ComfyUI API (port 8188) - Direct integration
        └─→ Hunyuan 3D 2.1 (GLB mesh generation, ~30-60s)
            ↓
Isaac Worker HTTP API (port 8090, inside Docker)
    ├─→ POST /convert (GLB → USD with physics)
    └─→ POST /run_simulation (throw simulation + videos)
        ↓
recordings/{job_id}_static.mp4 (static camera)
recordings/{job_id}_follow.mp4 (follow camera)
```

### Key Components

**1. Upload Server** (`src/scan2wall/server/server.py`)
- FastAPI web server on port 49100
- Handles image uploads, validation, job tracking
- In-memory job storage (JOBS dict)
- Background task processing via `coordinator.py`
- Endpoints: `/`, `/upload`, `/job/{job_id}`, `/jobs`, `/video/{job_id}`, `/asset/{job_id}/*`
- Videos automatically display on upload page when job completes

**2. Pipeline Coordinator** (`src/scan2wall/pipeline/coordinator.py`)
- Orchestrates the entire processing flow
- Talks directly to ComfyUI API (port 8188) - no wrapper needed
- Calls Gemini API for material inference
- Communicates with Isaac Worker HTTP API (port 8090) for conversion and simulation
- Key functions:
  - `process_image(job_id, image_path, jobs_dict)` - Main orchestration
  - `generate_mesh_via_comfyui(image_path, job_id)` - Direct ComfyUI integration
  - `convert_mesh(out_file, fname, mass, df, ds)` - Calls Isaac worker `/convert`
  - `make_throwing_anim(file, scaling, job_id, status_updater)` - Calls Isaac worker `/run_simulation`

**3. Material Inference** (`src/scan2wall/inference/get_object_properties.py`)
- Uses Gemini 2.0 Flash multimodal LLM
- Returns JSON with: mass, dimensions, friction coefficients, object type
- Controlled by `USE_LLM` flag in coordinator.py

**4. ComfyUI Integration** (Direct API)
- Pipeline coordinator posts workflow JSON directly to ComfyUI's `/prompt` endpoint
- Polls `/history/{prompt_id}` for completion
- Retrieves GLB from output directory
- Uses workflow: `3d_gen/ComfyUI/custom_nodes/ComfyUI-MeshCraft/workflows/image-to-texture-mesh-api-proper.json`

**5. Isaac Worker** (`src/scan2wall/simulation/isaac_worker.py`)
- Persistent HTTP server running inside Docker `vscode` container (uses Python's http.server)
- Listens on port 8090 (accessible from host)
- Manages Isaac Lab's main Kit loop for GPU-accelerated physics
- **Endpoints:**
  - `GET /` - Health check (returns status and queue size)
  - `POST /convert` - Convert GLB → USD with physics properties
  - `POST /run_simulation` - Run throw simulation and generate videos (static + follow camera)
  - `POST /create_base_scene` - Create base scene with pyramid
- Processes jobs sequentially on Isaac's main thread
- Reuses camera between simulations for efficiency

**6. Mesh Conversion** (via Isaac Worker `/convert`)
- Converts GLB → USD using Isaac Lab's `MeshConverter`
- Applies physics properties from Gemini inference
- Sets collision mesh, mass, friction coefficients
- Saves to container path: `/workspace/s2w-data/usd_files/`

**7. Simulation** (via Isaac Worker `/run_simulation`)
- Loads USD object into Isaac Sim scene
- Creates pyramid target (6 levels by default, configurable up to 20 levels)
- Applies throwing velocity: 13 m/s forward + 6 m/s upward (magnitude ≈14.3 m/s)
- Records from two camera angles: static view and follow camera
- Records 200 physics steps (~4 seconds) at 1280×720
- Skips first 10 frames (warmup period)
- Encodes with ffmpeg (NVENC H.264 GPU encoding for speed)
- Outputs two videos per job:
  - `data/recordings/{job_id}_static.mp4` (fixed camera view)
  - `data/recordings/{job_id}_follow.mp4` (follow camera view)

### Path Configuration

Path management is handled via environment variables in `.env` file:

- **PROJECT_ROOT**: Auto-detected from repo structure
- **ISAAC_WORKSPACE**: Isaac Lab path inside container (default: `/workspace/isaaclab`)
- **ISAAC_SCRIPTS_DIR**: Location of isaac_worker.py (default: `{PROJECT_ROOT}/src/scan2wall/simulation`)
- **USD_OUTPUT_DIR**: Where converted USD meshes go (default: `/workspace/s2w-data/usd_files`)
- **RECORDINGS_DIR**: Video output directory (default: `{PROJECT_ROOT}/data/recordings`)
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
- Docker Compose files:
  - Base: `isaac/isaac-launchable/isaac-lab/docker-compose.yml`
  - Override: `isaac/isaac-launchable/isaac-lab/docker-compose.override.yml` (scan2wall-specific mounts)
- Container mounts (configured in docker-compose.override.yml):
  - Host `{PROJECT_ROOT}/src/scan2wall/simulation` → Container `/workspace/s2w-scripts`
  - Host `{PROJECT_ROOT}/data` → Container `/workspace/s2w-data`
- Isaac Lab inside container at: `/workspace/isaaclab`
- Note: Setup scripts auto-configure paths based on actual installation directory

**Key Path Mappings (Host → Container):**
- `{PROJECT_ROOT}/data/uploaded_pictures` → `/workspace/s2w-data/uploaded_pictures`
- `{PROJECT_ROOT}/data/reconstructed_geoms` → `/workspace/s2w-data/reconstructed_geoms`
- `{PROJECT_ROOT}/data/usd_files` → `/workspace/s2w-data/usd_files`
- `{PROJECT_ROOT}/data/recordings` → `/workspace/s2w-data/recordings`
- `{PROJECT_ROOT}/src/scan2wall/simulation` → `/workspace/s2w-scripts`

## Important Technical Details

### ComfyUI Workflow
- Node 112: Load Image
- Node 89: Save Model (GLB output with filename prefix)
- Custom nodes include: ComfyUI-MeshCraft (Hunyuan3d-2-1), Inspyrenet-Rembg, LayerStyle, KJNodes
- Workflow located in: `3d_gen/ComfyUI/custom_nodes/ComfyUI-MeshCraft/workflows/`
- Models stored in `3d_gen/ComfyUI/models/` (~8GB)

### Physics Configuration
- Default mass: 1.0 kg (overridden by Gemini)
- Collision approximation: convexDecomposition (configurable)
- Physics timestep: 0.01s (100 FPS)
- Video output: 1280×720, H.264 NVENC GPU encoding, 50 FPS (configurable)
- Two camera views: static and follow

### Job States
Jobs flow through: `queued` → `processing` → `done` / `error`

### File Validation
Upload server performs two-stage validation:
1. Signature check via `imghdr` (accepts: JPEG, PNG, WEBP, GIF)
2. Pillow `.verify()` to detect corruption

### Performance Bottlenecks
- **3D generation (first run): ~150s** (GPU-bound, largest bottleneck)
  - Model loading: ~8s (only first run)
  - 3D mesh generation: ~15s
  - MultiView PBR texture generation: ~125s (cached after first run → ~40s)
- **3D generation (cached): ~55-60s** (models stay in VRAM)
- Material inference: 2-5s (API latency, Gemini API)
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

**Import errors (ModuleNotFoundError):**
The codebase is now structured as a proper Python package under `src/scan2wall/`.
Install the package with:
```bash
uv sync  # Installs scan2wall package and all dependencies
```
Then use module imports like `python -m scan2wall.server.run`

**Missing dependencies:**
Dependencies are managed via `uv` (see `uv.lock`). To install:
```bash
# Install dependencies with uv
uv sync

# Or manually install upload server dependencies
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

**Path errors in Docker:**
- Host paths: `/home/ubuntu/scan2wall/data/*`
- Container paths: `/workspace/s2w-data/*`
- The ML pipeline automatically converts host → container paths
- Isaac Lab inside container: `/workspace/isaaclab`
- Isaac Worker expects container paths in API requests

## Development Tips

- **First 3D generation takes ~150s** (model loading + full pipeline), **subsequent ones ~55-60s** (models cached in VRAM)
- ComfyUI model caching provides ~64% speedup on subsequent runs
- Device placement fix applied to handle cached models correctly (prevents CUDA errors)
- Set `USE_LLM = False` in `src/scan2wall/pipeline/coordinator.py` to skip Gemini inference (faster testing with default physics)
- Set `USE_SCALING = False` in coordinator.py to disable object scaling (use 1.0)
- Videos saved to `data/recordings/` directory with two views per job (static + follow)
- Simulation skips first 10 frames to avoid warmup artifacts
- Isaac Worker runs persistently - it reuses the camera and scene between jobs for efficiency
- Path conversion happens automatically in pipeline coordinator (host paths → container paths)
- The Isaac Worker HTTP API allows parallel development: you can test conversion/simulation independently
- Check worker queue status with `curl http://localhost:8090/` to see if jobs are pending

## Project Structure Note

The project is organized as a proper Python package:
- `src/scan2wall/` - Main package source code
  - `server/` - Upload server and web UI
  - `pipeline/` - Processing coordinator
  - `inference/` - Gemini material property inference
  - `simulation/` - Isaac Sim integration (isaac_worker.py)
  - `cli/` - Command-line interface
- `3d_gen/ComfyUI/` - ComfyUI installation
  - `custom_nodes/ComfyUI-MeshCraft/workflows/` - 3D mesh generation workflow JSON files
- `data/` - Runtime data (uploads, meshes, recordings, logs)
- `isaac/isaac-launchable/isaac-lab/` - Isaac Lab Docker setup

## Tech Stack Summary
- **Python**: 3.10+ (managed via `uv` package manager)
- **3D Generation**: Hunyuan 3D 2.1 via ComfyUI (with ComfyUI-MeshCraft)
- **Material Analysis**: Google Gemini 2.0 Flash
- **Physics**: NVIDIA Isaac Sim (Isaac Lab) - Docker-based deployment
- **Backend**: FastAPI (upload server) + Python http.server (Isaac Worker)
- **Frontend**: HTML5 + vanilla JavaScript
- **Container Runtime**: Docker + Docker Compose
- **Video Encoding**: FFmpeg with NVENC GPU acceleration
- **Package Management**: uv (fast Python package manager)

## System Ports

| Port | Service | Location | Purpose |
|------|---------|----------|---------|
| 8188 | ComfyUI | Host | 3D mesh generation API |
| 49100 | Upload Server | Host | Web interface, image uploads & video serving |
| 8090 | Isaac Worker | Docker (vscode) | Mesh conversion & simulation API |
| 49110 | Web Viewer | Docker | Isaac Lab streaming interface |
| 49111 | Nginx | Docker | Reverse proxy for web services |
