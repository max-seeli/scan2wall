from pathlib import Path
import cv2
import numpy as np
from scan2wall.material_properties.get_object_properties import get_object_properties
import requests
import re
import subprocess
import os


def process_image(job_id: str, image_path: str) -> str:
    """
    Args:
        image_path: path to uploaded image
    Returns:
        Path to a processed artifact (e.g., a thumbnail or JSON result)
    """
    p = Path(image_path)
    out_dir = p.parent.parent / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    # generate glb mesh file
    # 1. make a post request to
    url = "https://8012-hah9c53y9.brevlab.com/process"
    with open(p, "rb") as f:
        resp = requests.post(
            url,
            files={"file": (p.name, f, "application/octet-stream")},
            data={"timeout": "300", "job_id": job_id},
            timeout=(10, 600),
        )
    print("!")
    resp.raise_for_status()
    out_file = out_dir / f"{job_id}.glb"
    # out_file = "/workspace/scan2wall/src/scan2wall/image_collection/processed/4b3df0f54ab641a7826b609fea240902.glb"
    print(out_file)
    out_file.write_bytes(resp.content)

    props = get_object_properties(image_path)
    # print(props)
    mass = props["weight_kg"]["value"]
    df = props["friction_coefficients"]["dynamic"]
    ds = props["friction_coefficients"]["static"]
    usd_file = convert_mesh(out_file, f"{job_id}.glb", mass=mass, df=df, ds=ds)
    # out_file = "/workspace/scan2wall/src/scan2wall/image_collection/processed/4b3df0f54ab641a7826b609fea240902.glb"
    # usd_file = convert_mesh(out_file, f"{job_id}.glb", mass=None, df=None, ds=None)
    # usd_file = "/workspace/isaaclab/4b3df0f54ab641a7826b609fea240902.usd"
    make_throwing_anim(usd_file)
    return str(out_file)

def convert_mesh(out_file, fname, mass=None, df=None, ds=None):
    fname_new = fname.replace(".glb", ".usd")
    print(fname_new)
    m = f"--mass {mass}" if mass else ""
    ds = f"--static-friction {ds}" if ds else ""
    df = f"--dynamic-friction {df}" if df else ""
    
    #os.system(f"/bin/bash -lic 'python /workspace/isaaclab/scripts/tools/convert_mesh.py {out_file} /workspace/isaaclab/{fname_new} --kit_args='--headless' {m} {df} {ds}'")

    cmd = (
        f"python /workspace/isaaclab/scripts/tools/convert_mesh.py "
        f"{out_file} /workspace/isaaclab/{fname_new} "
        f"--kit_args='--headless' {m} {df} {ds}"
    )

    # Spawn in a new process group (detached), but keep a handle to wait later
    proc = subprocess.Popen(
        ["/bin/bash", "-lic", cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # detaches from parent session
        text=True
    )

    for line in proc.stdout:
        print(line, end="")  # stream live output

    proc.wait()

    print("conversion done :)")
    return f"/workspace/isaaclab/{fname_new}"
    #    --collision-approximation convexHull   --mass 0.35   --com 0 0 0   --inertia 0.00195 0.00195 0.000246   --principal-axes 1 0 0 0   --static-friction 0.6   --dynamic-friction 0.5   --restitution 0.2   --friction-combine average   --restitution-combine min")

def make_throwing_anim(file):
    print("Q")
    # os.system(f"/bin/bash -lic 'python /workspace/isaaclab/scripts/test_place_obj_video.py --video --usd_path_abs \"{file}\"  --kit_args='--no-window''")
    st = f"/workspace/isaaclab/isaaclab.sh -p /workspace/isaaclab/scripts/test_place_obj_video.py --video --usd_path_abs '{file}' --kit_args='--no-window'"
    print(st)
    #result = os.system(st)
    #cmd = [
    #    "/bin/bash",
    #    "-lc",
    #    f"/workspace/isaaclab/isaaclab.sh -p /workspace/isaaclab/scripts/test_place_obj_video.py --video --usd_path_abs '{file}' --kit_args='--no-window'"
    #]

    #result = subprocess.run(cmd, text=True)
    cmd = (
        f"python /workspace/isaaclab/scripts/test_place_obj_video.py "
        f"--video --usd_path_abs '{file}' --kit_args='--no-window'"
    )
    subprocess.Popen(
        ["/bin/bash", "-lic", cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True  # fully detached from parent
    )
    print("DONE! :)")

# url = "https://8188-hah9c53y9.brevlab.com/upload/image" # todo: remove hardcoding

# with open(p, "rb") as f:
#     files = {"file": f}  # or use the correct key your endpoint expects
#     response = requests.post(url, files=files)
# print(response.status_code)
# # Infer object properties
# properties = get_object_properties(str(p))
# out = out_dir / f"{p.stem}_properties.json"
# out.write_text(str(properties))

# process
# img = cv2.imread(str(p), cv2.IMREAD_COLOR)
# if img is None:
#     fail = out_dir / f"{p.stem}_FAILED.txt"
#     fail.write_text("Could not read uploaded image.")
#     return str(fail)

# # Example processing: resize to thumbnail and save
# h, w = img.shape[:2]
# scale = 256 / max(h, w)
# new_size = (int(w * scale), int(h * scale))
# thumb = cv2.resize(img, new_size, interpolation=cv2.INTER_AREA)
# out = out_dir / f"{p.stem}_thumb.jpg"
# cv2.imwrite(str(out), thumb)

# return str(out)

if __name__ == "__main__":
    # dir = "/workspace/scan2wall/src/scan2wall/image_collection/processed/"
    # fname = "job_83e55f3895054f8cbd92cb979029a82e.glb"
    # convert_mesh(dir + fname, fname)
    process_image("4b3df0f54ab641a7826b609fea240902", "uploads/20251011-222124-4562cb-IMG_0451.png")
    # make_throwing_anim("/workspace/isaaclab/ab015dc2cdcd4a44a647952fc9a854bb.usd")
