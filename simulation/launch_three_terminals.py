import shutil, subprocess, sys, time
from pathlib import Path
root = Path(__file__).resolve().parents[1]
py = sys.executable
scenario = str(root / "simulation/scenarios/example.json")
commands = [
    f"cd {root}; {py} -m simulation.panel --scenario {scenario}",
    f"cd {root}; {py} -m simulation.node_process --name A --id 1",
    f"cd {root}; {py} -m simulation.node_process --name B --id 2",
]
term = shutil.which("konsole") or shutil.which("gnome-terminal") or shutil.which("xterm")
if not term:
    print("No supported terminal launcher found. Open 3 terminals manually and use README commands.")
    raise SystemExit(1)
for command in commands:
    if "konsole" in term:
        subprocess.Popen([term, "-e", "bash", "-lc", command + "; exec bash"])
    elif "gnome-terminal" in term:
        subprocess.Popen([term, "--", "bash", "-lc", command + "; exec bash"])
    else:
        subprocess.Popen([term, "-e", "bash", "-lc", command + "; exec bash"])
    time.sleep(0.4)
