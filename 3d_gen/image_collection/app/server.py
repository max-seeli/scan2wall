import time
import uuid
from pathlib import Path
from typing import Dict, Any, List
import imghdr
from fastapi import FastAPI, File, UploadFile, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi import HTTPException
from PIL import Image
import io
import imghdr
from fastapi import HTTPException
from ml_pipeline import process_image

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "JOBS"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="scan2wall")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

# Mount static files directory
static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

JOBS: Dict[str, Dict[str, Any]] = {}


@app.get("/", response_class=HTMLResponse)
async def upload_page(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})

@app.post("/upload")
async def upload_image(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    print("[INFO] Received file.")

    # --- Step 1: read all bytes once ---
    contents = await file.read()
    file.file.seek(0)  # just in case
    
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
    job_id = uuid.uuid4().hex[:8]

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
async def get_job_status(job_id: str):
    """Get the status of a processing job."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job = JOBS[job_id]
    job_dir = UPLOAD_DIR / job_id

    # Check availability of each asset
    nobackground_ready = len(list(job_dir.glob(f"{job_id}_nobackground_*.png"))) > 0
    decoded_ready = len(list(job_dir.glob(f"{job_id}_decoded_*.stl"))) > 0
    glb_ready = (job_dir / f"{job_id}.glb").exists()
    properties_ready = (job_dir / "properties.json").exists()

    # Check video file in job directory
    video_path = UPLOAD_DIR / job_id / f"{job_id}_sim.mp4"
    video_ready = video_path.exists()

    return JSONResponse({
        "job_id": job["id"],
        "status": job["status"],
        "status_detail": job.get("status_detail", "Processing..."),
        "filename": job["filename"],
        "created_at": job["created_at"],
        "processed_path": job.get("processed_path"),
        "video_filename": job.get("video_filename"),
        "error": job.get("error"),
        "assets": {
            "nobackground_ready": nobackground_ready,
            "decoded_ready": decoded_ready,
            "glb_ready": glb_ready,
            "properties_ready": properties_ready,
            "video_ready": video_ready
        }
    })

@app.get("/jobs")
async def list_jobs():
    """List all jobs (for debugging/admin)."""
    return JSONResponse({"jobs": list(JOBS.values())})

@app.get("/video/{job_id}")
async def get_video(job_id: str, download: bool = False):
    """Serve the simulation video for a completed job."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job = JOBS[job_id]

    # Check if job is complete and has a video
    if job["status"] != "done":
        raise HTTPException(status_code=400, detail="Job not yet complete")

    video_filename = f"{job_id}_sim.mp4"
    video_path = UPLOAD_DIR / job_id / video_filename

    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found")

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
    """Serve the image with background removed."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job_dir = UPLOAD_DIR / job_id
    # Find the nobackground PNG file
    nobackground_files = list(job_dir.glob(f"{job_id}_nobackground_*.png"))

    if not nobackground_files:
        raise HTTPException(status_code=404, detail="No-background image not yet available")

    headers = {}
    if download:
        headers["Content-Disposition"] = f"attachment; filename={job_id}_nobackground.png"

    return FileResponse(
        path=str(nobackground_files[0]),
        media_type="image/png",
        filename=f"{job_id}_nobackground.png",
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

def _run_pipeline(job_id: str, path: str) -> None:
    JOBS[job_id]["status"] = "processing"
    JOBS[job_id]["status_detail"] = "Starting pipeline..."
    try:
        out_path = process_image(job_id, path, JOBS)
        JOBS[job_id]["status"] = "done"
        JOBS[job_id]["status_detail"] = "Complete! Simulation video generated."
        JOBS[job_id]["processed_path"] = out_path

        # Store video path in job directory
        video_path = UPLOAD_DIR / job_id / f"{job_id}_sim.mp4"
        if video_path.exists():
            JOBS[job_id]["video_path"] = str(video_path)
            JOBS[job_id]["video_filename"] = f"{job_id}_sim.mp4"
    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["status_detail"] = f"Error: {str(e)}"
        JOBS[job_id]["error"] = repr(e)
        print(f"[ERROR] Job {job_id} failed: {e}")
