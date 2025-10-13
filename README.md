# scan2wall

**Scan objects and simulate throwing them at a wall using AI and physics.**

![Demo](images/loop.gif)

A hackathon project for NVIDIA's Simulation Hack that combines phone camera capture, AI-powered 3D mesh generation, material property inference, and realistic physics simulation.

## How It Works

1. 📱 Take a photo of any object on your phone
2. ⬆️ Upload via web interface (QR code provided)
3. 🤖 AI generates 3D mesh and infers material properties
4. 🎮 Object gets thrown at a pyramid in Isaac Sim
5. 🎬 Watch the simulation video

**Total time: ~1-2 minutes**

## Tech Stack

- **3D Generation**: [Hunyuan 3D 2.1](https://github.com/Tencent/Hunyuan3D-2) via [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
- **Material Analysis**: Google Gemini 2.0 Flash
- **Physics Simulation**: NVIDIA Isaac Sim
- **Backend**: FastAPI, Python 3.11
- **Frontend**: HTML5 + JavaScript

## Quick Start

### Prerequisites

- **Linux** with NVIDIA GPU (16GB+ VRAM recommended)
- **CUDA** toolkit installed
- **50GB+ free disk space** for models and Isaac Lab

### Installation

```bash
# Clone repository
git clone https://github.com/max-seeli/scan2wall.git
cd scan2wall

# Install Python dependencies for upload server
pip install fastapi uvicorn python-multipart python-dotenv pillow requests google-generativeai qrcode

# Setup ComfyUI and download models (~8GB, takes ~15 min)
cd 3d_gen
bash setup_comfyui.sh
bash modeldownload.sh
cd ..

# Setup Isaac Lab (~10GB, takes ~20 min)
# Follow instructions at: https://github.com/isaac-sim/IsaacLab
```

### Configuration

```bash
cp .env.example .env
```

Edit `.env` and add your Gemini API key:
- **Required**: `GOOGLE_API_KEY` - Get from [Google AI Studio](https://makersuite.google.com/app/apikey)
- Everything else is pre-configured for single-machine setup!

### Running

**Option 1: Automated (with tmux)**
```bash
./start.sh auto
```
This opens tmux windows automatically. Use `Ctrl+B` then number keys to switch between them.

**Option 2: Manual (2 separate terminals)**
```bash
./start.sh
```
This prints commands to run in 2 separate terminal windows:
- Terminal 1: ComfyUI backend
- Terminal 2: Upload server

Once started, scan the QR code or visit the URL on your phone to upload photos!

## Features

✅ Mobile-first web interface
✅ Real-time job status updates
✅ AI-powered material inference (mass, friction, dimensions)
✅ State-of-the-art 3D generation
✅ Realistic physics simulation
✅ Automatic video recording

## Documentation

- **[SETUP.md](SETUP.md)** - Detailed installation guide
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System architecture and technical details
- **[EMAIL_INTEGRATION.md](EMAIL_INTEGRATION.md)** - Future email feature design

## Project Structure

```
scan2wall/
├── 3d_gen/
│   ├── image_collection/    # Upload server and web UI
│   ├── material_properties/ # Gemini API integration
│   ├── utils/               # Path configuration
│   └── ComfyUI/             # 3D generation backend
├── isaac_scripts/           # Isaac Sim simulation scripts
└── recordings/              # Generated videos
```

## API Endpoints

- `GET /` - Upload page
- `POST /upload` - Submit image
- `GET /job/{job_id}` - Check job status
- `GET /jobs` - List all jobs (admin)

## Troubleshooting

**Can't connect from phone?**
- Ensure same WiFi network
- Check firewall allows the port

**ComfyUI model not found?**
- Re-run `modeldownload.sh`

**Isaac Sim crashes?**
- Check VRAM usage
- Reduce simulation resolution

See [SETUP.md](SETUP.md) for more troubleshooting.

## Future Ideas

- 📧 Email integration
- 🎨 Custom simulation settings
- 🌐 Public gallery
- 🔗 Social media sharing

## Built For

**NVIDIA Simulation Hack** (October 10-12, 2025)

This project showcases the integration of multiple cutting-edge AI and physics systems:
- Tencent's Hunyuan 3D 2.1 for image-to-3D generation
- Google's Gemini 2.0 Flash for intelligent material property inference
- NVIDIA's Isaac Sim for high-fidelity physics simulation

## License

MIT License - see [LICENSE](LICENSE) file for details

## Acknowledgments

Special thanks to NVIDIA for hosting the Simulation Hack and providing Isaac Sim access!

## Contact

Issues: [GitHub Issues](https://github.com/max-seeli/scan2wall/issues)
