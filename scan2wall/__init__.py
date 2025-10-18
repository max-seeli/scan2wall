"""scan2wall - AI pipeline for 2D photos to 3D physics simulations.

This package provides the core utilities and configuration for the scan2wall
project, which converts phone photos into 3D physics simulations using:
- Hunyuan 3D 2.1 for mesh generation
- Google Gemini 2.0 Flash for material inference
- NVIDIA Isaac Sim for physics simulation
"""

__version__ = "0.1.0"


def main():
    """Main entry point for scan2wall CLI."""
    print(f"scan2wall v{__version__}")
    print("Scan objects and simulate throwing them at a wall using AI and physics.")
    print("")
    print("Quick start:")
    print("  ./start.sh auto")


__all__ = [
    "__version__",
    "main",
]
