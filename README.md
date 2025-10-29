# scan2wall

**Scan objects and simulate throwing them at a wall using AI and physics.**

![Demo](docs/black_bottle.webp)
![Demo](docs/loop.gif)
![Demo](docs/ComfyUI.png)

## How It Works

1. 📱 Take a photo of any object on your phone
2. ⬆️ Upload via web interface
3. 🤖 AI generates 3D mesh, texture and infers material properties
4. 🎮 Object gets thrown at a brick wall in Isaac Sim
5. 🎬 You can watch the simulation video

**Total time: ~1 minute! (on a L40S GPU)**

## Tech Stack

- **3D Generation**: [Hunyuan 3D 2.1](https://github.com/Tencent/Hunyuan3D-2) via [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
- **Material Analysis**: Google Gemini 2.5 Flash
- **Physics Simulation**: NVIDIA Isaac Sim
- **Backend**: FastAPI, Python 3.11
- **Frontend**: HTML5 + JavaScript

## Quick Start

### Prerequisites

- **Linux** with NVIDIA GPU (with drivers installed)
- **70GB+ free disk space** for models and Isaac Lab
- **24GB+ of VRAM** for ComfyUI with MeshCraft

**Note**: Docker and nvidia-container-toolkit will be automatically installed during setup if not present.

### Installation

**Install**
```bash
git clone https://github.com/max-seeli/scan2wall.git
cd scan2wall
./scripts/setup.sh
```
The setup script will automatically:
- Install Docker (if not already installed)
- Install NVIDIA Container Toolkit (if not already installed)
- Download and configure Isaac Lab (~10-15GB Docker images)
- Set up ComfyUI with required custom nodes
- Download AI models (~8GB)

**API Key Setup:**
You will be prompted for a Gemini API key during setup. You can also skip it and add it later by editing `.env`:
```bash
GOOGLE_API_KEY=your_key_here  # Get from https://makersuite.google.com/app/apikey
```

### Running

```bash
./scripts/start.sh
```
This opens tmux windows automatically. Use `Ctrl+B` then number keys to switch between them.
ComfyUI will be on port 8188, upload server on port 49100.

Once started, visit the URL to upload photos!

## Documentation

- ARCHITECTURE.md

## Project Structure

PUT FOLDER STRUCTURE HERE.

## Future Ideas

- Trebuchet minigame
- Sliding down a plane minigame
- Segmentation of 3D reconstruction for more realistic physics

## Built For

**NVIDIA Simulation Hack** (October 10-12, 2025)

This project showcases the integration of multiple cutting-edge AI and physics systems:
- Tencent's Hunyuan 3D 2.1 for image-to-3D generation
- Google's Gemini 2.5 Flash for intelligent material property inference
- NVIDIA's Isaac Sim for high-fidelity physics simulation

## Made by:

Andrea Pozzetti
Max Seeliger
Patrick Styll
Valentin Vogt

## License

MIT License - see [LICENSE](LICENSE) file for details

## Acknowledgments

Thank you to Jua, Flexion Robotics and NVIDIA for the Hackathon!

## Contact

Issues: [GitHub Issues](https://github.com/max-seeli/scan2wall/issues)