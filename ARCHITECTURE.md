# scan2wall Architecture

Technical architecture and data flow documentation for the scan2wall project.

## System Overview

scan2wall is a multi-stage pipeline that transforms a 2D photo into a physics-based 3D simulation. The system consists of four main components that communicate via HTTP APIs and file system.

```
┌─────────────┐
│   Phone     │
│  (Camera)   │
└──────┬──────┘
       │ HTTP POST
       │ (image file)
       ▼
┌─────────────────────────────────────────────────────────┐
│                  FastAPI Upload Server                   │
│              (scan2wall/image_collection)                │
│  ┌────────────────────────────────────────────────────┐ │
│  │  Routes:                                            │ │
│  │  • POST /upload  - Receive image                   │ │
│  │  • GET /job/{id} - Job status polling              │ │
│  │  • GET /jobs     - List all jobs                   │ │
│  └────────────────────────────────────────────────────┘ │
└────────┬─────────────────────────────────────────┬──────┘
         │                                         │
         │ 1. Image saved to disk                  │
         │ 2. Job queued                           │
         │                                         │
         ▼                                         ▼
┌──────────────────┐                    ┌──────────────────┐
│  Gemini 2.0 API  │                    │  Background Job  │
│  (ML Pipeline)   │                    │    Processing    │
└────────┬─────────┘                    └────────┬─────────┘
         │                                       │
         │ Material Properties                   │
         │ (mass, friction, etc.)                │
         │                                       │
         └───────────────┬───────────────────────┘
                         │
                         ▼
         ┌───────────────────────────────┐
         │   ComfyUI API Server          │
         │   (3d_gen/server.py)          │
         │                               │
         │   • POST /process             │
         │   • Returns GLB mesh          │
         └───────────┬───────────────────┘
                     │
                     │ HTTP POST (image)
                     │
                     ▼
         ┌───────────────────────────────┐
         │   ComfyUI Worker              │
         │   (Hunyuan 2.1 Model)         │
         │                               │
         │   • Image → 3D mesh           │
         │   • Outputs GLB format        │
         └───────────┬───────────────────┘
                     │
                     │ GLB file saved
                     │
                     ▼
         ┌───────────────────────────────┐
         │   Mesh Converter              │
         │   (isaac_scripts/)            │
         │                               │
         │   • GLB → USD format          │
         │   • Applies physics props     │
         └───────────┬───────────────────┘
                     │
                     │ USD file
                     │
                     ▼
         ┌───────────────────────────────┐
         │   NVIDIA Isaac Sim            │
         │   (Physics Simulation)        │
         │                               │
         │   • Load USD mesh             │
         │   • Create pyramid target     │
         │   • Throw object              │
         │   • Record video              │
         └───────────┬───────────────────┘
                     │
                     │ MP4 video
                     │
                     ▼
              [recordings/ dir]
```

---

## Component Details

### 1. Frontend (Mobile Web Interface)

**Location**: `src/scan2wall/image_collection/app/templates/upload.html`

**Technologies**: HTML5, JavaScript (ES6+), Fetch API

**Features**:
- Camera capture with `capture="environment"` attribute (opens rear camera)
- Client-side file validation (JPEG, PNG, WEBP, GIF)
- File size checking and warnings
- Auto-upload on image selection
- Real-time job status polling
- Visual feedback (spinner, success/error states)

**User Flow**:
1. User opens URL (via QR code or direct link)
2. Taps "Take photo" button
3. Camera opens, user takes photo
4. Frontend validates file type and size
5. Upload begins automatically
6. Status updates via polling every 2 seconds
7. Shows completion or error message

### 2. Upload Server

**Location**: `src/scan2wall/image_collection/app/server.py`

**Technologies**: FastAPI, Uvicorn, Python 3.11+

**Endpoints**:

| Endpoint | Method | Purpose | Response |
|----------|--------|---------|----------|
| `/` | GET | Serve upload page | HTML |
| `/upload` | POST | Receive image upload | `{job_id, status, message}` |
| `/job/{job_id}` | GET | Check job status | `{status, filename, error}` |
| `/jobs` | GET | List all jobs (admin) | `{jobs: [...]}` |

**Image Validation**:
- File signature check using `imghdr` (prevents malicious files)
- Pillow verification (ensures valid image structure)
- Supported: JPEG, PNG, WEBP, GIF

**Job Management**:
```python
JOBS = {
    "job_id": {
        "id": str,
        "filename": str,
        "path": str,
        "status": "queued" | "processing" | "done" | "error",
        "created_at": float,
        "processed_path": str | None,
        "error": str | None
    }
}
```

**Background Processing**:
- Uses FastAPI `BackgroundTasks`
- Non-blocking: user gets immediate response
- Job status persisted in memory (note: resets on server restart)

### 3. ML Pipeline

**Location**: `src/scan2wall/image_collection/ml_pipeline.py`

**Process Flow**:

#### Step 1: Material Property Inference
```python
get_object_properties(image_path) -> dict
```

Uses **Gemini 2.0 Flash** to analyze the image and infer:
- Object type and use case
- Materials (with probabilities)
- Rigidity (rigid vs deformable)
- Dimensions (length, width, height in meters)
- Weight (kg)
- Friction coefficients (static and dynamic)
- Confidence score

**Sample Output**:
```json
{
  "object_type": "coffee mug",
  "materials": [{"name": "ceramic", "prob": 0.9}],
  "weight_kg": {"value": 0.35},
  "friction_coefficients": {
    "static": 0.6,
    "dynamic": 0.5
  },
  "confidence_overall": 0.85
}
```

#### Step 2: 3D Mesh Generation
```python
POST https://[comfyui-server]:8012/process
  Body: multipart/form-data
    - file: image file
    - timeout: 300
    - job_id: unique identifier

  Returns: GLB file (binary)
```

**Model**: Hunyuan 2.1 (Tencent's image-to-3D model)
- State-of-the-art quality
- ~30-60 seconds generation time
- Outputs GLB (GL Transmission Format)

#### Step 3: Mesh Conversion
```python
convert_mesh(glb_path, output_name, mass, friction_static, friction_dynamic)
```

Converts GLB → USD (Universal Scene Description) format:
- Applies physics properties from Gemini inference
- Sets mass, friction coefficients
- Configures collision properties
- Uses Isaac Sim's mesh converter tool

**Command**:
```bash
python /workspace/isaaclab/scripts/tools/convert_mesh.py \
  input.glb output.usd \
  --kit_args='--headless' \
  --mass 0.35 \
  --static-friction 0.6 \
  --dynamic-friction 0.5
```

#### Step 4: Simulation Trigger
```python
make_throwing_anim(usd_path)
```

Spawns detached Isaac Sim process:
- Loads USD mesh
- Runs `test_place_obj_video.py`
- Records simulation to MP4
- Runs in background (fire-and-forget)

### 4. ComfyUI Server

**Location**: `3d_gen/server.py`

**Purpose**: HTTP wrapper around ComfyUI for image-to-3D conversion

**Technology Stack**:
- FastAPI
- ComfyUI (node-based workflow system)
- Hunyuan 2.1 model nodes

**Process**:
1. Receives image via POST
2. Saves to temporary directory
3. Copies to ComfyUI input directory
4. Loads workflow JSON template
5. Updates workflow nodes with:
   - Input image path
   - Unique output prefix (job_id)
6. Queues prompt to ComfyUI on port 8188
7. Polls output directory for GLB file
8. Returns GLB file when ready

**Workflow Nodes**:
- Node 112: Load Image
- Node 89: Save Model (GLB output)

### 5. Isaac Sim Integration

**Location**: `isaac_scripts/test_place_obj_video.py`

**Simulation Setup**:

```python
# Scene elements
- Ground plane
- Distant light
- Custom USD object (loaded from conversion)
- Pyramid of 20 levels (blue cubes)

# Physics configuration
- dt = 0.01 (100 FPS physics)
- Rigid body dynamics
- Collision detection
```

**Throwing Mechanics**:
```python
throw_object(
    prim_path="/World/Objects/custom_obj",
    direction=(0.0, 1.0, 0.1),  # mostly Y, slight up
    speed=17.0  # m/s
)
```

Sets initial linear velocity on rigid body:
- Direction normalized to unit vector
- Velocity = direction × speed
- Applied via `UsdPhysics.RigidBodyAPI`

**Video Recording**:
- Uses `omni.kit.viewport.utility` (not Replicator)
- Captures at 1920×1080 by default
- Records 200 steps (2 seconds at 100 FPS physics)
- Skips first 10 frames (warmup)
- Encodes with ffmpeg (H.264, yuv420p)
- Output: `recordings/sim_run.mp4`

**Camera Position**:
```python
sim.set_camera_view(
    eye=[0.0, -4.0, 4.0],    # Camera position
    target=[0.0, 0.0, 3.0]   # Look at target
)
```

---

## Data Flow Diagram

```
Image Upload
     │
     ├─► Validation (client + server)
     │
     ├─► Save to: uploads/YYYYMMDD-HHMMSS-{uuid}-{filename}
     │
     ├─► Create Job Entry (status: queued)
     │
     ├─► Background Task Start
     │
     └─► Return job_id to client
              │
              ├─► Client polls /job/{job_id} every 2s
              │
              └─► Job Status Updates:
                       │
                  "queued" → "processing" → "done"/"error"
                       │
                       └─► Processing Steps:
                            │
                            1. Gemini API Call
                            │   ├─► Analyze image
                            │   └─► Return properties JSON
                            │
                            2. ComfyUI Request
                            │   ├─► POST to /process
                            │   ├─► Queue workflow
                            │   ├─► Generate 3D mesh
                            │   └─► Return GLB file
                            │
                            3. Mesh Conversion
                            │   ├─► GLB → USD
                            │   ├─► Apply physics props
                            │   └─► Save to /workspace/isaaclab/
                            │
                            4. Isaac Sim Trigger
                                ├─► Spawn process
                                ├─► Load scene
                                ├─► Run simulation
                                ├─► Record video
                                └─► Save to recordings/
```

---

## File Structure

```
scan2wall/
├── src/scan2wall/
│   ├── image_collection/
│   │   ├── app/
│   │   │   ├── server.py         # FastAPI server
│   │   │   └── templates/
│   │   │       └── upload.html   # Mobile UI
│   │   ├── ml_pipeline.py        # Main processing logic
│   │   ├── run.py                # Server launcher (public IP)
│   │   ├── run_desktop.py        # Desktop testing version
│   │   ├── uploads/              # Uploaded images (gitignored)
│   │   └── processed/            # Generated GLB files (gitignored)
│   └── material_properties/
│       └── get_object_properties.py  # Gemini API wrapper
│
├── 3d_gen/
│   ├── ComfyUI/                  # ComfyUI installation
│   ├── workflows/
│   │   └── image_to_3D_fast.json # Hunyuan 2.1 workflow
│   ├── server.py                 # ComfyUI HTTP API
│   ├── comfy.sh                  # ComfyUI installer
│   ├── modeldownload.sh          # Model downloader
│   └── input/                    # ComfyUI input dir (gitignored)
│
├── isaac_scripts/
│   ├── convert_mesh.py           # GLB → USD converter
│   ├── test_place_obj.py         # Basic simulation test
│   └── test_place_obj_video.py   # Simulation with video recording
│
├── recordings/                   # Simulation videos (gitignored)
├── pyproject.toml                # Python dependencies
├── uv.lock                       # Locked dependencies
├── .env                          # Environment variables (gitignored)
└── upload_page_qr.png            # Generated QR code (gitignored)
```

---

## API Specifications

### POST /upload

**Request**:
```
Content-Type: multipart/form-data

file: <binary image data>
```

**Response** (201 Created):
```json
{
  "message": "✅ File uploaded successfully.",
  "job_id": "a1b2c3d4e5f6...",
  "filename": "20241012-143022-abc123-photo.jpg",
  "status": "queued"
}
```

**Errors**:
- 400: Invalid file type or corrupted image
- 500: Server error during save

### GET /job/{job_id}

**Response** (200 OK):
```json
{
  "job_id": "a1b2c3d4e5f6...",
  "status": "processing",
  "filename": "20241012-143022-abc123-photo.jpg",
  "created_at": 1697123456.789,
  "processed_path": "/path/to/output.glb",
  "error": null
}
```

**Status Values**:
- `queued`: Job created, not started
- `processing`: Currently running ML pipeline
- `done`: Successfully completed
- `error`: Failed (check `error` field)

**Errors**:
- 404: Job ID not found

### POST /process (ComfyUI Server)

**Request**:
```
Content-Type: multipart/form-data

file: <image file>
timeout: 300
job_id: "a1b2c3d4e5f6..."
```

**Response**:
```
Content-Type: model/gltf-binary

<binary GLB data>
```

**Errors**:
- 400: Invalid prompt JSON or missing node
- 500: Failed to save upload
- 504: Timeout waiting for ComfyUI output

---

## Configuration

### Environment Variables

| Variable | Purpose | Default | Required |
|----------|---------|---------|----------|
| `GOOGLE_API_KEY` | Gemini API key | - | Yes |
| `PORT` | Upload server port | 49100 | No |
| `COMFY_SERVER_URL` | ComfyUI API URL | http://127.0.0.1:8012 | No |
| `COMFY_INPUT_DIR` | ComfyUI input path | ~/scan2wall/3d_gen/input | No |

### Hardcoded Paths (to fix)

⚠️ These should be moved to environment variables:

1. **ml_pipeline.py:24** - ComfyUI server URL
2. **ml_pipeline.py:61** - Isaac converter script path
3. **ml_pipeline.py:98** - Isaac simulation script path
4. **server.py:18** - ComfyUI output directory
5. **server.py:22** - Workflow JSON path

---

## Performance Characteristics

### Timing Breakdown (approximate)

| Stage | Time | Bottleneck |
|-------|------|-----------|
| Upload | 1-5s | Network bandwidth |
| Gemini API | 2-5s | API latency |
| 3D Generation | 30-60s | GPU compute (Hunyuan 2.1) |
| Mesh Conversion | 5-10s | CPU + I/O |
| Simulation | 10-20s | GPU compute (Isaac Sim) |
| Video Encoding | 2-5s | CPU (ffmpeg) |
| **Total** | **50-100s** | **3D generation** |

### Resource Usage

| Component | CPU | RAM | VRAM | Storage |
|-----------|-----|-----|------|---------|
| Upload Server | Low | ~100MB | - | Negligible |
| ComfyUI | Medium | ~4GB | 6-8GB | ~20GB (models) |
| Isaac Sim | High | ~8GB | 4-6GB | ~10GB |
| Gemini API | - | - | - | - |

---

## Scalability Considerations

### Current Limitations

1. **Single-threaded processing**: Jobs processed sequentially
2. **In-memory job storage**: Lost on server restart
3. **No job queue**: No prioritization or retry logic
4. **Synchronous ComfyUI**: One generation at a time
5. **No cleanup**: Uploaded files accumulate indefinitely

### Potential Improvements

1. **Job Queue System**: Redis + Celery for distributed processing
2. **Persistent Storage**: Database for job metadata
3. **Multi-GPU Support**: Parallel ComfyUI instances
4. **Cloud Storage**: S3/GCS for uploads and outputs
5. **Cleanup Jobs**: Automatic deletion of old files
6. **Webhooks**: Notify client on completion (vs polling)
7. **Caching**: Cache frequently-generated meshes

---

## Security Considerations

### Current Protections

✅ File signature validation (prevents fake extensions)
✅ Pillow verification (prevents malformed images)
✅ Allowed file types whitelist
✅ Filename sanitization

### Potential Risks

⚠️ No rate limiting (DDoS vulnerability)
⚠️ No authentication (public access)
⚠️ No file size limits on server side
⚠️ API keys in environment (consider secret management)
⚠️ No HTTPS (transmits images unencrypted)

### Recommendations

1. Add rate limiting (e.g., slowapi)
2. Implement authentication (API keys or OAuth)
3. Add file size limits (FastAPI `File(max_size=...)`)
4. Use secret management (AWS Secrets Manager, Vault)
5. Deploy with HTTPS (Let's Encrypt)
6. Add CORS restrictions

---

## Error Handling

### Frontend
- File type validation before upload
- Network error catching and display
- Timeout handling (stops polling after 5 minutes)

### Backend
- Comprehensive exception catching in pipeline
- Job status updates on failure
- Detailed error messages in job metadata

### Missing
- Retry logic for transient failures
- Dead letter queue for failed jobs
- Alerting/monitoring system

---

## Testing Strategy

### Unit Tests (not yet implemented)

Suggested test coverage:
- Image validation functions
- Material property parsing
- Mesh conversion parameters
- Job status transitions

### Integration Tests

Manual testing checklist:
- [ ] Upload valid image → success
- [ ] Upload non-image → rejection
- [ ] Upload oversized file → warning
- [ ] Check job status → correct state
- [ ] Complete pipeline → video generated
- [ ] ComfyUI timeout → error state
- [ ] Network failure → error message

---

## Future Architecture

### Email Integration (see EMAIL_INTEGRATION.md)

```
Email Server → Parse Image → Upload API → Existing Pipeline
                    │
                    └─► Reply with video link
```

### Multi-User Support

```
User Auth → Personal Job Queue → Isolated File Storage
                    │
                    └─► Job History Dashboard
```

### Real-Time Updates

```
WebSocket Connection → Live Status Updates → Progress Bar
                            │
                            └─► Stream Logs
```

---

## Related Documentation

- **SETUP.md** - Installation and configuration guide
- **EMAIL_INTEGRATION.md** - Email feature design
- **README.md** - Quick start guide
- **Isaac Sim Docs**: https://docs.omniverse.nvidia.com/isaacsim/
- **ComfyUI**: https://github.com/comfyanonymous/ComfyUI
- **Hunyuan 2.1**: https://github.com/Tencent/Hunyuan3D-2
