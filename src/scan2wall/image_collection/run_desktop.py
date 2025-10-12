from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

VIDEO_DIR = Path("recordings")

app = FastAPI()
VIDEO_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(VIDEO_DIR)), name="static")


def get_latest_video():
    """Return the Path of the video file with the highest numeric name."""
    videos = sorted(
        VIDEO_DIR.glob("*.mp4"),
        key=lambda p: int(p.stem) if p.stem.isdigit() else -1,
        reverse=True,
    )
    return videos[0] if videos else None


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse("""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Simulation Viewer</title>
  <style>
    html,body { height: 100%; margin: 0; font-family: system-ui, sans-serif; background:#0b0b0b; color:#eaeaea; }
    .wrap { min-height:100%; display:flex; align-items:center; justify-content:center; padding: 2rem; text-align:center; }
    .msg { font-size: 1.25rem; opacity:.85; }
    video { max-width: 100vw; max-height: 100vh; outline:none; }
    .hint { opacity:.6; font-size:.9rem; margin-top:.75rem; }
  </style>
</head>
<body>
  <div class="wrap">
    <div id="content">
      <div class="msg">No simulation generated yet :(</div>
      <div class="hint">Will pop up here as soon as we're done…</div>
    </div>
  </div>
  <script>
    const content = document.getElementById('content');
    let showingVideo = false;
    let lastVideo = null;

    async function check() {
      try {
        const res = await fetch('/api/status', { cache: 'no-store' });
        const data = await res.json();

        if (data.exists) {
          if (data.filename !== lastVideo) {
            lastVideo = data.filename;
            const cacheBust = `${data.modified}-${data.size}-${Date.now()}`;
            const src = `/static/${data.filename}?v=${cacheBust}`;
            showingVideo = true;
            content.innerHTML = `
              <video id="player" src="${src}" autoplay muted loop playsinline controls></video>
              <div class="hint">Loaded at ${new Date().toLocaleTimeString()}</div>
            `;
          }
        } else {
          showingVideo = false;
          lastVideo = null;
          content.innerHTML = `
            <div class="msg">No simulation generated yet :(</div>
            <div class="hint">Will pop up here as soon as we're done…</div>
          `;
        }
      } catch (e) {
        console.error(e);
      } finally {
        setTimeout(check, 5000);
      }
    }

    check();
  </script>
</body>
</html>
""")


@app.get("/api/status", response_class=JSONResponse)
def status():
    latest = get_latest_video()
    if latest and latest.exists():
        st = latest.stat()
        return {
            "exists": True,
            "filename": latest.name,
            "modified": int(st.st_mtime),
            "size": int(st.st_size),
        }
    return {"exists": False, "filename": None, "modified": None, "size": 0}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False, access_log=False)
