import time
import uuid
from pathlib import Path
from typing import Dict, Any, List

from fastapi import FastAPI, File, UploadFile, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ml_pipeline import process_image

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
PROCESSED_DIR = Path(__file__).resolve().parent.parent / "processed"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Scan2Mesh")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

JOBS: Dict[str, Dict[str, Any]] = {}


@app.get("/", response_class=HTMLResponse)
async def upload_page(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})


@app.post("/upload")
async def upload_image(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    print("[INFO] Received file.")
    ts = time.strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:6]
    original = Path(file.filename).name if file.filename else "photo.jpg"
    safe_name = "".join(ch for ch in original if ch.isalnum() or ch in ("-", "_", ".", " ")).strip() or "photo.jpg"
    fname = f"{ts}-{suffix}-{safe_name}"
    dest = UPLOAD_DIR / fname

    with dest.open("wb") as f:
        while True:
            chunk = await file.read(2**20)
            if not chunk:
                break
            f.write(chunk)

    job_id = uuid.uuid4().hex
    JOBS[job_id] = {
        "id": job_id,
        "filename": fname,
        "path": str(dest),
        "status": "queued",
        "created_at": time.time(),
        "processed_path": None,
        "error": None,
    }

    background_tasks.add_task(_run_pipeline, job_id, str(dest))
    return JSONResponse(
        {
            "message": "File uploaded successfully",
            "job_id": job_id,
            "filename": fname,
            "status": "queued"
        },
        status_code=201
    )


def _run_pipeline(job_id: str, path: str) -> None:
    JOBS[job_id]["status"] = "processing"
    try:
        out_path = process_image(job_id, path)
        JOBS[job_id]["status"] = "done"
        JOBS[job_id]["processed_path"] = out_path
    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = repr(e)
