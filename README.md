# scan2wall

**Scan objects and simulate throwing them at a wall using AI and physics.**

A hackathon project for NVIDIA's Simulation Hack that combines:
- 📱 Phone camera capture
- 🤖 AI-powered 3D mesh generation (Hunyuan 2.1)
- 🧠 Material property inference (Gemini 2.0 Flash)
- 🎮 Physics simulation (NVIDIA Isaac Sim)
- 🎬 Automatic video recording

## Quick Demo

1. Take a photo of any object on your phone
2. Upload via web interface (QR code provided)
3. Wait ~1 minute
4. Watch your object get thrown at a pyramid in a physics simulation

## Features

✅ Mobile-friendly web interface with QR code access
✅ Real-time job status updates
✅ AI-powered material property inference (mass, friction)
✅ State-of-the-art 3D generation (Hunyuan 2.1)
✅ Realistic physics simulation (Isaac Sim)
✅ Automatic video recording and encoding
✅ Error handling and validation

## Documentation

- **[SETUP.md](SETUP.md)** - Complete installation and setup guide
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System architecture and technical details
- **[EMAIL_INTEGRATION.md](EMAIL_INTEGRATION.md)** - Future email feature design
- **[3d_gen/README.md](3d_gen/README.md)** - ComfyUI and model setup
- **[src/scan2wall/image_collection/README.md](src/scan2wall/image_collection/README.md)** - Upload server details

## Quick Start

### Prerequisites
- Linux with NVIDIA GPU (8GB+ VRAM)
- Python 3.10+
- NVIDIA Isaac Sim
- CUDA Toolkit

### Installation

```bash
# 1. Clone repository
git clone https://github.com/yourusername/scan2wall.git
cd scan2wall

# 2. Copy environment template
cp .env.example .env
# Edit .env and add your GOOGLE_API_KEY

# 3. Install main dependencies
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
uv pip install -e .

# 4. Set up ComfyUI (in separate terminal)
cd 3d_gen
conda create -n comfyui python=3.10 -y
conda activate comfyui
bash comfy.sh
bash modeldownload.sh
```

See [SETUP.md](SETUP.md) for detailed instructions.

### Running

**Terminal 1** - ComfyUI:
```bash
cd 3d_gen
conda activate comfyui
cd ComfyUI
python main.py --listen 0.0.0.0 --port 8188
```

**Terminal 2** - ComfyUI API Server:
```bash
cd 3d_gen
conda activate comfyui
python server.py
```

**Terminal 3** - Main Upload Server:
```bash
uv run src/scan2wall/image_collection/run.py
```

Scan the generated QR code or visit the printed URL on your phone.

## How It Works

```
Phone Photo → Upload Server → Material Inference (Gemini) →
3D Generation (Hunyuan 2.1) → Mesh Conversion →
Isaac Sim Physics → Video Recording → Done!
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed pipeline documentation.

## Tech Stack

- **Frontend**: HTML5, JavaScript, Fetch API
- **Backend**: FastAPI, Python 3.11
- **3D Generation**: ComfyUI + Hunyuan 2.1
- **Material Analysis**: Google Gemini 2.0 Flash
- **Physics**: NVIDIA Isaac Sim
- **Video**: ffmpeg (H.264 encoding)

## Project Structure

```
scan2wall/
├── src/scan2wall/
│   ├── image_collection/    # Upload server and web UI
│   └── material_properties/  # Gemini API integration
├── 3d_gen/                  # ComfyUI and 3D generation
├── isaac_scripts/           # Isaac Sim simulation scripts
├── recordings/              # Generated videos
└── docs/                    # Documentation
```

## Configuration

Environment variables (`.env`):
```bash
GOOGLE_API_KEY=your_gemini_api_key_here
PORT=49100
COMFY_SERVER_URL=http://127.0.0.1:8012
```

See `.env.example` for full configuration options.

## API Endpoints

- `GET /` - Upload page (mobile UI)
- `POST /upload` - Upload image
- `GET /job/{job_id}` - Check job status
- `GET /jobs` - List all jobs (admin)

## Troubleshooting

**Upload page not accessible from phone?**
- Ensure phone and server are on same WiFi
- Check firewall allows port 49100

**ComfyUI model not found?**
- Re-run `modeldownload.sh`
- Check models are in `3d_gen/ComfyUI/models/`

**Isaac Sim crashes?**
- Check VRAM usage
- Try reducing simulation resolution

See [SETUP.md](SETUP.md) for more troubleshooting tips.

## Future Features

- 📧 Email integration (send photo via email)
- 🎨 Custom simulation settings
- 📊 Usage dashboard
- 🌐 Public gallery
- 🔗 Social media sharing

See [EMAIL_INTEGRATION.md](EMAIL_INTEGRATION.md) for email feature design.

## Contributing

This is a hackathon project! Contributions welcome:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License - see LICENSE file for details

## Credits

Built for NVIDIA's Simulation Hack hackathon.

Technologies:
- [NVIDIA Isaac Sim](https://developer.nvidia.com/isaac-sim)
- [Hunyuan 2.1](https://github.com/Tencent/Hunyuan3D-2) by Tencent
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
- [Google Gemini](https://ai.google.dev/)

## Contact

Issues: [GitHub Issues](https://github.com/yourusername/scan2wall/issues)

## Acknowledgments

Special thanks to NVIDIA for hosting the Simulation Hack and providing Isaac Sim access!
