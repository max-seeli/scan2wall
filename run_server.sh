#!/bin/bash
conda activate comfyui
cd 3d_gen/ComfyUI/
python main.py &

cd ../
python server.py 