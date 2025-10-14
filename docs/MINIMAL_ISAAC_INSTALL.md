# Minimal Isaac Lab Installation for scan2wall

## Overview

The scan2wall project only uses basic Isaac Sim and Isaac Lab functionality for mesh conversion and simple physics simulation. The default Isaac Lab installation includes extensive RL/robotics dependencies that are **not needed** for this project.

## What scan2wall Actually Needs

### Required Components
- ✅ Isaac Sim 5.0.0 (pip package)
- ✅ Isaac Lab core utilities (`isaaclab.app`, `isaaclab.sim`)
- ✅ Basic USD/Omniverse functionality
- ✅ Physics simulation (PhysX)

### NOT Needed (but installed by default)
- ❌ `isaaclab_tasks` - RL training environments
- ❌ `isaaclab_rl` - RL framework integration
- ❌ `isaaclab_mimic` - Imitation learning
- ❌ PyTorch, TensorBoard, Transformers - ML frameworks (except PyTorch for Isaac)
- ❌ stable-baselines3, rsl-rl, rl-games, skrl, ray - RL libraries
- ❌ gymnasium - RL environment API
- ❌ hpp-fcl, pinocchio, dex-retargeting - Advanced robotics

## Disk Space Comparison

| Installation Type | Venv Size | Install Time | What's Included |
|------------------|-----------|--------------|-----------------|
| **Full** (default) | ~8-10 GB | 20-25 min | Everything (RL, robotics, ML) |
| **Minimal** (recommended) | ~3-4 GB | 8-10 min | Just what scan2wall needs |

## Minimal Installation Steps

### Option 1: Manual Minimal Install (Recommended for New Installs)

```bash
# 1. Create venv and install Isaac Sim
python3.11 -m venv /workspace/isaac_venv
source /workspace/isaac_venv/bin/activate
pip install isaacsim==5.0.0.0 --extra-index-url https://pypi.nvidia.com

# 2. Clone Isaac Lab
cd /workspace
git clone --depth 1 https://github.com/isaac-sim/IsaacLab.git
cd IsaacLab

# 3. Install ONLY base Isaac Lab (no extensions)
pip install -e source/isaaclab

# 4. Install minimal additional deps for our scripts
pip install warp-lang opencv-python
```

**Time saved:** ~10-15 minutes
**Space saved:** ~5-6 GB

### Option 2: Skip Isaac Lab Entirely (Most Minimal)

Since our scripts only use Isaac Lab's app launcher and basic sim utilities, you could potentially:

```bash
# Just install Isaac Sim
python3.11 -m venv /workspace/isaac_venv
source /workspace/isaac_venv/bin/activate
pip install isaacsim==5.0.0.0 --extra-index-url https://pypi.nvidia.com

# Clone Isaac Lab source (read-only, no install)
git clone --depth 1 https://github.com/isaac-sim/IsaacLab.git /workspace/IsaacLab

# Add Isaac Lab to PYTHONPATH instead of installing
export PYTHONPATH=/workspace/IsaacLab/source:$PYTHONPATH
```

**Time saved:** ~15-20 minutes
**Space saved:** ~6-7 GB

**Note:** This approach requires manual PYTHONPATH management and may be less robust.

## Why the Default Install Is Heavy

The Isaac Lab `./isaaclab.sh --install` command runs this workflow:
1. Installs PyTorch + CUDA (~3 GB)
2. Installs `isaaclab` package
3. Installs `isaaclab_tasks` (RL environments)
4. Installs `isaaclab_rl` (RL framework integrations)
5. Installs `isaaclab_mimic` (imitation learning)
6. Each extension pulls in many dependencies:
   - `stable-baselines3`, `rsl-rl`, `rl-games`, `skrl` - RL algorithms
   - `ray` - Distributed computing framework
   - `tensorboard`, `wandb` - Experiment tracking
   - `gymnasium` - RL environment API
   - `transformers` - NLP models (unused)
   - `hpp-fcl`, `pinocchio` - Advanced robotics

## For Future Setup Script Updates

Add a `--minimal` flag to `setup_isaac.sh`:

```bash
# In setup_isaac.sh, replace:
./isaaclab.sh --install

# With:
if [ "$MINIMAL_INSTALL" = "true" ]; then
    pip install -e source/isaaclab
    pip install warp-lang opencv-python
else
    ./isaaclab.sh --install
fi
```

## Verification

After minimal install, verify it works:

```bash
source /workspace/isaac_venv/bin/activate
python -c "from isaaclab.app import AppLauncher; print('✓ Isaac Lab core imported')"
python -c "import isaaclab.sim as sim_utils; print('✓ Sim utilities imported')"
```

Then test the actual scripts:

```bash
# Test mesh conversion (headless)
python isaac_scripts/convert_mesh.py \
    /path/to/input.glb /path/to/output.usd \
    --mass 1.0 --kit_args='--headless'

# Test simulation (headless)
python isaac_scripts/test_place_obj_video.py \
    --usd_path_abs /path/to/object.usd \
    --kit_args='--no-window'
```

## Migration from Full to Minimal

If you already have the full installation and want to switch:

```bash
# Back up current venv (optional)
mv /workspace/isaac_venv /workspace/isaac_venv.full

# Start fresh with minimal
python3.11 -m venv /workspace/isaac_venv
source /workspace/isaac_venv/bin/activate

# Install minimal deps
pip install isaacsim==5.0.0.0 --extra-index-url https://pypi.nvidia.com
cd /workspace/IsaacLab
pip install -e source/isaaclab
pip install warp-lang opencv-python
```

## Summary

For **scan2wall**, the minimal installation is sufficient and recommended for:
- Faster setup times
- Reduced disk usage
- Simpler dependency management
- Faster pip operations

The full installation is only needed if you plan to:
- Run Isaac Lab RL examples
- Train reinforcement learning agents
- Use advanced robotics features
- Contribute to Isaac Lab development
