# scan2wall

**Scan objects and simulate throwing them at a wall using AI and physics.**

![Demo](docs/black_bottle.webp)
![Demo](docs/loop.gif)
![Demo](docs/ComfyUI.png)

A hackathon project for NVIDIA's Simulation Hack that combines phone camera capture, AI-powered 3D mesh generation, material property inference, and realistic physics simulation.

## How It Works

1. 📱 Take a photo of any object on your phone
2. ⬆️ Upload via web interface (QR code provided)
3. 🤖 AI generates 3D mesh and infers material properties
4. 🎮 Object gets thrown at a pyramid in Isaac Sim
5. 🎬 Watch the simulation video

**Total time: ~1 minute!**

## Tech Stack

- **3D Generation**: [Hunyuan 3D 2.1](https://github.com/Tencent/Hunyuan3D-2) via [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
- **Material Analysis**: Google Gemini 2.0 Flash
- **Physics Simulation**: NVIDIA Isaac Sim
- **Backend**: FastAPI, Python 3.11
- **Frontend**: HTML5 + JavaScript

## Quick Start

### Prerequisites

- **Linux** with NVIDIA GPU (16GB+ VRAM recommended)
- **70GB+ free disk space** for models and Isaac Lab
- **24GB+ of VRAM** for ComfyUI with MeshCraft

### Installation

**Install**
```bash
git clone https://github.com/max-seeli/scan2wall.git
cd scan2wall
./scripts/setup.sh
```
You will be asked for a Gemini API Key during setup!
You can also skip adding it during setup and add it later;

Edit `.env` and add your Gemini API key:
- **Required**: `GOOGLE_API_KEY` - Get from [Google AI Studio](https://makersuite.google.com/app/apikey)

### Running

```bash
./scripts/start.sh
```
This opens tmux windows automatically. Use `Ctrl+B` then number keys to switch between them.
ComfyUI will be on port 8188, upload server on port 49100.

Once started, visit the URL to upload photos!

## Features

✅ Real-time job status updates
✅ AI-powered material inference (mass, friction, dimensions)
✅ State-of-the-art 3D mesh+texture generation
✅ Realistic physics simulation
✅ Automatic video recording from Isaac

## Documentation

- **[SETUP.md](SETUP.md)** - Detailed installation guide
- TOUPDATE

## Project Structure

TOUPDATE

## API Endpoints

- `GET /` - Upload page
- `POST /upload` - Submit image
- `GET /job/{job_id}` - Check job status
- `GET /jobs` - List all jobs (admin)

TOUPDATE^

## Future Ideas

- Trebuchet minigame
- Sliding down a plane minigame
- Segmentation of 3D reconstruction

## Built For

**NVIDIA Simulation Hack** (October 10-12, 2025)

This project showcases the integration of multiple cutting-edge AI and physics systems:
- Tencent's Hunyuan 3D 2.1 for image-to-3D generation
- Google's Gemini 2.0 Flash for intelligent material property inference
- NVIDIA's Isaac Sim for high-fidelity physics simulation

Made by:

Andrea Pozzetti
Max Seeliger
Patrick Styll
Volgt

## License

MIT License - see [LICENSE](LICENSE) file for details

## Acknowledgments

Thank you to Jua, Flexion Robotics and NVIDIA for the Hackathon!

## Contact

Issues: [GitHub Issues](https://github.com/max-seeli/scan2wall/issues)