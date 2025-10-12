# scan2wall
Scan objects and do collision simulation (throw it at a wall).

# Run the public-facing Isaac-side server:

Install uv.
```
uv sync
uv pip install -e .
```
and then 
`uv run src/scan2wall/image_collection/run.py`.

# Comfy-side work server
#!/bin/bash
source activate base
conda activate comfyui
cd 3d_gen/ComfyUI/
python main.py &

cd ../
python server.py
