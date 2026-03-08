"""
Firebot Launcher
A minimal Python script that re-launches menubar_app.py from the venv.
This is compiled by PyInstaller into a real .app bundle that macOS accepts.
"""
import os
import sys
import subprocess

# Get the directory where this launcher lives
# For a .app bundle, the agent dir is 3 levels up from the executable:
# Firebot.app/Contents/MacOS/Firebot -> agent/
launcher_path = os.path.abspath(__file__)
agent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(launcher_path))))

# If running as a PyInstaller bundle, _MEIPASS is set
if getattr(sys, 'frozen', False):
    # We're inside .app bundle: Contents/MacOS/Firebot
    # Go up to Firebot.app, then up one more to agent/
    bundle_dir = os.path.dirname(sys.executable)  # Contents/MacOS/
    agent_dir = os.path.dirname(os.path.dirname(os.path.dirname(bundle_dir)))

venv_python = os.path.join(agent_dir, "venv", "bin", "python3")
menubar_script = os.path.join(agent_dir, "app_window.py")

# Redirect logs
log_path = "/tmp/firebot_menubar.log"

with open(log_path, "w") as log:
    log.write(f"Launching from: {agent_dir}\n")
    log.write(f"Python: {venv_python}\n")
    log.write(f"Script: {menubar_script}\n")

proc = subprocess.Popen(
    [venv_python, menubar_script],
    cwd=agent_dir,
    stdout=open(log_path, "a"),
    stderr=subprocess.STDOUT,
)
proc.wait()
