# LoRe Project — Dynamic Duplex Coms TIAN Software

This branch is the current reference implementation for the laptop-side **Tian Software** reliability layer before the real ESP32 + LoRa transport is connected.

It supports two independent Tian Software processes, reliable half-duplex transfer, queued sending from both sides, randomized channel contention, selective retransmission with NACK, timeout recovery for lost control frames, text/image payload processing, configurable fault-injection scenarios, a live interactive two-Tian simulation, per-node action scenarios, and a serial-ready frame boundary for future ESP32 firmware.

> Terminology: **Tian Software** is the laptop-side application/protocol component. A complete physical node may later contain Tian Software + ESP32 + LoRa, but Tian Software itself is not called a node in this documentation.

## IMPORTANT: start here for the new live simulation

The new live simulation is a major change. It runs three persistent terminals:

```text
Terminal 1 = Channel / packet monitor panel
Terminal 2 = Tian Software A
Terminal 3 = Tian Software B
```

A and B can send text and images live, and **each Tian process can load its own independent node scenario**.

Read this guide before using the feature:

- [`docs/LIVE_SIMULATION.md`](docs/LIVE_SIMULATION.md) — complete step-by-step guide for launching live mode, manual text/image transfer, creating a separate scenario for A and B, delays, image paths, `/load`, `/run`, pause/resume/stop, autorun, channel scenarios, packet loss, contention, troubleshooting mistakes, and recommended tests.

The most important distinction is:

```text
NODE SCENARIO    = what Tian A or Tian B wants to send
CHANNEL SCENARIO = what the simulated radio channel does to the packets
```

Examples included in the repository:

```text
simulation/scenarios/node_a_example.json
simulation/scenarios/node_b_example.json
simulation/scenarios/live_channel.json
```

## Documentation map

Start here, then use the detailed guides when you need deeper information:

- [`docs/LIVE_SIMULATION.md`](docs/LIVE_SIMULATION.md) — **new live two-Tian mode and per-node scenarios; read this first for the new feature.**
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system responsibilities, data flow, queueing, channel ownership, both-send behavior, text/image processing, and process structure.
- [`docs/PROTOCOL.md`](docs/PROTOCOL.md) — binary frame format, DATA/END/NACK/COMPLETE, CRC, packet numbering, missing-packet detection, retransmission, NACK paging, timeout recovery, and protocol limits.
- [`docs/SIMULATION_GUIDE.md`](docs/SIMULATION_GUIDE.md) — original/predefined simulator, installation, Quick Test, panel JSON scenarios, loss syntax, random seeds, sequence semantics, logs, and expected results.
- [`docs/ESP32_INTEGRATION.md`](docs/ESP32_INTEGRATION.md) — Tian Software ↔ ESP32 serial contract, future radio responsibilities, half-duplex behavior, and a staged hardware integration plan.
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — common setup/runtime problems such as missing Pillow, terminal launcher issues, bad image paths, ports, and interpreting stalled simulations.
- [`docs/TERMINAL_SCENARIO_BUILDER.md`](docs/TERMINAL_SCENARIO_BUILDER.md) — create/save/preload Tian A/B node scenarios entirely in the terminal.
- [`docs/CHANNEL_SCENARIO_BUILDER.md`](docs/CHANNEL_SCENARIO_BUILDER.md) — create/save/preload Panel packet-loss/channel scenarios entirely in the terminal.
- [`docs/REAL_PACKET_DELAY.md`](docs/REAL_PACKET_DELAY.md) — real inter-frame TX delay used to make DATA/END/NACK/COMPLETE visible during experiments.
- [`docs/NODE_SCENARIO_PACING.md`](docs/NODE_SCENARIO_PACING.md) — timing between scripted node actions; separate from packet transmission delay.
- [`docs/EXPERIMENT_OBSERVABILITY.md`](docs/EXPERIMENT_OBSERVABILITY.md) — node encode/decode traces, TX/RX detail, and Panel metadata commands.

## Quick start

Use a virtual environment so the three child terminals use the same Python installation and dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 lore_sim.py
```

You can also start the menu with:

```bash
./RUN_ME.sh
```

`RUN_ME.sh` simply changes to the repository directory and runs `python3 lore_sim.py`.

The required Python packages are currently:

```text
cryptography
Pillow
pyserial
```

Current menu:

```text
1) QUICK TEST (predefined messages)
2) LIVE INTERACTIVE A <-> B
3) Run saved JSON channel scenario
4) View / validate JSON channel scenario
5) Run included example
6) Exit
```

For the new live feature choose **2** and follow [`docs/LIVE_SIMULATION.md`](docs/LIVE_SIMULATION.md).

For the original predefined simulator choose **1**.

## Quick Test flow

The original predefined Quick Test asks for a direction:

```text
1) A -> B
2) B -> A
3) A and B both send
```

Then each sender chooses its application payload:

```text
1) Text
2) Image
```

For text, Tian Software sends the actual text once. It no longer repeats the message to artificially create a large payload.

For an image, enter a local path such as:

```text
/home/user/Pictures/test.png
```

The current image path is:

```text
source image
  -> convert to RGB
  -> thumbnail, maximum 240 x 240
  -> JPEG quality 50
  -> zlib compression
  -> 64-bit millisecond timestamp
  -> AES-GCM encryption
  -> LoRe DATA frames
```

The receiver reverses the Tian payload processing and saves the reconstructed JPEG under `received/`.

### Important image limitation

Current image mode is a **processed image-transfer test**, not an exact original-file transfer. A PNG/JPEG input is converted to RGB, resized if needed, and encoded as JPEG quality 50 before transmission. Therefore the received file is not byte-for-byte identical to the original PNG.

If the final project requires exact PNG/file preservation, a later binary/file payload mode should send the original file bytes instead of the current image-preview pipeline.

## Reliable transfer in one picture

A normal successful transaction looks like:

```text
Sender                                 Receiver
  |                                       |
  |-- DATA 0 ---------------------------->|
  |-- DATA 1 ---------------------------->|
  |-- DATA 2 --------X lost               |
  |-- DATA 3 ---------------------------->|
  |-- END ------------------------------->|
  |                                       |
  |<---------------------- NACK [2] ------|
  |                                       |
  |-- DATA 2 ---------------------------->|
  |-- END ------------------------------->|
  |                                       |
  |<----------------------- COMPLETE -----|
  |                                       |
       transaction finished; release channel
```

Only missing DATA indexes are retransmitted.

## Half-duplex and both-send behavior

One physical LoRa radio cannot normally transmit and receive at the same instant. The design therefore gives one reliable message transaction ownership of the shared channel at a time.

If A and B both have queued messages, both can request the channel. The simulator waits for a short contention window and generates randomized backoff values. The smallest backoff wins.

Example:

```text
A requests channel
B requests channel
A backoff = 34 ms
B backoff = 79 ms
A wins
```

A then owns the **transaction**, not the radio direction permanently. During A's transaction the radio direction may switch:

```text
A -> B : DATA / END
B -> A : NACK
A -> B : retransmitted DATA / END
B -> A : COMPLETE
```

After a delivered `COMPLETE`, channel ownership is released. The previous loser remains eligible to send. The previous winner may also request again if it still has another queued message. Each new message transaction requires channel access again.

The current simulator uses randomized contention rather than strict round-robin fairness, so the same side can theoretically win more than once.

## Loss-sequence Quick Test syntax

Example:

```text
1,2,5 | 2,5 | random:1 | 20% | none+nack | none
```

Meaning:

```text
Sequence 1 -> manually drop DATA indexes 1,2,5
Sequence 2 -> drop indexes 2,5 if those indexes are present in this retry window
Sequence 3 -> randomly drop exactly 1 DATA frame from this window
Sequence 4 -> each DATA frame has 20% independent loss probability
Sequence 5 -> no DATA loss, but drop the NACK response
Sequence 6 -> clean window
```

Packet indexes are **zero-based**. A trace such as:

```text
DATA index=6 total=7
```

means the message has DATA indexes `0..6`, seven DATA frames total.

Supported compact controls:

```text
none
1,2,5
random:2
20%
none+end
1,3+nack
random:1+complete
```

See [`docs/SIMULATION_GUIDE.md`](docs/SIMULATION_GUIDE.md) for exact predefined sequence behavior and JSON equivalents.

## Three independent processes

Both simulator styles use three programs:

```text
Terminal 1: Simulation Control / Monitor Panel
Terminal 2: Tian Software A
Terminal 3: Tian Software B
```

The panel is the simulated shared medium. It performs arbitration and deliberate fault injection, but it does **not** reconstruct messages or generate NACK decisions for Tian Software.

Tian Software A and B each execute their own queue, sender session, receive sessions, NACK handling, timeout behavior, payload processing, and packet trace.

The processes communicate over localhost TCP for simulation only. Encoded LoRe frames are base64-wrapped inside newline-delimited JSON messages between the Tian processes and the panel. This simulation IPC is separate from the future ESP32 serial framing.

## Live mode in one picture

```text
node_a_example.json                 node_b_example.json
       |                                   |
       v                                   v
+--------------+                    +--------------+
| Tian A       |                    | Tian B       |
| + keyboard   |                    | + keyboard   |
+--------------+                    +--------------+
       |                                   |
       +---------------+ +-----------------+
                       | |
                       v v
                 +-------------+
                 |   PANEL     |
                 | contention  |
                 | packet loss |
                 +-------------+
                       ^
                       |
               live_channel.json
```

**A's JSON controls A, B's JSON controls B, and the panel JSON controls the simulated radio channel between them.**

## Current LoRe frame summary

The protocol uses:

```text
16-byte binary header
0..180-byte frame payload
2-byte CRC-16/CCITT-FALSE
```

A maximum-size DATA frame is therefore:

```text
16 + 180 + 2 = 198 bytes
```

Main frame types:

```text
DATA      message chunk
END       sender finished the current TX/retry window
NACK      receiver lists missing DATA indexes
COMPLETE  receiver has the complete message
```

The current header includes protocol version, frame type, content type, source node ID, message ID, total packet/page count, packet/page index, and payload length.

There is currently **no destination-node field** in the frame. The present runtime assumes the two-party A/B topology.

See [`docs/PROTOCOL.md`](docs/PROTOCOL.md) for the full field layout and state behavior.

## ESP32 boundary

The intended future hardware pipeline is:

```text
        Text / Image / Application
                    |
                    v
      Tian Software payload processing
                    |
                    v
          Tian reliable protocol
        DATA / END / NACK / COMPLETE
                    |
                    v
            serial_transport.py
                    |
                    v
[2-byte big-endian length][encoded LoRe frame]
                    |
                    v
                  ESP32
                    |
                    v
                LoRa radio
                    |
                    RF
                    |
                    v
LoRa radio -> ESP32 -> serial -> Tian Software
```

The current serial envelope is intentionally simple:

```text
uint16 big-endian frame_length
frame_length bytes of encoded LoRe frame
```

`serial_transport.py` allows up to 1024 bytes per serial frame envelope; the current LoRe DATA frame is at most 198 bytes.

The ESP32 should eventually move encoded frame bytes between USB serial and the LoRa radio. Tian Software remains responsible for payload processing, packetization, missing-packet calculation, NACK construction, retransmission decisions, and reconstruction.

See [`docs/ESP32_INTEGRATION.md`](docs/ESP32_INTEGRATION.md).

## Reliability behavior currently covered

The protocol/test suite currently verifies frame encode/decode, CRC corruption detection, 16-bit packet indexes, missing-packet detection, selective retransmission, DATA loss recovery, lost END recovery, lost response/COMPLETE recovery, multi-page NACKs, source-node consistency, serial-envelope round trips, bidirectional Tian Software transfers, text payload round trips, and image payload round trips.

Run everything with:

```bash
python3 -m unittest discover -s tests -v
```

## Current limitations and things not to over-assume

This branch is a strong simulation/reference stage, but it is not yet the final radio implementation.

- The AES-GCM key in `tian_payload.py` is a fixed demo/test key. It is not production key management.
- Image mode deliberately converts images to a reduced JPEG; it does not preserve original PNG bytes.
- `ContentType.BINARY` exists in the protocol, but current terminal UI exposes Text and Image only.
- The simulation panel is a centralized medium/arbitrator. Real LoRa channel sensing/CAD is not implemented yet.
- Randomized arbitration does not guarantee strict fairness.
- Panel loss sequences are consumed globally in chronological TX-window order, including when both A and B send.
- Node scenarios are independent per Tian process, but channel sequences are global to the panel.
- The simulator currently injects DATA/END/NACK/COMPLETE loss. Duplicate, reordering, bit-corruption, and latency injection are not exposed in the current scenario UI.
- CRC validation exists, but real RF corruption still needs hardened handling before production hardware use.
- The frame contains a source ID but no destination ID, so the present design is best understood as a two-party link.

## Source-file guide

```text
lore_sim.py
  main menu: predefined + live launcher

tian_payload.py
  text/image timestamping, image processing, AES-GCM encode/decode

tian_software.py
  outbound queue, sender/receiver sessions, reliability actions

lore_protocol.py
  binary frame definition, CRC, DATA/END/NACK/COMPLETE,
  missing detection, retransmission, protocol-level simulator

serial_transport.py
  future Tian Software <-> ESP32 length-prefixed serial envelope

simulation/panel.py
  shared-medium simulator, contention and loss injection

simulation/live_panel.py
  enhanced live Panel terminal commands and channel-scenario builder

simulation/channel_scenario_manager.py
  terminal-only channel scenario list/select/preview/build/save logic

simulation/node_process.py
  predefined-simulation Tian process

simulation/interactive_node.py
  live Tian process, keyboard commands, per-node scenario player,
  node scenario builder integration, packet delay and experiment traces

simulation/node_scenario_manager.py
  terminal-only Tian node scenario list/select/preview/build/save logic

simulation/experiment_trace.py
  experiment metadata and compact transfer summaries

simulation/launch_three_terminals.py
  opens predefined panel + A + B

simulation/launch_live_terminals.py
  opens enhanced live panel + interactive A + interactive B

simulation/scenarios/node_a_example.json
  example application actions for Tian A

simulation/scenarios/node_b_example.json
  example application actions for Tian B

simulation/scenarios/live_channel.json
  default clean live shared-medium configuration

tests/
  protocol, serial, dynamic Tian Software, and payload tests
```

## Latest live-simulator additions

The detailed material above remains the foundation. The following features were added later and extend it.

### Terminal-only scenario creation

Node scenarios no longer require manual JSON editing for normal use:

```text
A> /scenario make
B> /scenario make
```

The builder can add TEXT/IMAGE actions, edit action delays, set scenario pacing, save as a new JSON file, and automatically preload the newly saved scenario. Existing files are never overwritten.

The Panel now has an equivalent channel builder:

```text
PANEL> /scenario make
```

It can configure:

```text
DATA loss: none / manual indexes / random exact count / probability
Drop END
Drop NACK
Drop COMPLETE
random seed
contention window
max randomized backoff
multiple retry sequences
```

See [`docs/TERMINAL_SCENARIO_BUILDER.md`](docs/TERMINAL_SCENARIO_BUILDER.md) and [`docs/CHANNEL_SCENARIO_BUILDER.md`](docs/CHANNEL_SCENARIO_BUILDER.md).

### Real streaming DATA through the Panel

Live mode now makes PASS/DROP decisions as each DATA frame arrives and immediately forwards passed DATA to the opposite Tian process.

The Panel does **not** wait for END and then burst the whole DATA window to the receiver.

Conceptually:

```text
A TX DATA 0 -> Panel PASS/DROP -> B RX DATA 0
wait configured sender frame delay
A TX DATA 1 -> Panel PASS/DROP -> B RX DATA 1
...
A TX END    -> Panel PASS/DROP -> B RX END if passed
```

END remains only the protocol boundary telling the receiver to evaluate whether DATA is missing.

### `/delay` versus `/pacing`

These are separate controls:

```text
/delay normal       0 s between transmitted protocol frames
/delay slow         0.25 s between DATA/END/NACK/COMPLETE frames
/delay very-slow    1 s between protocol frames
/delay 0.5          custom 0.5 s inter-frame delay
```

`/pacing` controls node-scenario action timing instead:

```text
/pacing normal      +0 s between scripted actions
/pacing slow        +2 s between scripted actions
/pacing very-slow   +5 s between scripted actions
```

See [`docs/REAL_PACKET_DELAY.md`](docs/REAL_PACKET_DELAY.md) and [`docs/NODE_SCENARIO_PACING.md`](docs/NODE_SCENARIO_PACING.md).

### Experiment observability

Tian terminals show encode/decode details and use `[EXPRIMT]` for high-level experiment summaries. Individual protocol frames prioritize direction and protocol meaning through `[TX]` and `[RX]` lines.

The Panel provides:

```text
/metadata current
/metadata on
/metadata off
/metadata status
```

so the latest metadata can be inspected once or full sequence metadata can be shown continuously.

See [`docs/EXPERIMENT_OBSERVABILITY.md`](docs/EXPERIMENT_OBSERVABILITY.md).

### Builder input safety

The node scenario builder runs inside the one stdin-reading thread. This prevents two concurrent `input()` calls from stealing each other's keystrokes while keeping the network loop active in the background.

The live Panel builder follows the same single-keyboard-reader design.

For the live workflow continue with [`docs/LIVE_SIMULATION.md`](docs/LIVE_SIMULATION.md).
For deeper system design continue with [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
