import time
import uuid
from pathlib import Path
from typing import Dict, Any, List
import imghdr
from fastapi import FastAPI, File, UploadFile, Request, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from PIL import Image
import io
from scan2wall.pipeline.coordinator import process_image

# Rate limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "JOBS"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Initialize rate limiter (works with Cloudflare via X-Forwarded-For)
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="scan2wall")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

# Mount static files directory
static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

JOBS: Dict[str, Dict[str, Any]] = {}


def get_queue_info(job_id: str) -> dict:
    """Calculate queue position and estimated wait time for a job.

    Args:
        job_id: The job ID to check

    Returns:
        dict with keys:
            - queue_position: Position in queue (1-indexed), 0 if processing/done
            - queue_total: Total jobs currently queued or processing (global count)
            - estimated_wait_seconds: Estimated wait time in seconds
    """
    # Count total jobs in queue/processing (global count, always return this)
    total_queued = sum(1 for j in JOBS.values() if j["status"] in ["queued", "processing"])

    if job_id not in JOBS:
        return {"queue_position": 0, "queue_total": total_queued, "estimated_wait_seconds": 0}

    job = JOBS[job_id]

    # Count jobs ahead of this one (older jobs that are queued or processing)
    job_created_at = job["created_at"]
    jobs_ahead = 0

    for other_id, other_job in JOBS.items():
        if other_job["status"] in ["queued", "processing"]:
            # Count jobs created before this one
            if other_job["created_at"] < job_created_at:
                jobs_ahead += 1

    # Position is 1-indexed (1st in queue, 2nd in queue, etc.)
    queue_position = jobs_ahead + 1 if job["status"] == "queued" else 0

    # Estimate 60 seconds per job ahead
    estimated_wait_seconds = jobs_ahead * 60

    return {
        "queue_position": queue_position,
        "queue_total": total_queued,  # Always return global count
        "estimated_wait_seconds": estimated_wait_seconds
    }


@app.get("/", response_class=HTMLResponse)
async def upload_page(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})

@app.post("/upload")
@limiter.limit("10/hour")  # 10 uploads per IP per hour
async def upload_image(request: Request, background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    print("[INFO] Received file.")

    # --- Step 1: read all bytes once ---
    contents = await file.read()
    file.file.seek(0)  # just in case

    # --- Step 1.5: Check file size (20MB limit) ---
    MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"📦 File too large! Your image is {len(contents) / 1024 / 1024:.1f}MB. Maximum size is 20MB. Try compressing your image or taking a photo with lower resolution."
        )

    # --- Step 2: signature check ---
    kind = imghdr.what(None, contents[:512])
    if kind not in {"jpeg", "png", "webp", "gif", "jpg"}:
        raise HTTPException(
            status_code=400,
            detail=f"🚫 '{file.filename}' is not a valid image. Supported: JPEG, PNG, WEBP, GIF."
        )

    # --- Step 3: Pillow validation ---
    try:
        Image.open(io.BytesIO(contents)).verify()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail=f"⚠️ '{file.filename}' appears corrupted or unreadable. Try again with a valid image."
        )

    # --- Step 4: save ---
    job_id = uuid.uuid4().hex  # Full 32-character UUID (prevents enumeration)

    ts = time.strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:6]
    fname = f"{ts}.{kind}"
    dest = UPLOAD_DIR / job_id
    dest.mkdir(parents=True, exist_ok=True)
    spath = dest / fname

    spath.write_bytes(contents)  # simpler save

    # --- Step 5: queue job ---
    JOBS[job_id] = {
        "id": job_id,
        "filename": fname,
        "path": str(spath),
        "status": "queued",
        "status_detail": "Waiting in queue...",
        "created_at": time.time(),
        "processed_path": None,
        "error": None,
    }

    background_tasks.add_task(_run_pipeline, job_id, str(dest))
    return JSONResponse(
        {"message": "✅ File uploaded successfully.", "job_id": job_id, "filename": fname, "status": "queued"},
        status_code=201,
    )

@app.get("/job/{job_id}")
@limiter.limit("60/minute")  # 60 status checks per minute (1/second reasonable)
async def get_job_status(request: Request, job_id: str):
    """Get the status of a processing job."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job = JOBS[job_id]
    job_dir = UPLOAD_DIR / job_id

    # Check availability of each asset
    # Check for new segmentation cropped files or old nobackground files
    cropped_files = list(job_dir.glob(f"{job_id}_*_seg_cropped_*.png"))
    nobackground_files = list(job_dir.glob(f"{job_id}_nobackground_*.png"))
    nobackground_ready = len(cropped_files) > 0 or len(nobackground_files) > 0

    decoded_ready = len(list(job_dir.glob(f"{job_id}_decoded_*.stl"))) > 0
    glb_ready = (job_dir / f"{job_id}.glb").exists()
    properties_ready = (job_dir / "properties.json").exists()

    # Check both video files in job directory
    video_static_path = UPLOAD_DIR / job_id / f"{job_id}_static.mp4"
    video_follow_path = UPLOAD_DIR / job_id / f"{job_id}_follow.mp4"
    video_static_ready = video_static_path.exists()
    video_follow_ready = video_follow_path.exists()
    video_ready = video_static_ready and video_follow_ready

    # Get queue information
    queue_info = get_queue_info(job_id)

    return JSONResponse({
        "job_id": job["id"],
        "status": job["status"],
        "status_detail": job.get("status_detail", "Processing..."),
        "filename": job["filename"],
        "created_at": job["created_at"],
        "processed_path": job.get("processed_path"),
        "video_filename": job.get("video_filename"),
        "error": job.get("error"),
        "queue_position": queue_info["queue_position"],
        "queue_total": queue_info["queue_total"],
        "estimated_wait_seconds": queue_info["estimated_wait_seconds"],
        "assets": {
            "nobackground_ready": nobackground_ready,
            "decoded_ready": decoded_ready,
            "glb_ready": glb_ready,
            "properties_ready": properties_ready,
            "video_ready": video_ready,
            "video_static_ready": video_static_ready,
            "video_follow_ready": video_follow_ready
        }
    })

# /jobs endpoint removed for privacy - users should not see other users' jobs
# For queue position, each user only sees their own job via /job/{job_id}

@app.get("/video/{job_id}")
async def get_video(job_id: str, view: str = "static", download: bool = False):
    """Serve the simulation video for a completed job.

    Args:
        job_id: The job ID
        view: Which camera view to serve ('static' or 'follow')
        download: Whether to force download
    """
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job = JOBS[job_id]

    # Check if job is complete and has a video
    if job["status"] == "rejected":
        raise HTTPException(status_code=400, detail="Segmentation validation failed - no video available")
    elif job["status"] != "done":
        raise HTTPException(status_code=400, detail="Job not yet complete")

    # Validate view parameter
    if view not in ["static", "follow"]:
        raise HTTPException(status_code=400, detail="Invalid view parameter. Must be 'static' or 'follow'")

    video_filename = f"{job_id}_{view}.mp4"
    video_path = UPLOAD_DIR / job_id / video_filename

    if not video_path.exists():
        raise HTTPException(status_code=404, detail=f"Video file not found for {view} view")

    headers = {}
    if download:
        headers["Content-Disposition"] = f"attachment; filename={video_filename}"

    return FileResponse(
        path=str(video_path),
        media_type="video/mp4",
        filename=video_filename,
        headers=headers
    )

@app.get("/asset/{job_id}/original")
async def get_original_image(job_id: str):
    """Serve the original uploaded image."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job = JOBS[job_id]
    image_path = Path(job["path"])

    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Original image not found")

    return FileResponse(
        path=str(image_path),
        media_type="image/jpeg",
        filename=f"{job_id}_original{image_path.suffix}"
    )

@app.get("/asset/{job_id}/nobackground")
async def get_nobackground_image(job_id: str, download: bool = False):
    """Serve the image with background removed (final validated segmentation image)."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job_dir = UPLOAD_DIR / job_id

    # First, look for the final validated image (saved by coordinator)
    final_image = job_dir / f"{job_id}_final_segmented.png"
    if final_image.exists():
        headers = {}
        if download:
            headers["Content-Disposition"] = f"attachment; filename={job_id}_segmented.png"

        return FileResponse(
            path=str(final_image),
            media_type="image/png",
            filename=f"{job_id}_segmented.png",
            headers=headers
        )

    # Fallback: look for cropped segmentation files (SAM or Inspyre)
    # Pattern: {job_id}_sam_seg_cropped_*.png or {job_id}_inspyre_seg_cropped_*.png
    cropped_files = list(job_dir.glob(f"{job_id}_*_seg_cropped_*.png"))

    # Fallback to old nobackground pattern for backwards compatibility
    if not cropped_files:
        cropped_files = list(job_dir.glob(f"{job_id}_nobackground_*.png"))

    if not cropped_files:
        raise HTTPException(status_code=404, detail="Segmented image not yet available")

    headers = {}
    if download:
        headers["Content-Disposition"] = f"attachment; filename={job_id}_segmented.png"

    return FileResponse(
        path=str(cropped_files[0]),
        media_type="image/png",
        filename=f"{job_id}_segmented.png",
        headers=headers
    )

@app.get("/asset/{job_id}/decoded")
async def get_decoded_mesh(job_id: str, download: bool = False):
    """Serve the untextured (processed) STL mesh."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job_dir = UPLOAD_DIR / job_id
    # Find the processed STL file
    decoded_files = list(job_dir.glob(f"{job_id}_processed_*.stl"))

    if not decoded_files:
        raise HTTPException(status_code=404, detail="Decoded mesh not yet available")

    headers = {}
    if download:
        headers["Content-Disposition"] = f"attachment; filename={job_id}_decoded.stl"

    return FileResponse(
        path=str(decoded_files[0]),
        media_type="application/octet-stream",
        filename=f"{job_id}_decoded.stl",
        headers=headers
    )

@app.get("/asset/{job_id}/glb")
async def get_glb_mesh(job_id: str, download: bool = False):
    """Serve the textured GLB mesh."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job_dir = UPLOAD_DIR / job_id
    glb_file = job_dir / f"{job_id}.glb"

    if not glb_file.exists():
        raise HTTPException(status_code=404, detail="GLB mesh not yet available")

    headers = {}
    if download:
        headers["Content-Disposition"] = f"attachment; filename={job_id}.glb"

    return FileResponse(
        path=str(glb_file),
        media_type="model/gltf-binary",
        filename=f"{job_id}.glb",
        headers=headers
    )

@app.get("/asset/{job_id}/properties")
async def get_properties(job_id: str, download: bool = False):
    """Serve the physical properties JSON."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job_dir = UPLOAD_DIR / job_id
    properties_file = job_dir / "properties.json"

    if not properties_file.exists():
        raise HTTPException(status_code=404, detail="Properties not yet available")

    headers = {}
    if download:
        headers["Content-Disposition"] = f"attachment; filename={job_id}_properties.json"

    return FileResponse(
        path=str(properties_file),
        media_type="application/json",
        filename=f"{job_id}_properties.json",
        headers=headers
    )

@app.get("/asset/{job_id}/logs")
async def get_job_logs(job_id: str, download: bool = False):
    """Serve the per-job log file."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job_dir = UPLOAD_DIR / job_id
    log_file = job_dir / "job.log"

    if not log_file.exists():
        raise HTTPException(status_code=404, detail="Job log not yet available")

    headers = {}
    if download:
        headers["Content-Disposition"] = f"attachment; filename={job_id}_job.log"

    return FileResponse(
        path=str(log_file),
        media_type="text/plain",
        filename=f"{job_id}_job.log",
        headers=headers
    )

def _run_pipeline(job_id: str, path: str) -> None:
    JOBS[job_id]["status"] = "processing"
    JOBS[job_id]["status_detail"] = "Starting pipeline..."
    try:
        out_path = process_image(job_id, path, JOBS)
        JOBS[job_id]["status"] = "done"
        JOBS[job_id]["status_detail"] = "Complete! Simulation videos generated."
        JOBS[job_id]["processed_path"] = out_path

        # Store both video paths in job directory
        video_static_path = UPLOAD_DIR / job_id / f"{job_id}_static.mp4"
        video_follow_path = UPLOAD_DIR / job_id / f"{job_id}_follow.mp4"
        if video_static_path.exists() and video_follow_path.exists():
            JOBS[job_id]["video_static_path"] = str(video_static_path)
            JOBS[job_id]["video_follow_path"] = str(video_follow_path)
    except Exception as e:
        # Check if status was already set to "rejected" by the pipeline
        if JOBS[job_id]["status"] != "rejected":
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["status_detail"] = f"Error: {str(e)}"
            JOBS[job_id]["error"] = repr(e)
        else:
            # Keep rejected status and update detail message
            JOBS[job_id]["status_detail"] = str(e)
            JOBS[job_id]["error"] = str(e)
        print(f"[ERROR] Job {job_id} failed: {e}")
