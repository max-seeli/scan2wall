import time
import uuid
from pathlib import Path
from typing import Dict, Any, List
import imghdr
from fastapi import FastAPI, File, UploadFile, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi import HTTPException
from PIL import Image
import io
import imghdr
from fastapi import HTTPException
from ml_pipeline import process_image

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "JOBS"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Scan2Mesh")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

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
    return JSONResponse({
        "job_id": job["id"],
        "status": job["status"],
        "status_detail": job.get("status_detail", "Processing..."),
        "filename": job["filename"],
        "created_at": job["created_at"],
        "processed_path": job.get("processed_path"),
        "video_filename": job.get("video_filename"),
        "error": job.get("error"),
    })

@app.get("/jobs")
async def list_jobs():
    """List all jobs (for debugging/admin)."""
    return JSONResponse({"jobs": list(JOBS.values())})

@app.get("/video/{job_id}")
async def get_video(job_id: str):
    """Serve the simulation video for a completed job."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job = JOBS[job_id]

    # Check if job is complete and has a video
    if job["status"] != "done":
        raise HTTPException(status_code=400, detail="Job not yet complete")

    video_filename = f"{job_id}_sim.mp4"
    video_path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "recordings" / video_filename

    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found")

    return FileResponse(
        path=str(video_path),
        media_type="video/mp4",
        filename=video_filename
    )

def _run_pipeline(job_id: str, path: str) -> None:
    JOBS[job_id]["status"] = "processing"
    JOBS[job_id]["status_detail"] = "Starting pipeline..."
    try:
        out_path = process_image(job_id, path, JOBS)
        JOBS[job_id]["status"] = "done"
        JOBS[job_id]["status_detail"] = "Complete! Simulation video generated."
        JOBS[job_id]["processed_path"] = out_path

        # Store video path (convert container path to host path if needed)
        video_path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "recordings" / f"{job_id}_sim.mp4"
        if video_path.exists():
            JOBS[job_id]["video_path"] = str(video_path)
            JOBS[job_id]["video_filename"] = f"{job_id}_sim.mp4"
    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["status_detail"] = f"Error: {str(e)}"
        JOBS[job_id]["error"] = repr(e)
        print(f"[ERROR] Job {job_id} failed: {e}")
