# Simulation Guide

This guide explains how to install, run, configure, and interpret the current three-process Tian Software simulator.

## 1. What the simulator is testing

The simulator is designed to test Tian Software before ESP32/LoRa hardware is inserted.

The real target architecture is:

```text
Tian Software A <-> ESP32 A <-> LoRa A <-> RF <-> LoRa B <-> ESP32 B <-> Tian Software B
```

The simulator temporarily replaces the middle hardware with:

```text
Tian Software A <-> Simulation Panel <-> Tian Software B
```

The panel does not replace Tian Software. A and B are separate Tian Software processes.

## 2. Install dependencies

Recommended:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Then verify:

```bash
python3 -c "from PIL import Image; print('Pillow OK')"
python3 -c "from cryptography.hazmat.primitives.ciphers.aead import AESGCM; print('cryptography OK')"
```

## 3. Start the simulator

Normal method:

```bash
python3 lore_sim.py
```

Menu:

```text
1) QUICK TEST (recommended)
2) Run saved JSON scenario
3) View / validate JSON scenario
4) Run included example
5) Exit
```

## 4. Quick Test direction

Choose:

```text
1) A -> B
2) B -> A
3) A and B both send
```

Option 3 is the contention test. Both sides queue a message and request channel access.

## 5. Payload selection

For each active sender:

```text
1) Text
2) Image
```

### Text

Enter a message such as:

```text
Hello from A
```

The message is sent once. The simulator no longer repeats the string to make it artificially large.

Short text may fit into only one DATA frame after Tian payload overhead. Use an image or a naturally longer text if you want many DATA packets.

### Image

Enter a valid local path:

```text
/home/user/Pictures/test.png
```

The file must exist on the same machine that runs the Tian process.

Current image processing:

```text
RGB -> max 240x240 -> JPEG quality 50 -> zlib -> AES-GCM
```

This means even a very large PNG may become a relatively small transmitted payload.

## 6. Compact loss-sequence syntax

Quick Test accepts one line such as:

```text
1,2,5 | 2,5 | random:1 | 20% | none+nack | none
```

The pipe character `|` separates chronological transmission/retransmission windows.

### Manual DATA loss

```text
1,2,5
```

Drop DATA indexes 1, 2, and 5 if those indexes are present in the current window.

Indexes are zero-based.

### Random exact count

```text
random:3
```

Randomly choose exactly three DATA frames from the DATA frames actually present in that current TX window.

If the retry window only contains two DATA frames, the implementation clamps the count to the available number.

### Random probability

```text
20%
```

Each DATA frame in that window independently has a 20% probability of being dropped.

### No DATA loss

```text
none
```

### Control-frame loss

Append one or more control flags:

```text
none+end
none+nack
none+complete
1,3+nack
random:1+complete
```

Current compact parser accepts these control names:

```text
end
nack
complete
```

## 7. What a sequence means exactly

Each sequence is selected when an END frame closes the current sender window.

The panel temporarily buffers the DATA frames belonging to that window. When END arrives, it applies that sequence's DATA-loss rule to the buffered DATA frames and applies `drop_end` to END.

The NACK or COMPLETE produced because of that window is also associated with that same sequence, so `drop_nack` or `drop_complete` can affect the response.

Then the next sender TX/retry window consumes the next sequence.

Example:

```text
Sequence 1 = 1,2,5
Sequence 2 = 2,5
Sequence 3 = none
```

Possible behavior:

```text
initial DATA window
  drop 1,2,5
  END arrives
  receiver NACK [1,2,5]

retry window contains only 1,2,5
  sequence 2 attempts drop 2,5
  receiver gets 1
  receiver NACK [2,5]

retry window contains only 2,5
  sequence 3 drops nothing
  receiver COMPLETE
```

## 8. Important sequence behavior when both sides send

The sequence list is currently **global to the simulation panel**.

It is consumed in chronological TX-window order, regardless of whether A or B owns that transaction.

Example:

```text
sequences = [S1, S2, S3, S4]
```

If A wins first and requires three windows, A may consume S1, S2, and S3. B's first TX window would then use S4.

Therefore the sequence list is not currently a separate independent sequence schedule per direction.

For precise direction-specific experiments, either:

- run A->B or B->A separately, or
- carefully design enough global sequences for the expected chronological order.

## 9. What happens after the configured sequence list ends

If a transfer needs more windows than you configured, the panel creates an implicit clean fallback sequence:

```text
default-N
DATA loss = none
```

That is why logs may show:

```text
SEQ 2 default-2 PASS ...
```

It means no explicit Sequence 2 existed, so the simulator used a clean default.

## 10. Random seed

The scenario contains:

```json
"seed": 48291
```

A random seed makes pseudorandom decisions repeatable.

It affects both:

- random packet-loss choices
- randomized contention backoff

Using the same scenario and same seed should produce the same pseudorandom sequence of choices, assuming the same order of operations.

If the seed is `null` or Quick Test input is left blank, a new random state is used each run.

Use a fixed seed when you want to reproduce a failure.

## 11. Quick Test saves JSON automatically

Quick Test writes its generated scenario to:

```text
simulation/scenarios/quick_last.json
```

You can inspect it later or rerun it through menu option 2.

## 12. JSON scenario structure

Typical scenario:

```json
{
  "seed": 48291,
  "contention_window_ms": 80,
  "max_backoff_ms": 120,
  "messages": [
    {
      "sender": "A",
      "label": "A-text",
      "payload_type": "text",
      "text": "Hello from A"
    },
    {
      "sender": "B",
      "label": "B-image",
      "payload_type": "image",
      "path": "/home/user/Pictures/test.png"
    }
  ],
  "sequences": [
    {
      "name": "initial loss",
      "data_loss": {
        "mode": "manual",
        "indexes": [1, 2, 5]
      }
    },
    {
      "name": "retry random",
      "data_loss": {
        "mode": "random_count",
        "count": 1
      }
    },
    {
      "name": "lost response",
      "data_loss": {
        "mode": "none"
      },
      "drop_nack": true
    }
  ]
}
```

## 13. JSON DATA loss modes

### None

```json
"data_loss": {"mode": "none"}
```

### Manual

```json
"data_loss": {
  "mode": "manual",
  "indexes": [1, 2, 5]
}
```

### Random exact count

```json
"data_loss": {
  "mode": "random_count",
  "count": 3
}
```

### Random probability

```json
"data_loss": {
  "mode": "random_probability",
  "probability": 0.20
}
```

Probability in JSON is `0.0..1.0`, whereas Quick Test uses percentage syntax such as `20%`.

## 14. Control-loss JSON

Any sequence can additionally include:

```json
"drop_end": true,
"drop_nack": true,
"drop_complete": true
```

These are booleans.

## 15. Three terminals and what each one means

### Simulation panel

Typical logs:

```text
[PANEL] A connected node_id=1
[PANEL] B connected node_id=2
[PANEL] A requests channel
[PANEL] B requests channel
[PANEL] contention A:34ms, B:79ms -> A wins
```

Frame events:

```text
[PANEL] SEQ 1 sequence-1 DROP A->B DATA#2
[PANEL] SEQ 1 sequence-1 PASS A->B END
[PANEL] SEQ 1 sequence-1 PASS B->A NACK[2]
```

End:

```text
[PANEL] DONE completed=2/2 delivered=... dropped=...
```

`completed=2/2` means two configured messages completed.

### Tian Software sender

Example:

```text
[QUEUE] TEXT 'Hello from A' ...
[CHANNEL] GRANTED backoff=34ms
[TX] DATA index=0 total=4
[TX] DATA index=1 total=4
[TX] DATA index=2 total=4
[TX] DATA index=3 total=4
[TX] END round=0
[RX] NACK [2]
[TX] DATA index=2 total=4
[TX] END round=1
[RX] COMPLETE
[TRANSFER] COMPLETE
```

### Tian Software receiver

Example:

```text
[RX] DATA index=0 total=4
[RX] DATA index=1 total=4
[RX] DATA index=3 total=4
[RX] END round=0
[TX] NACK [2]
...
[TX] COMPLETE
[MESSAGE] TEXT from=1 bytes=... text='Hello from A'
```

## 16. Both-send contention example

Suppose both A and B have one queued message.

```text
A requests
B requests
```

The panel waits `contention_window_ms` so near-simultaneous requests can be considered together.

It then generates backoffs between 5 ms and `max_backoff_ms`.

Example:

```text
A: 38 ms
B: 71 ms
A wins
```

B remains waiting.

After A's COMPLETE is delivered, the panel releases the channel.

B is then still eligible to acquire it and send.

If a side has another locally queued message after completing its current transfer, it can request again as well.

## 17. Manual three-terminal execution

If automatic terminal launching does not work, run these manually from the project directory with the same activated virtual environment.

Terminal 1:

```bash
python3 -m simulation.panel --scenario simulation/scenarios/example.json
```

Terminal 2:

```bash
python3 -m simulation.node_process --name A --id 1
```

Terminal 3:

```bash
python3 -m simulation.node_process --name B --id 2
```

The panel must be running before or approximately when A/B connect.

## 18. Automatic terminal launcher

`simulation/launch_three_terminals.py` tries terminal applications in this order:

```text
konsole
gnome-terminal
xterm
```

If none exists, it prints the three manual commands instead.

The launcher uses the same `sys.executable` that ran `lore_sim.py`. This is one reason activating the virtual environment before launch is important.

## 19. Example tests to try

### Clean A -> B

```text
none
```

Expected:

```text
no NACK
COMPLETE after first END
```

### One missing packet

```text
1 | none
```

Expected:

```text
NACK [1]
selective retry DATA 1
COMPLETE
```

### Progressive loss

```text
1,2,5 | 2,5 | 5 | none
```

Expected NACK progression:

```text
[1,2,5]
[2,5]
[5]
COMPLETE
```

provided all referenced indexes exist in the corresponding windows.

### Lost END

```text
none+end | none
```

Expected:

```text
first END dropped
sender timeout
sender retries END
receiver responds
```

### Lost NACK

```text
1+nack | none | none
```

Expected:

```text
DATA 1 missing
NACK lost
sender timeout
sender retries END
receiver sends NACK again
sender retransmits DATA 1
```

### Lost COMPLETE

```text
none+complete | none
```

Expected:

```text
receiver complete
first COMPLETE dropped
sender timeout
sender retries END
receiver COMPLETE again
```

### Random count

```text
random:3 | none
```

### Random probability

```text
30% | 20% | none
```

### Both send

Choose option 3 and use:

```text
none
```

First verify arbitration/queue behavior without packet loss. Then add loss sequences.

## 20. Current simulator limitations

The current UI injects frame loss only.

It does not currently expose:

- duplicate injection
- packet reordering
- arbitrary bit corruption
- propagation delay/jitter controls
- per-direction independent sequence lists
- strict fairness scheduling

CRC corruption itself is tested at protocol unit-test level.

## 21. Run unit tests

```bash
python3 -m unittest discover -s tests -v
```

This is recommended after changing protocol or transport code.
