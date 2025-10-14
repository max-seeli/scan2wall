"""scan2wall - AI pipeline for 2D photos to 3D physics simulations.

This package provides the core utilities and configuration for the scan2wall
project, which converts phone photos into 3D physics simulations using:
- Hunyuan 3D 2.1 for mesh generation
- Google Gemini 2.0 Flash for material inference
- NVIDIA Isaac Sim for physics simulation
"""

__version__ = "0.1.0"

# Import path utilities for convenient access
from scan2wall.utils.paths import (
    get_project_root,
    get_isaac_workspace,
    get_isaac_scripts_dir,
    get_assets_csv,
    get_recordings_dir,
    get_usd_output_dir,
)

# Export commonly used paths
PROJECT_ROOT = get_project_root()
ISAAC_WORKSPACE = get_isaac_workspace()


def main():
    """Main entry point for scan2wall CLI."""
    print(f"scan2wall v{__version__}")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Isaac workspace: {ISAAC_WORKSPACE}")
    print("")
    print("For more options, run: python -m scan2wall --check")


__all__ = [
    "__version__",
    "PROJECT_ROOT",
    "ISAAC_WORKSPACE",
    "main",
    "get_project_root",
    "get_isaac_workspace",
    "get_isaac_scripts_dir",
    "get_assets_csv",
    "get_recordings_dir",
    "get_usd_output_dir",
]
