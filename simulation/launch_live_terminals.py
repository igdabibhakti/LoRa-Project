import argparse, shlex, shutil, subprocess, sys, time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
py = sys.executable
ap = argparse.ArgumentParser(description="Open live Panel, Tian Software A, and Tian Software B in separate terminals")
ap.add_argument("--panel-scenario", default=str(root / "simulation/scenarios/live_channel.json"))
ap.add_argument("--a-scenario")
ap.add_argument("--b-scenario")
ap.add_argument("--a-delay", default="normal", help="A REAL inter-frame TX delay: normal, slow, very-slow, or seconds")
ap.add_argument("--b-delay", default="normal", help="B REAL inter-frame TX delay: normal, slow, very-slow, or seconds")
ap.add_argument("--a-pacing", help="optional A scenario action pacing override")
ap.add_argument("--b-pacing", help="optional B scenario action pacing override")
ap.add_argument("--autorun", action="store_true", help="autorun any preloaded node scenarios")
args = ap.parse_args()

panel_scenario = str(Path(args.panel_scenario).expanduser().resolve())

commands = [
    f"cd {shlex.quote(str(root))}; {shlex.quote(py)} -m simulation.live_panel --scenario {shlex.quote(panel_scenario)}",
]
for name, node_id, scenario, delay, pacing in [
    ("A", 1, args.a_scenario, args.a_delay, args.a_pacing),
    ("B", 2, args.b_scenario, args.b_delay, args.b_pacing),
]:
    cmd = (
        f"cd {shlex.quote(str(root))}; {shlex.quote(py)} -m simulation.interactive_node "
        f"--name {name} --id {node_id} --delay {shlex.quote(str(delay))}"
    )
    if pacing is not None:
        cmd += f" --pacing {shlex.quote(str(pacing))}"
    if scenario:
        cmd += f" --scenario {shlex.quote(str(Path(scenario).expanduser().resolve()))}"
        if args.autorun:
            cmd += " --autorun"
    commands.append(cmd)

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

print("Started live 3-terminal simulation")
print(f"Panel channel scenario: {panel_scenario}")
print("Panel terminal supports: /scenario list | select | preview | make")
print(f"A REAL TX frame delay: {args.a_delay}")
print(f"B REAL TX frame delay: {args.b_delay}")
if args.a_pacing is not None: print(f"A scenario action pacing override: {args.a_pacing}")
if args.b_pacing is not None: print(f"B scenario action pacing override: {args.b_pacing}")
if args.a_scenario: print(f"A node scenario: {args.a_scenario}")
if args.b_scenario: print(f"B node scenario: {args.b_scenario}")
