import argparse, shlex, shutil, subprocess, sys, time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
py = sys.executable
ap = argparse.ArgumentParser(description="Open Panel, Tian Software A, and Tian Software B in separate terminals")
ap.add_argument("--scenario", default=str(root / "simulation/scenarios/example.json"))
args = ap.parse_args()
scenario = str(Path(args.scenario).expanduser().resolve())

commands = [
    f"cd {shlex.quote(str(root))}; {shlex.quote(py)} -m simulation.panel --scenario {shlex.quote(scenario)}",
    f"cd {shlex.quote(str(root))}; {shlex.quote(py)} -m simulation.node_process --name A --id 1",
    f"cd {shlex.quote(str(root))}; {shlex.quote(py)} -m simulation.node_process --name B --id 2",
]
term = shutil.which("konsole") or shutil.which("gnome-terminal") or shutil.which("xterm")
if not term:
    print("No supported GUI terminal launcher found.")
    print("Run these commands manually in 3 terminals:")
    for i, command in enumerate(commands, 1): print(f"Terminal {i}: {command}")
    raise SystemExit(1)
for command in commands:
    if "konsole" in term:
        subprocess.Popen([term, "-e", "bash", "-lc", command + "; exec bash"])
    elif "gnome-terminal" in term:
        subprocess.Popen([term, "--", "bash", "-lc", command + "; exec bash"])
    else:
        subprocess.Popen([term, "-e", "bash", "-lc", command + "; exec bash"])
    time.sleep(0.4)
print(f"Started 3-terminal simulation using: {scenario}")
