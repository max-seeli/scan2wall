"""
Path configuration utilities for scan2wall.

Provides centralized path management with environment variable configuration
and intelligent defaults. Supports flexible deployment on single or multiple instances.
"""

import os
from pathlib import Path
from typing import Optional


def _get_project_root() -> Path:
    """
    Auto-detect project root from this file's location.

    Returns:
        Path to project root directory (where pyproject.toml lives)
    """
    # This file is at: PROJECT_ROOT/scan2wall/utils/paths.py
    # So go up 3 levels to get to PROJECT_ROOT
    current_file = Path(__file__).resolve()
    return current_file.parent.parent.parent


def get_project_root() -> Path:
    """
    Get project root directory.

    Uses PROJECT_ROOT env var if set, otherwise auto-detects.

    Returns:
        Path to project root
    """
    env_root = os.getenv("PROJECT_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return _get_project_root()


def get_isaac_workspace() -> Path:
    """
    Get Isaac Lab workspace directory (where USD files are saved).

    Uses ISAAC_WORKSPACE env var if set, otherwise defaults to PROJECT_ROOT/isaac/IsaacLab

    Returns:
        Path to Isaac workspace
    """
    env_workspace = os.getenv("ISAAC_WORKSPACE")
    if env_workspace:
        return Path(env_workspace).resolve()
    # Default: isaac/IsaacLab within project
    return get_project_root() / "isaac" / "IsaacLab"


def get_isaac_scripts_dir() -> Path:
    """
    Get Isaac scripts directory.

    Uses ISAAC_SCRIPTS_DIR env var if set, otherwise uses PROJECT_ROOT/isaac_scripts

    Returns:
        Path to isaac_scripts directory
    """
    env_scripts = os.getenv("ISAAC_SCRIPTS_DIR")
    if env_scripts:
        return Path(env_scripts).resolve()
    return get_project_root() / "isaac_scripts"


def get_assets_csv() -> Path:
    """
    Get assets.csv file path.

    Uses ASSETS_CSV env var if set, otherwise uses PROJECT_ROOT/assets.csv

    Returns:
        Path to assets.csv
    """
    env_csv = os.getenv("ASSETS_CSV")
    if env_csv:
        return Path(env_csv).resolve()
    return get_project_root() / "assets.csv"


def get_recordings_dir() -> Path:
    """
    Get recordings output directory.

    Uses RECORDINGS_DIR env var if set, otherwise uses PROJECT_ROOT/data/recordings

    Returns:
        Path to recordings directory
    """
    env_recordings = os.getenv("RECORDINGS_DIR")
    if env_recordings:
        return Path(env_recordings).resolve()
    return get_project_root() / "data" / "recordings"


def get_usd_output_dir() -> Path:
    """
    Get USD output directory (where converted meshes are saved).

    Uses USD_OUTPUT_DIR env var if set, otherwise uses ISAAC_WORKSPACE

    Returns:
        Path to USD output directory
    """
    return Path("/home/ubuntu/workspace/scan2wall/data/usd_files")


def validate_paths(check_writable: bool = False) -> dict:
    """
    Validate all configured paths.

    Args:
        check_writable: If True, also check if directories are writable

    Returns:
        Dict with path names as keys and (exists, writable) tuples as values
    """
    results = {}

    paths_to_check = {
        "project_root": get_project_root(),
        "isaac_workspace": get_isaac_workspace(),
        "isaac_scripts_dir": get_isaac_scripts_dir(),
        "recordings_dir": get_recordings_dir(),
        "usd_output_dir": get_usd_output_dir(),
    }

    # Files to check (existence only)
    files_to_check = {
        "assets_csv": get_assets_csv(),
    }

    for name, path in paths_to_check.items():
        exists = path.exists() and path.is_dir()
        writable = False
        if check_writable and exists:
            try:
                # Try to create a temp file
                test_file = path / ".write_test"
                test_file.touch()
                test_file.unlink()
                writable = True
            except (OSError, PermissionError):
                writable = False
        results[name] = {"path": str(path), "exists": exists, "writable": writable}

    for name, path in files_to_check.items():
        exists = path.exists() and path.is_file()
        results[name] = {"path": str(path), "exists": exists, "writable": None}

    return results


def print_path_configuration():
    """Print current path configuration for debugging."""
    print("=" * 80)
    print("scan2wall Path Configuration")
    print("=" * 80)
    print(f"Project Root:       {get_project_root()}")
    print(f"Isaac Workspace:    {get_isaac_workspace()}")
    print(f"Isaac Scripts Dir:  {get_isaac_scripts_dir()}")
    print(f"Assets CSV:         {get_assets_csv()}")
    print(f"Recordings Dir:     {get_recordings_dir()}")
    print(f"USD Output Dir:     {get_usd_output_dir()}")
    print("=" * 80)
    print("\nPath Validation:")

    validation = validate_paths(check_writable=True)
    for name, info in validation.items():
        status = "✓" if info["exists"] else "✗"
        writable_status = ""
        if info["writable"] is not None:
            writable_status = " (writable)" if info["writable"] else " (read-only)"
        print(f"  {status} {name}: {info['path']}{writable_status}")
    print("=" * 80)


if __name__ == "__main__":
    # When run directly, print configuration
    print_path_configuration()
