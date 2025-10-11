# scan2wall
Scan objects and do collision simulation (throw it at a wall).

In the following order:

1 - `conda create -n comfyui python=3.10 -y` 
OR run minic.sh
2 - CLOSE YOUR TERMINAL
3 - Open terminal, run "conda activate comfyui"
4 - Bash run comfy.sh
5 - Bash run modeldownload.sh

THEN:
start comfyui by running:

```
cd ComfyUI
python main.py --listen 0.0.0.0 --port 8188
```
make sure port 8188 is exposed

Load workflows/image_to_3D_fast.json into comfyui