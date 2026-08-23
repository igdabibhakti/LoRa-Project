#!/usr/bin/env python3
"""Easy terminal launcher for LoRe/Tian Software simulation."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCENARIO_DIR = ROOT / "simulation" / "scenarios"
DEFAULT_SCENARIO = SCENARIO_DIR / "example.json"
QUICK_SCENARIO = SCENARIO_DIR / "quick_last.json"
LIVE_CHANNEL_SCENARIO = SCENARIO_DIR / "live_channel.json"


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value if value else default


def parse_manual_indexes(token: str) -> list[int]:
    if not token.strip(): return []
    vals=[]
    for part in token.split(','):
        part=part.strip()
        if not part: continue
        value=int(part)
        if value < 0: raise ValueError("packet indexes cannot be negative")
        vals.append(value)
    return sorted(set(vals))


def parse_sequence_token(token: str, number: int) -> dict:
    pieces=[p.strip().lower() for p in token.split('+') if p.strip()]
    data_part=pieces[0] if pieces else 'none'; flags=set(pieces[1:])
    if data_part in {'','none','clean','0'}: loss={'mode':'none'}
    elif data_part.startswith('random:'):
        count=int(data_part.split(':',1)[1]);
        if count < 0: raise ValueError('random count cannot be negative')
        loss={'mode':'random_count','count':count}
    elif data_part.endswith('%'):
        percent=float(data_part[:-1])
        if not 0 <= percent <= 100: raise ValueError('percentage must be 0..100')
        loss={'mode':'random_probability','probability':percent/100.0}
    else: loss={'mode':'manual','indexes':parse_manual_indexes(data_part)}
    unknown=flags-{'end','nack','complete'}
    if unknown: raise ValueError('unknown control fault: '+','.join(sorted(unknown)))
    seq={'name':f'sequence-{number}','data_loss':loss}
    if 'end' in flags: seq['drop_end']=True
    if 'nack' in flags: seq['drop_nack']=True
    if 'complete' in flags: seq['drop_complete']=True
    return seq


def parse_sequence_line(raw: str) -> list[dict]:
    toks=[x.strip() for x in raw.split('|') if x.strip()]
    if not toks: toks=['none']
    return [parse_sequence_token(t,i) for i,t in enumerate(toks,1)]


def choose_payload(sender: str) -> dict:
    print(f"\nPayload for {sender}:")
    print("1) Text")
    print("2) Image")
    typ=ask("Choose", "1")
    if typ == '2':
        while True:
            raw=ask("Image path")
            path=Path(raw).expanduser().resolve()
            if path.is_file():
                return {'sender':sender,'label':f'{sender}-image','payload_type':'image','path':str(path)}
            print(f"File not found: {path}")
    text=ask(f"{sender} text message", f"Hello from {sender}")
    return {'sender':sender,'label':f'{sender}-text','payload_type':'text','text':text}


def load_json(path: Path) -> dict:
    with path.open('r',encoding='utf-8') as f: cfg=json.load(f)
    if not isinstance(cfg.get('messages'),list) or not isinstance(cfg.get('sequences'),list):
        raise ValueError('scenario must contain messages[] and sequences[]')
    return cfg


def launch(path: Path) -> None:
    load_json(path)
    subprocess.run([sys.executable,str(ROOT/'simulation'/'launch_three_terminals.py'),'--scenario',str(path)],check=True)


def launch_live() -> None:
    print("\n=== LIVE INTERACTIVE TWO-TIAN SIMULATION ===")
    print("Three terminals will open: Channel Panel, Tian A, Tian B.")
    print("Both Tian terminals accept normal text and /image <path> live.")
    print("Each Tian terminal can also load its own node scenario with /load <file.json>.")
    print("\nOptional startup node scenarios:")
    a_raw=ask("A scenario path (Enter = manual only)","")
    b_raw=ask("B scenario path (Enter = manual only)","")
    autorun=False
    if a_raw or b_raw:
        autorun=ask("Autorun loaded scenario(s)? y/n","n").lower().startswith('y')
    command=[sys.executable,str(ROOT/'simulation'/'launch_live_terminals.py'),'--panel-scenario',str(LIVE_CHANNEL_SCENARIO)]
    if a_raw: command += ['--a-scenario',str(Path(a_raw).expanduser().resolve())]
    if b_raw: command += ['--b-scenario',str(Path(b_raw).expanduser().resolve())]
    if autorun: command += ['--autorun']
    subprocess.run(command,check=True)


def quick_test() -> Path:
    print("\n=== QUICK TEST ===")
    print("1) A -> B")
    print("2) B -> A")
    print("3) A and B both send")
    direction=ask("Choose","1")
    if direction not in {'1','2','3'}: direction='1'
    messages=[]
    if direction in {'1','3'}: messages.append(choose_payload('A'))
    if direction in {'2','3'}: messages.append(choose_payload('B'))

    print("\nLoss sequence syntax:")
    print("  1,2,5        = manually lose DATA packet indexes 1,2,5")
    print("  random:2     = lose exactly 2 random DATA packets")
    print("  20%          = 20% DATA loss probability")
    print("  none         = no DATA loss")
    print("  +end/+nack/+complete = also lose that control frame")
    print("  |            = next retransmission sequence")
    print("Example: 1,2,5 | 2,5 | random:1 | none+nack | none")
    while True:
        raw=ask("Loss sequences","1,2,5 | none")
        try: sequences=parse_sequence_line(raw); break
        except ValueError as exc: print(f"Invalid sequence: {exc}")
    seed_raw=ask("Random seed (Enter = random every run)","")
    seed=int(seed_raw) if seed_raw else None
    cfg={'seed':seed,'contention_window_ms':80,'max_backoff_ms':120,'messages':messages,'sequences':sequences}
    SCENARIO_DIR.mkdir(parents=True,exist_ok=True)
    QUICK_SCENARIO.write_text(json.dumps(cfg,indent=2)+'\n',encoding='utf-8')
    print(f"\nSaved scenario: {QUICK_SCENARIO}")
    for m in messages:
        if m['payload_type']=='image': print(f"  {m['sender']}: IMAGE {m['path']}")
        else: print(f"  {m['sender']}: TEXT {m['text']!r}")
    print(f"Sequences: {len(sequences)}")
    print("Launching Panel + Tian Software A + Tian Software B...")
    return QUICK_SCENARIO


def choose_json() -> Path:
    SCENARIO_DIR.mkdir(parents=True,exist_ok=True)
    files=sorted(SCENARIO_DIR.glob('*.json'))
    if files:
        print("\nSaved scenarios:")
        for i,p in enumerate(files,1): print(f"  {i}) {p.name}")
        raw=ask("Choose number or type path","1")
        if raw.isdigit() and 1 <= int(raw) <= len(files): return files[int(raw)-1]
        return Path(raw).expanduser().resolve()
    return Path(ask("JSON path")).expanduser().resolve()


def show_json(path: Path): print(json.dumps(load_json(path),indent=2))


def main():
    while True:
        print("\n====================================\n LoRe / Tian Software Simulator\n====================================")
        print("1) QUICK TEST (predefined messages)\n2) LIVE INTERACTIVE A <-> B\n3) Run saved JSON channel scenario\n4) View / validate JSON channel scenario\n5) Run included example\n6) Exit")
        choice=ask("Choose","2")
        try:
            if choice=='1': launch(quick_test()); return
            if choice=='2': launch_live(); return
            if choice=='3': path=choose_json(); show_json(path); launch(path); return
            if choice=='4': show_json(choose_json()); continue
            if choice=='5': show_json(DEFAULT_SCENARIO); launch(DEFAULT_SCENARIO); return
            if choice=='6': return
        except (OSError,ValueError,json.JSONDecodeError,subprocess.CalledProcessError) as exc:
            print(f"ERROR: {exc}")

if __name__=='__main__': main()
