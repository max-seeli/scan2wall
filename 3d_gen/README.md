# ComfyUI Setup for scan2wall

3D mesh generation using ComfyUI with Hunyuan 3D 2.1 model.

## Quick Setup (uv - No conda needed!)

```bash
# 1. Run unified setup script
bash setup_comfyui.sh

# 2. Download models (~8GB)
bash modeldownload.sh

# 3. Start ComfyUI
source .venv/bin/activate
cd ComfyUI
python main.py --listen 0.0.0.0 --port 8188
```

Make sure port 8188 is exposed.

## Usage

1. Open `http://localhost:8188` in your browser
2. Load the workflow: `workflows/image_to_3D_fast.json`
3. Upload an image and generate!

## Running the API Server

In a separate terminal:

```bash
cd 3d_gen
source .venv/bin/activate
python server.py
```

This runs on port 8012 and provides HTTP API for the main scan2wall application.

## What's Included

- **ComfyUI**: Node-based workflow system
- **Hunyuan 3D 2.1**: State-of-the-art image-to-3D model by Tencent
- **Custom Nodes**:
  - ComfyUI-Manager
  - ComfyUI-Hunyuan3d-2-1
  - ComfyUI-Inspyrenet-Rembg
  - ComfyUI_Comfyroll_CustomNodes
  - ComfyUI-KJNodes
  - ComfyUI_LayerStyle (Photoshop-like layer effects)
  - ComfyUI_LightGradient (gradient generation)
  - andrea-nodes (custom)

## Benefits of uv Setup

- ✅ **10-100x faster** than pip/conda
- ✅ **No conda needed** - just uv
- ✅ **Single script** - replaces 3 separate bash scripts
- ✅ **Consistent** - same tool as main project

## Troubleshooting

**Port 8188 already in use?**
```bash
lsof -ti:8188 | xargs kill -9
```

**Models not found?**
Re-run `bash modeldownload.sh`

**CUDA errors?**
Check NVIDIA driver and CUDA toolkit installation.

**Setup failed?**
- Ensure CUDA toolkit is installed
- Check you have enough disk space (~50GB)
- Verify internet connection for downloads
