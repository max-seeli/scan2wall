#!/bin/bash
source activate base
conda activate comfyui
cd 3d_gen/ComfyUI/
python main.py &

cd ../
python server.py 