# scan2wall Architecture

Technical architecture for the scan2wall project - a pipeline that transforms 2D photos into physics-based 3D simulations.

## System Overview

scan2wall is a multi-stage pipeline with four main components communicating via HTTP APIs and file system.

```
Phone (Camera)
     │
     ├──> FastAPI Upload Server (port 49100)
     │         │
     │         ├──> Gemini 2.0 Flash API (material properties)
     │         │
     │         └──> ComfyUI API Server (port 8012)
     │                   │
     │                   └──> Hunyuan 3D 2.1 (GLB mesh generation)
     │                             │
     │                             └──> Mesh Converter (GLB → USD)
     │                                       │
     │                                       └──> Isaac Sim (physics + video)
     │
     └──> Video output (recordings/)
```

---

## Key Technologies

### 1. Hunyuan 3D 2.1 (Image-to-3D Generation)

**What**: Tencent's state-of-the-art image-to-3D model
**Role**: Converts 2D photos into 3D meshes

- Runs via ComfyUI node-based workflow system
- Generates GLB format (GL Transmission Format)
- ~30-60 seconds generation time
- Requires 6-8GB VRAM

**Workflow**: `3d_gen/workflows/image_to_3D_fast.json`

### 2. ComfyUI (Workflow Engine)

**What**: Node-based workflow system for AI models
**Role**: Orchestrates the 3D generation pipeline

- Backend runs on port 8188
- Custom HTTP API wrapper on port 8012
- Manages model loading and execution
- Supports custom nodes and extensions

**Custom Nodes Used**:
- ComfyUI-Hunyuan3d-2-1 (main 3D generation)
- ComfyUI-Inspyrenet-Rembg (background removal)
- ComfyUI_LayerStyle (image preprocessing)
- ComfyUI-KJNodes (utilities)

### 3. Google Gemini 2.0 Flash (Material Inference)

**What**: Google's multimodal LLM
**Role**: Analyzes images to infer physical properties

Extracts:
- Object type and materials
- Mass (kg)
- Dimensions (meters)
- Friction coefficients (static/dynamic)
- Rigidity characteristics

**Example output**:
```json
{
  "object_type": "coffee mug",
  "weight_kg": {"value": 0.35},
  "dimensions_m": {
    "length": {"value": 0.08},
    "width": {"value": 0.08},
    "height": {"value": 0.10}
  },
  "friction_coefficients": {
    "static": 0.6,
    "dynamic": 0.5
  }
}
```

### 4. NVIDIA Isaac Sim (Physics Simulation)

**What**: NVIDIA's robotics simulation platform
**Role**: Runs physics-based throwing simulation

- Converts USD mesh with physics properties
- Creates pyramid target (20 levels of cubes)
- Throws object at 17 m/s
- Records video at 1920×1080
- Physics runs at 100 FPS (dt=0.01)

**Output**: MP4 video encoded with ffmpeg (H.264)

---

## Data Flow

### Step 1: Upload
- User captures photo via mobile web interface
- Image validated (JPEG/PNG/WEBP/GIF, signature check)
- Saved to `uploads/YYYYMMDD-HHMMSS-{uuid}-{filename}`
- Job created with status: `queued`

### Step 2: Material Analysis
- Image sent to Gemini 2.0 Flash API
- Response parsed for physical properties
- Properties stored with job metadata

### Step 3: 3D Generation
- Image posted to ComfyUI API server
- Server copies image to ComfyUI input directory
- Workflow queued with Hunyuan 3D 2.1 model
- GLB mesh generated and returned
- Saved to `processed/{job_id}.glb`

### Step 4: Mesh Conversion
- GLB converted to USD format (Isaac Sim compatible)
- Physics properties applied from Gemini inference:
  - Mass
  - Static/dynamic friction
  - Collision geometry
- USD saved to Isaac workspace

### Step 5: Simulation
- Isaac Sim spawned in detached process
- Scene setup: ground plane, lighting, pyramid
- Custom object loaded from USD
- Throwing velocity applied (direction + speed)
- Simulation recorded for 200 steps (~2 seconds)
- Video encoded and saved to `recordings/`

**Job status**: `queued` → `processing` → `done`/`error`

---

## Component Details

### FastAPI Upload Server

**Location**: `src/scan2wall/image_collection/app/server.py`

**Endpoints**:
- `GET /` - Serve upload page
- `POST /upload` - Receive image, create job
- `GET /job/{job_id}` - Poll job status
- `GET /jobs` - Admin view of all jobs

**Features**:
- Background task processing
- In-memory job storage
- File validation (signature + Pillow verification)
- Real-time status updates

### ComfyUI API Wrapper

**Location**: `3d_gen/server.py`

**Process**:
1. Receives image via POST to `/process`
2. Copies to ComfyUI input directory
3. Loads workflow template JSON
4. Updates nodes with job-specific data
5. Queues prompt to ComfyUI (port 8188)
6. Polls output directory for GLB file
7. Returns GLB binary data

**Key Nodes**:
- Node 112: Load Image
- Node 89: Save Model (GLB output)

### Isaac Sim Integration

**Location**: `isaac_scripts/test_place_obj_video.py`

**Scene Elements**:
- Ground plane
- Distant light
- Custom USD object (user's mesh)
- Pyramid: 20 levels of blue cubes

**Throwing Mechanics**:
```python
throw_object(
    prim_path="/World/Objects/custom_obj",
    direction=(0.0, 1.0, 0.1),  # forward + slight up
    speed=17.0  # m/s
)
```

**Video Recording**:
- Captures viewport at 1920×1080
- Records 200 physics steps
- Skips first 10 frames (warmup)
- Encodes with ffmpeg (yuv420p color space)

**Camera Position**:
```python
eye = [0.0, -4.0, 4.0]
target = [0.0, 0.0, 3.0]
```

---

## File Structure

```
scan2wall/
├── src/scan2wall/
│   ├── image_collection/
│   │   ├── app/
│   │   │   ├── server.py              # FastAPI server
│   │   │   └── templates/upload.html  # Mobile UI
│   │   ├── ml_pipeline.py             # Main processing logic
│   │   ├── run.py                     # Server launcher
│   │   └── uploads/                   # User images
│   └── material_properties/
│       └── get_object_properties.py   # Gemini API wrapper
│
├── 3d_gen/
│   ├── ComfyUI/                       # ComfyUI installation
│   ├── workflows/
│   │   └── image_to_3D_fast.json      # Hunyuan workflow
│   ├── server.py                      # ComfyUI HTTP API
│   └── setup_comfyui.sh               # Setup script
│
├── isaac_scripts/
│   ├── convert_mesh.py                # GLB → USD converter
│   └── test_place_obj_video.py        # Simulation + recording
│
└── recordings/                        # Output videos
```

---

## Performance

### Timing Breakdown
| Stage | Time | Bottleneck |
|-------|------|-----------|
| Upload | 1-5s | Network |
| Gemini API | 2-5s | API latency |
| 3D Generation | 30-60s | **GPU compute** |
| Mesh Conversion | 5-10s | CPU + I/O |
| Simulation | 10-20s | GPU compute |
| Video Encoding | 2-5s | CPU |
| **Total** | **50-100s** | **3D generation** |

### Resource Usage
| Component | VRAM | RAM | Storage |
|-----------|------|-----|---------|
| ComfyUI | 6-8GB | ~4GB | ~20GB (models) |
| Isaac Sim | 4-6GB | ~8GB | ~10GB |
| Upload Server | - | ~100MB | Negligible |

---

## Configuration

### Environment Variables

#### Core Variables

| Variable | Purpose | Required | Default |
|----------|---------|----------|---------|
| `GOOGLE_API_KEY` | Gemini API authentication | Yes | - |
| `ISAAC_INSTANCE_ADDRESS` | ComfyUI API endpoint | Yes | - |
| `PORT` | Upload server port | No | 49100 |
| `COMFY_SERVER_URL` | ComfyUI API URL | No | http://127.0.0.1:8012 |
| `COMFY_INPUT_DIR` | ComfyUI input path | No | ~/scan2wall/3d_gen/input |

#### Path Configuration (Advanced)

All paths are **auto-detected** from the project structure by default. Set these only for custom deployments:

| Variable | Purpose | Default |
|----------|---------|---------|
| `PROJECT_ROOT` | Project root directory | Auto-detected |
| `ISAAC_WORKSPACE` | Isaac Lab workspace | /workspace/isaaclab |
| `ISAAC_SCRIPTS_DIR` | Isaac scripts location | ${PROJECT_ROOT}/isaac_scripts |
| `ASSETS_CSV` | Assets tracking file | ${PROJECT_ROOT}/assets.csv |
| `RECORDINGS_DIR` | Video output directory | ${PROJECT_ROOT}/recordings |
| `USD_OUTPUT_DIR` | USD mesh output directory | ${ISAAC_WORKSPACE} |

**Single-instance setup**: Set `ISAAC_INSTANCE_ADDRESS=http://127.0.0.1:8012/process` and optionally customize `ISAAC_WORKSPACE`.

**Path utilities**: Use `python -m scan2wall.utils.paths` to view current configuration and validate paths.

See `.env.example` for full configuration template.

---

## Error Handling

### Frontend
- File type validation before upload
- Network error catching with user feedback
- Polling timeout after 5 minutes

### Backend
- Exception catching in ML pipeline
- Job status updates on failure
- Detailed error messages in job metadata

---

## Scalability Considerations

### Current Limitations
- Sequential job processing (one at a time)
- In-memory job storage (lost on restart)
- No job queue or prioritization
- Single ComfyUI instance
- No automatic file cleanup

### Potential Improvements
- Job queue system (Redis + Celery)
- Database for persistent job storage
- Multi-GPU parallel processing
- Cloud storage (S3/GCS)
- WebSocket for real-time updates
- Automatic cleanup of old files

---

## Related Documentation

- **[README.md](README.md)** - Quick start guide
- **[SETUP.md](SETUP.md)** - Installation instructions
- **[EMAIL_INTEGRATION.md](EMAIL_INTEGRATION.md)** - Email feature design
- **[ComfyUI Docs](https://github.com/comfyanonymous/ComfyUI)**
- **[Hunyuan 3D 2.1](https://github.com/Tencent/Hunyuan3D-2)**
- **[Isaac Sim Docs](https://docs.omniverse.nvidia.com/isaacsim/)**
