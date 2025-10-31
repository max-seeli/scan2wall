#!/bin/bash
set -e

echo "🚀 Setting up ComfyUI environment (simplified)"

# --- Paths ---
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GEN_DIR="$ROOT_DIR/3d_gen"
COMFY_DIR="$GEN_DIR/ComfyUI"

mkdir -p "$GEN_DIR"
cd "$GEN_DIR"

# --- Install uv ---
if ! command -v uv &> /dev/null; then
  echo "📦 Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.cargo/bin:$PATH"
fi

# --- Virtual env ---
echo "🐍 Creating Python 3.10 venv..."
[ -d ".venv" ] || uv venv --python 3.10
source .venv/bin/activate

# --- Clone ComfyUI ---
if [ ! -d "$COMFY_DIR" ]; then
  echo "📥 Cloning ComfyUI..."
  git clone https://github.com/comfyanonymous/ComfyUI
fi
cd "$COMFY_DIR"
uv pip install -r requirements.txt

# --- Manager + Custom Nodes ---
echo "📦 Installing ComfyUI Manager..."
mkdir -p custom_nodes
cd custom_nodes
[ -d "ComfyUI-Manager" ] || git clone https://github.com/Comfy-Org/ComfyUI-Manager
uv pip install -r ComfyUI-Manager/requirements.txt

# --- Custom Nodes ---
echo "📦 Installing Custom Nodes..."
NODES=(
  "Suzie1/ComfyUI_Comfyroll_CustomNodes"
  "kijai/ComfyUI-KJNodes"
  "chflame163/ComfyUI_LayerStyle"
  "huagetai/ComfyUI_LightGradient"
  "PozzettiAndrea/ComfyUI-MeshCraft"
  "PozzettiAndrea/ComfyUI-Grounding"
  "kijai/ComfyUI-segment-anything-2"
  "rgthree/rgthree-comfy"
  "PozzettiAndrea/ComfyUI-Inspyrenet-Rembg-withcaching"
  "yichengup/ComfyUI-YCNodes"
)

for n in "${NODES[@]}"; do
  repo=$(basename "$n")
  if [ ! -d "$repo" ]; then
    echo "📥 Cloning $repo..."
    git clone "https://github.com/$n"
    # checkout specific tag for MeshCraft
    if [ "$repo" = "ComfyUI-MeshCraft" ]; then
      (
        cd "$repo"
        git fetch --tags
        git checkout tags/0.0.1 -b v0.0.1
      )
      echo "📌 Pinned ComfyUI-MeshCraft to tag 0.0.1"
    fi
  else
    echo "⚠️  $repo already exists, skipping clone"
  fi
  # install dependencies if present
  [ -f "$repo/requirements.txt" ] && uv pip install -r "$repo/requirements.txt" || true
done

# --- GPU / System dependencies ---
echo "⚙️  Installing GPU + OpenCV dependencies..."
uv pip install "rembg[gpu]" opencv-contrib-python==4.10.0.84

# --- Core Python deps ---
echo "📦 Installing extra utilities..."
uv pip install transformers==4.46.3 pynanoinstantmeshes hf_transfer fastapi uvicorn python-multipart

# --- Optional CUDA extension (diso) ---
if command -v nvcc &> /dev/null; then
  echo "🧩 Installing diso (CUDA extension)..."
  uv pip install diso --no-build-isolation || echo "⚠️ diso build failed, skipping"
else
  echo "⚠️ CUDA not found (nvcc missing) — skipping diso build"
fi

# --- Blender (optional) ---
if ! command -v blender &> /dev/null; then
  echo "📥 Installing Blender (optional)..."
  sudo apt-get update -qq && sudo apt-get install -y blender || echo "⚠️ Blender install failed"
fi

echo ""
echo "✅ Setup complete!"
echo "=========================================================="
echo "Next steps:"
echo "1. Activate the environment:"
echo "   source $GEN_DIR/.venv/bin/activate"
echo ""
echo "2. Run ComfyUI:"
echo "   cd $COMFY_DIR && python main.py --listen 0.0.0.0 --port 8188"
echo ""
echo "3. (Optional) Run your API server:"
echo "   cd $GEN_DIR && python server.py"
echo ""