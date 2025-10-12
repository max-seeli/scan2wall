"""FastAPI server for running ComfyUI prompts based on uploaded images."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib import request
import shutil
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI(title="ComfyUI Runner")

PROMPT_URL = "http://127.0.0.1:8188/prompt"
COMFY_OUTPUT_DIR = Path("~/scan2wall/3d_gen/ComfyUI/output").expanduser()
COMFY_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = Path("/tmp/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PROMPT_FILE = Path("~/scan2wall/3d_gen/workflows/api_prompt_fast.json").expanduser()
LOAD_IMAGE_NODE_ID = "112"
SAVE_MODEL_NODE_ID = "89"

def queue_prompt(prompt: dict, prompt_url: str = PROMPT_URL) -> None:
    """Queue the provided prompt for ComfyUI processing."""
    payload = json.dumps({"prompt": prompt}).encode("utf-8")
    req = request.Request(prompt_url, data=payload)
    req.add_header("Content-Type", "application/json")
    request.urlopen(req)


def wait_for_file(path: Path, timeout: float = 300.0, stable_time: float = 1.0) -> None:
    """Block until *path* exists and stops growing in size."""
    deadline = time.time() + timeout
    last_size: Optional[int] = None
    while time.time() < deadline:
        if path.exists() and path.stat().st_size > 0:
            current_size = path.stat().st_size
            if last_size == current_size:
                return
            last_size = current_size
            time.sleep(stable_time)
            continue
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for output file: {path}")


@app.post("/process")
async def process_image(
    file: UploadFile = File(...),
    timeout: float = Form(300.0),
    job_id: str = Form(None),
) -> FileResponse:
    """Upload an image, queue the prompt, and return the generated output."""
    print(f"Received file: {file.filename}, timeout: {timeout}, job_id: {job_id}")
    try:
        prompt = json.loads(PROMPT_FILE.read_text())
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid prompt JSON: {exc}") from exc

    if LOAD_IMAGE_NODE_ID not in prompt or "inputs" not in prompt[LOAD_IMAGE_NODE_ID]:
        raise HTTPException(
            status_code=400,
            detail=f"Prompt must contain node '{LOAD_IMAGE_NODE_ID}' with an 'inputs' field.",
        )

    try:
        saved_path = save_upload(file)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {exc}") from exc

    comfy_input = Path(os.environ.get("COMFY_INPUT_DIR", "~/scan2wall/3d_gen/input")).expanduser()
    comfy_input.mkdir(parents=True, exist_ok=True)
    img_name = Path(saved_path).name
    shutil.copy2(saved_path, comfy_input / img_name)
    prompt[LOAD_IMAGE_NODE_ID]["inputs"]["image"] = str(comfy_input / img_name)
    unique_prefix = job_id or f"job_{uuid.uuid4().hex}"
    prompt["89"]["inputs"]["string"] = unique_prefix
    queue_prompt(prompt)
    # unique_prefix = "747dfbc5c0434263ab0af03ba185cc31"
    # # unique_prefix = "job_2fea13a4fc344f2cbe70e427c9c4c8f2"
    pattern = COMFY_OUTPUT_DIR / f"{unique_prefix}*.glb"
    deadline = time.time() + float(timeout)
    found = None
    while time.time() < deadline:
        matches = sorted(pattern.parent.glob(pattern.name))
        if matches:
            found = max(matches, key=lambda p: p.stat().st_mtime)
            if found.stat().st_size > 0:
                break
        time.sleep(0.5)
    
    if not found:
        raise HTTPException(status_code=504, detail="Timed out waiting for ComfyUI output")
    found = COMFY_OUTPUT_DIR / f"{unique_prefix}.glb"
    print(found)
    return FileResponse(path=str(found), media_type="model/gltf-binary", filename=f"{unique_prefix}.glb")

@app.get("/health")
def health() -> JSONResponse:
    """Simple health endpoint."""
    return JSONResponse({"status": "ok"})


def save_upload(file: UploadFile) -> Path:
    suffix = Path(file.filename or "upload").suffix
    target_path = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    with target_path.open("wb") as buffer:
        while chunk := file.file.read(1024 * 1024):
            buffer.write(chunk)
    return target_path


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8012, reload=False)