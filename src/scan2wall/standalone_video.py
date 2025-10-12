from pathlib import Path
import cv2
import numpy as np
import requests
import re
import subprocess
import os

def make_throwing_anim(file, scaling=1.0):
    print("Creating throwing anim")
    cmd = (
        f"python /workspace/scan2wall/isaac_scripts/test_place_obj_video.py "
        f"--video --usd_path_abs '{file}' --scaling_factor {scaling} --kit_args='--no-window'"
    )
    subprocess.Popen(
        ["/bin/bash", "-lic", cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # fully detached from parent
    )
    print("DONE! :)")


if __name__ == "__main__":
    object = "pen"
    with open(
        "/workspace/scan2wall/assets.csv", "r"
    ) as f:
        for line in f:
            if object in line:
                obj_path = line.strip().split(",")[-1]
                make_throwing_anim(obj_path, scaling=float(line.strip().split(",")[1]))
                break