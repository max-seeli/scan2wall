#!/usr/bin/env python3
"""
Simple Isaac Sim GUI launcher with WebRTC streaming.
Opens an empty scene for manual USDZ import and testing.
"""

from isaaclab.app import AppLauncher

# Launch with WebRTC streaming
app_launcher = AppLauncher({
    "headless": True,
    "enable_cameras": True,
    "livestream": 2,  # WebRTC streaming
    "kit_args": "--enable omni.kit.livestream.webrtc"
})
simulation_app = app_launcher.app

# Import Isaac Lab modules after app launch
from isaaclab.sim import SimulationContext
import omni.usd

print("🎨 Isaac Sim GUI running with WebRTC streaming")
print("📺 Access at: http://localhost/viewer")
print("")
print("💡 Tip: Drag and drop USDZ files into the viewport to import them")
print("🛑 Press Ctrl+C to stop")

# Initialize simulation context
sim = SimulationContext()

# Keep the app running
while simulation_app.is_running():
    sim.step(render=True)

# Cleanup
simulation_app.close()
