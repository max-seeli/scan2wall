"""
Standalone script to trigger Isaac Sim throwing animation for existing USD assets.

Usage:
    python standalone_video.py

Searches assets.csv for a specific object and triggers the simulation.
"""

from pathlib import Path
import subprocess
import sys
# Add current directory to path to import from 3d_gen
sys.path.insert(0, str(Path(__file__).parent))
from utils.paths import get_isaac_scripts_dir, get_assets_csv


def make_throwing_anim(file: str, scaling: float = 1.0):
    """
    Trigger Isaac Sim throwing animation simulation.

    Args:
        file: Path to USD file
        scaling: Scaling factor for the object
    """
    print(f"Creating throwing animation for: {file}")

    isaac_scripts = get_isaac_scripts_dir()
    sim_script = isaac_scripts / "test_place_obj_video.py"

    cmd = (
        f"python {sim_script} "
        f"--video --usd_path_abs '{file}' --scaling_factor {scaling} --kit_args='--no-window'"
    )

    subprocess.Popen(
        ["/bin/bash", "-lic", cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    print("Simulation triggered!")


if __name__ == "__main__":
    # Example: Search for a specific object in assets.csv and simulate it
    target_object = "pen"  # Change this to the object you want to simulate

    assets_csv = get_assets_csv()

    if not assets_csv.exists():
        print(f"Error: assets.csv not found at {assets_csv}")
        print("Run the main pipeline first to generate some assets.")
        exit(1)

    found = False
    with open(assets_csv, "r") as f:
        # Skip header
        next(f, None)

        for line in f:
            if target_object in line:
                parts = line.strip().split(",")
                if len(parts) >= 4:
                    obj_type, scaling, mass, obj_path = parts[0], parts[1], parts[2], parts[3]
                    print(f"Found {obj_type}: {obj_path}")
                    make_throwing_anim(obj_path, scaling=float(scaling))
                    found = True
                    break

    if not found:
        print(f"Object '{target_object}' not found in assets.csv")
        print("Available objects:")
        with open(assets_csv, "r") as f:
            next(f, None)  # Skip header
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 1:
                    print(f"  - {parts[0]}")
