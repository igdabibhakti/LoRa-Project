# LoRe Project — Reliable Half-Duplex Tian Software

This branch is the current reference implementation for the laptop-side **Tian Software** reliability layer before the real ESP32 + LoRa transport is connected.

Current working branch:

```text
feature/live-interactive-two-node-simulation
```

The protocol stage is considered good enough to move on to Tian Software ↔ ESP32 integration after simulation testing.

## What works now

The current live system supports:

- two independent Tian Software processes, A and B
- reliable half-duplex DATA / END / NACK / COMPLETE protocol
- missing-packet detection on the receiver
- selective retransmission of only missing DATA indexes
- timeout recovery when END, NACK, or COMPLETE is lost
- multi-page NACK support
- FIFO outgoing queues on both sides
- randomized shared-channel contention
- live manual text and image sending
- independent terminal-built node scenarios for A and B
- terminal-built Panel/channel scenarios for packet-loss experiments
- manual, exact-random-count, and probability DATA loss
- END / NACK / COMPLETE loss injection
- deterministic random seed support
- live streaming of DATA through the Panel instead of buffering until END
- real inter-frame TX delay for visually following packet flow
- Tian encode/decode experiment traces
- concise TX/RX-first node output
- optional full Panel metadata preview
- serial-ready LoRe frame boundary for future ESP32 integration

## Start here

Create/activate the Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Then run:

```bash
./RUN_ME.sh
```

or:

```bash
python3 lore_sim.py
```

For the current project workflow choose:

```text
2) LIVE INTERACTIVE A <-> B
```

Three terminals open:

```text
Terminal 1 = Panel / simulated shared LoRa channel
Terminal 2 = Tian Software A
Terminal 3 = Tian Software B
```

## The most important distinction

There are two completely different scenario types:

```text
NODE SCENARIO
= what Tian A or Tian B wants to send
= text, image, action order, action timing

CHANNEL SCENARIO
= what happens to the transmission
= DATA loss, END loss, NACK loss, COMPLETE loss,
  random seed and contention settings
```

Node scenario commands are typed in A or B:

```text
/scenario list
/scenario select <number|name|path>
/scenario preview
/scenario make
```

The `/protocol` command is an alias for `/scenario`.

Panel channel scenario commands are typed in the Panel:

```text
/scenario list
/scenario select <number|name|path>
/scenario preview
/scenario make
```

No JSON editing is required for the normal workflow anymore.

## Reliable transfer in one picture

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
       reliable transaction complete
```

The radio direction alternates, so the design never requires simultaneous TX and RX on one LoRa radio.

## What the control frames mean

```text
DATA
    one chunk of the application payload

END
    sender says: "this TX/retry window is finished; check what arrived"

NACK
    receiver says: "these DATA indexes are still missing"

COMPLETE
    receiver says: "I have the entire message"
```

If END is lost, the sender times out and retries END.

If NACK is lost, the sender times out and retries END; the receiver calculates/sends NACK again.

If COMPLETE is lost, the sender times out and retries END; the already-complete receiver sends COMPLETE again.

See `docs/PROTOCOL.md` for the full protocol definition.

## Live DATA streaming

The Panel now forwards or drops each DATA frame immediately as it arrives.

With a visible TX delay, the intended timeline is:

```text
A [TX] DATA 0
Panel PASS/DROP DATA 0
B [RX] DATA 0 if passed

wait TX delay

A [TX] DATA 1
Panel PASS/DROP DATA 1
B [RX] DATA 1 if passed
```

The Panel does **not** wait for END and then burst all stored DATA to the receiver.

END is only the protocol window boundary.

## Real packet/frame delay

In either Tian terminal:

```text
/delay normal
/delay slow
/delay very-slow
/delay 0.5
```

Current presets:

```text
normal    = 0 seconds between protocol frames
slow      = 0.25 seconds between protocol frames
very-slow = 1 second between protocol frames
number    = custom seconds
```

This controls actual sender spacing between DATA / END / NACK / COMPLETE frames.

Scenario action timing is separate:

```text
/pacing normal
/pacing slow
/pacing very-slow
```

See `docs/REAL_PACKET_DELAY.md` and `docs/NODE_SCENARIO_PACING.md`.

## Node terminal output

The node display prioritizes direction and protocol state.

Typical lines:

```text
[TX] DATA index=4 total=38 message_id=... content=IMAGE frame_bytes=198
[RX] DATA index=4 total=38 message_id=... content=IMAGE frame_bytes=198
[RX] NACK [3, 8, 14] message_id=...
[TX] END round=1 message_id=...
[RX] COMPLETE message_id=...
```

High-level experiment information uses the shorter prefix:

```text
[EXPRIMT]
```

The node no longer prints a duplicate `[EXPRIMT] DATA ...` line for every frame in addition to `[TX]`/`[RX]`.

## Experiment observability

Tian A/B can show:

```text
source text/image
-> image conversion / JPEG / zlib where applicable
-> timestamp application header
-> AES-GCM encryption
-> packetization / TX windows
-> retransmission
-> AES-GCM decryption
-> reconstruction
-> final text/image result
```

The Panel always shows concise ENCODE / TRANSMIT / PASS-DROP / DECODE information.

Optional Panel metadata commands:

```text
/metadata current
/metadata on
/metadata off
/metadata status
```

See `docs/EXPERIMENT_OBSERVABILITY.md`.

## Terminal-only Panel packet-loss builder

In the Panel:

```text
PANEL> /scenario make
```

You can build sequences containing:

```text
DATA loss:
  none
  manual packet indexes
  random exact count
  random probability

control loss:
  Drop END
  Drop NACK
  Drop COMPLETE

other controls:
  random seed
  contention window
  maximum randomized backoff
```

Saved channel scenarios go under:

```text
simulation/scenarios/channels/
```

Saving creates a new file and automatically selects it.

See `docs/CHANNEL_SCENARIO_BUILDER.md` for a complete explanation including the meaning of END/NACK/COMPLETE loss.

## Recommended first packet-loss experiment

Sequence 1:

```text
DATA loss     = random exact count 6
Drop END      = no
Drop NACK     = no
Drop COMPLETE = no
```

Sequence 2:

```text
DATA loss     = none
Drop END      = no
Drop NACK     = no
Drop COMPLETE = no
```

Expected result:

```text
initial window loses exactly 6 DATA frames
-> END passes
-> receiver sends NACK listing the 6 missing indexes
-> sender retransmits those indexes
-> clean retry passes
-> receiver sends COMPLETE
```

## Image pipeline

Current image mode is a processed preview transfer:

```text
source image
-> RGB
-> thumbnail maximum 240x240
-> JPEG quality 50
-> zlib level 9
-> 64-bit millisecond timestamp
-> AES-GCM
-> LoRe DATA frames
```

The receiver reconstructs a JPEG under `received/`.

This is **not** byte-perfect PNG/file transfer. Exact original-file preservation should be added later as a binary/file payload mode if required.

## Current LoRe frame format

```text
16-byte header
0..180-byte payload
2-byte CRC-16/CCITT-FALSE
```

Maximum DATA frame:

```text
16 + 180 + 2 = 198 bytes
```

Current frame types:

```text
DATA
END
NACK
COMPLETE
```

Current frames include a source node ID but no destination ID. The present design is therefore a two-party A/B link, not yet a general multi-node network.

## Half-duplex channel ownership

Channel ownership is per reliable message transaction, not permanent TX direction.

Example when A owns the transaction:

```text
A -> B : DATA / END
B -> A : NACK
A -> B : missing DATA / END
B -> A : COMPLETE
```

After a delivered COMPLETE, the Panel releases the channel. A or B can then compete for the next transaction.

## Simulation vs future ESP32

Current simulation:

```text
Tian A <-> localhost TCP <-> Panel <-> localhost TCP <-> Tian B
```

Future hardware:

```text
Tian Software
-> serial_transport.py
-> ESP32
-> LoRa radio
-> RF
-> LoRa radio
-> ESP32
-> serial_transport.py
-> Tian Software
```

The ESP32 should transport encoded LoRe frames and manage radio TX/RX switching. Tian Software remains responsible for payload processing and the reliability protocol.

## Documentation map

Use these as the current references:

- `docs/PROTOCOL.md` — DATA/END/NACK/COMPLETE, frame format, missing detection, retransmission, timeouts and protocol limits.
- `docs/ARCHITECTURE.md` — responsibilities of Tian Software, Panel, ESP32 and process/data flow.
- `docs/TERMINAL_SCENARIO_BUILDER.md` — terminal-only Tian A/B node scenario creation.
- `docs/CHANNEL_SCENARIO_BUILDER.md` — terminal-only Panel/channel scenario creation and all loss controls.
- `docs/REAL_PACKET_DELAY.md` — real inter-frame TX timing.
- `docs/NODE_SCENARIO_PACING.md` — timing between scripted actions.
- `docs/EXPERIMENT_OBSERVABILITY.md` — `[EXPRIMT]`, TX/RX detail and Panel metadata commands.
- `docs/TROUBLESHOOTING.md` — common simulator problems and expected timeout/retry behavior.
- `docs/ESP32_INTEGRATION.md` — next-stage Tian Software ↔ ESP32 serial integration.
- `docs/LIVE_SIMULATION.md` — extended live-simulator background and examples; some manual-JSON sections describe the older power-user workflow, while the terminal builders above are now preferred.
- `docs/SIMULATION_GUIDE.md` — original/predefined simulator reference.

## Main source files

```text
lore_protocol.py
    LoRe binary frames, CRC, receive/sender reliability sessions

tian_software.py
    queue + reliability wrapper

tian_payload.py
    text/image application processing and AES-GCM

simulation/interactive_node.py
    live Tian A/B terminal runtime

simulation/panel.py
    shared-medium streaming, arbitration and fault-injection engine

simulation/live_panel.py
    enhanced live Panel terminal commands and channel builder integration

simulation/node_scenario_manager.py
    node scenario store + terminal builder

simulation/channel_scenario_manager.py
    channel scenario store + terminal builder

simulation/experiment_trace.py
    experiment/metadata formatting

simulation/launch_live_terminals.py
    opens Panel + A + B

serial_transport.py
    future Tian Software ↔ ESP32 length-prefixed frame transport
```

## Tests

Protocol and existing unit tests can be run with:

```bash
python3 -m unittest discover -s tests -v
```

Recent live interactive changes should also be exercised manually in the three-terminal simulator before hardware integration, especially:

```text
clean text transfer
clean image transfer
6 random DATA losses + clean retry
lost END
lost NACK
lost COMPLETE
A and B both queue traffic
slow inter-frame transmission
Panel metadata current/on/off
node scenario builder
Panel channel scenario builder
```

## Current limitations

- Fixed demo AES-GCM key; not production key management.
- Image transfer is reduced JPEG preview, not exact original file bytes.
- Two-party topology; no destination ID yet.
- Centralized Panel arbitration is a simulation, not real LoRa CAD/MAC.
- No strict fairness guarantee for randomized contention.
- Channel sequences are global in chronological transmission-window order.
- Duplicate/reordering/bit-corruption/latency injection are not currently exposed in the terminal builder.
- Real RF malformed-frame handling still needs hardening.

The next major engineering stage is replacing the simulated transport boundary with the ESP32 serial/radio bridge while preserving the protocol behavior documented here.
