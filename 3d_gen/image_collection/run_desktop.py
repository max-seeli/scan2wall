from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

VIDEO_DIR = Path("recordings")
VIDEO_NAME = "sim_run.mp4"
VIDEO_PATH = VIDEO_DIR / VIDEO_NAME

app = FastAPI()
VIDEO_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(VIDEO_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Simulation Viewer</title>
  <style>
    html,body {{ height: 100%; margin: 0; font-family: system-ui, sans-serif; background:#0b0b0b; color:#eaeaea; }}
    .wrap {{ min-height:100%; display:flex; align-items:center; justify-content:center; padding: 2rem; text-align:center; }}
    .msg {{ font-size: 1.25rem; opacity:.85; }}
    video {{ max-width: 100vw; max-height: 100vh; outline:none; }}
    .hint {{ opacity:.6; font-size:.9rem; margin-top:.75rem; }}
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

    let lastModified = null;
    let lastSize = null;
    let pendingCandidate = null; // {{ modified, size }}

    async function check() {{
      try {{
        const res = await fetch('/api/status', {{ cache: 'no-store' }});
        const data = await res.json();

        if (data.exists) {{
          const changed = (data.modified !== lastModified) || (data.size !== lastSize);

          if (pendingCandidate === null && changed) {{
            pendingCandidate = {{ modified: data.modified, size: data.size }};
          }} else if (pendingCandidate !== null) {{
            const stable = (data.modified === pendingCandidate.modified) && (data.size === pendingCandidate.size);
            if (stable) {{
              lastModified = data.modified;
              lastSize = data.size;
              pendingCandidate = null;

              const cacheBust = `${{data.modified}}-${{data.size}}-${{Date.now()}}`;
              const src = `/static/{VIDEO_NAME}?v=${{cacheBust}}`;

              showingVideo = true;
              content.innerHTML = `
                <video id="player" src="${{src}}" autoplay muted loop playsinline controls></video>
                <div class="hint">Reloaded at ${{new Date().toLocaleTimeString()}}</div>
              `;
            }} else {{
              pendingCandidate = {{ modified: data.modified, size: data.size }};
            }}
          }}

          if (!showingVideo && pendingCandidate === null && !changed) {{
            lastModified = data.modified;
            lastSize = data.size;
            const cacheBust = `${{data.modified}}-${{data.size}}-${{Date.now()}}`;
            const src = `/static/{VIDEO_NAME}?v=${{cacheBust}}`;
            showingVideo = true;
            content.innerHTML = `
              <video id="player" src="${{src}}" autoplay muted loop playsinline controls></video>
              <div class="hint">Loaded at ${{new Date().toLocaleTimeString()}}</div>
            `;
          }}
        }} else {{
          showingVideo = false;
          lastModified = null;
          lastSize = null;
          pendingCandidate = null;
          content.innerHTML = `
            <div class="msg">No simulation generated yet :(</div>
            <div class="hint">Will pop up here as soon as we're done…</div>
          `;
        }}
      }} catch (e) {{
        console.error(e);
      }} finally {{
        setTimeout(check, 5000);
      }}
    }}

    check();
  </script>
</body>
</html>
""")


@app.get("/api/status", response_class=JSONResponse)
def status():
    if VIDEO_PATH.exists():
        st = VIDEO_PATH.stat()
        return {
            "exists": True,
            "modified": int(st.st_mtime),
            "size": int(st.st_size),
        }
    return {"exists": False, "modified": None, "size": 0}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False, access_log=True)
