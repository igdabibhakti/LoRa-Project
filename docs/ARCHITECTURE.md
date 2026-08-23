# Architecture

This document describes the current Tian Software reliability branch and the simulation architecture used before ESP32 + LoRa integration.

## 1. System goal

The final intended physical path is:

```text
Laptop application/user
    -> Tian Software
    -> ESP32
    -> LoRa radio
    -> RF
    -> LoRa radio
    -> ESP32
    -> Tian Software
    -> laptop application/user
```

The current branch replaces ESP32 + LoRa with a three-process simulator so the reliability protocol can be tested first.

## 2. Responsibility split

### Tian Software

Tian Software owns:

- text/image input
- image preprocessing
- timestamp application metadata
- AES-GCM encryption/decryption
- LoRe DATA packetization
- END generation
- receive-session state
- missing-DATA detection
- NACK generation
- multi-page NACK collection
- selective retransmission
- COMPLETE processing
- timeout-driven END retry
- outgoing FIFO queue
- message reconstruction
- received text/image output

### Panel / simulated channel

The Panel replaces the shared RF medium during testing. It owns:

- A/B connections
- channel requests
- randomized contention/backoff
- current reliable-transaction ownership
- routing encoded LoRe frames between A and B
- configured DATA loss
- configured END/NACK/COMPLETE loss
- PASS/DROP logging
- random-seed behavior
- experiment metadata display
- channel-scenario selection/building
- channel release after a delivered COMPLETE

The Panel does **not** reconstruct application messages and does **not** decide which DATA indexes are missing. Missing detection and NACK creation remain inside the receiving Tian Software process.

### ESP32 later

The intended ESP32 role is a frame transport/radio bridge:

```text
receive encoded frame from Tian over serial
-> transmit it through LoRa

receive encoded frame from LoRa
-> return it to Tian over serial
```

The ESP32 will also manage physical radio TX/RX switching.

It should not need to understand JPEG, zlib, AES-GCM, NACK algorithms, or image reconstruction.

## 3. Three-process live design

```text
                     +---------------------------+
                     | Enhanced Live Panel       |
                     | shared medium + faults    |
                     | terminal scenario builder |
                     +-------------+-------------+
                                   |
                             localhost TCP
                           /               \
                          /                 \
               +---------+------+     +-----+----------+
               | Tian A         |     | Tian B         |
               | node_id = 1    |     | node_id = 2    |
               | terminal input |     | terminal input |
               | node scenarios |     | node scenarios |
               +----------------+     +----------------+
```

A and B execute independent Tian protocol state. They are not mock objects inside the Panel.

## 4. Live Panel layering

The simulator separates the medium engine from the enhanced live terminal controls:

```text
simulation/panel.py
    shared-medium engine
    streaming DATA routing
    contention
    DATA/control-frame loss
    sequence tracking
    metadata capture

simulation/live_panel.py
    enhanced live terminal UI
    /scenario list/select/preview/make
    terminal channel-scenario builder integration
```

This keeps the original/predefined simulator path available while giving live mode richer terminal controls.

## 5. Application payload path

### Text

```text
text
-> UTF-8
-> prepend 64-bit millisecond timestamp
-> AES-GCM
-> ContentType.TEXT
-> DATA packetization
```

Receive path:

```text
reassembled encrypted bytes
-> AES-GCM decrypt
-> remove timestamp
-> UTF-8 decode
-> final text
```

### Image

Current image mode is a processed preview transfer:

```text
source image
-> RGB
-> thumbnail maximum 240x240
-> JPEG quality 50
-> zlib level 9
-> prepend millisecond timestamp
-> AES-GCM
-> ContentType.IMAGE
-> DATA packetization
```

Receive path:

```text
reassemble
-> decrypt
-> remove timestamp
-> zlib decompress
-> JPEG bytes
-> save under received/
```

It is not byte-perfect PNG/file preservation.

## 6. Protocol path

```text
prepared encrypted payload
-> DATA 0
-> DATA 1
-> ...
-> DATA N
-> END
```

Receiver stores DATA by packet index.

On END:

```text
expected = 0 .. total_packets-1
received = indexes stored in receive session
missing  = expected - received
```

If missing:

```text
receiver -> NACK [missing indexes]
```

If complete:

```text
receiver -> COMPLETE
```

A NACK causes the sender to transmit only requested DATA indexes plus a new END.

## 7. Streaming shared-medium behavior

The live Panel forwards or drops DATA **immediately** as each frame arrives.

Correct conceptual timing:

```text
A TX DATA 0
-> Panel PASS/DROP DATA 0
-> B RX DATA 0 if passed

A TX DATA 1
-> Panel PASS/DROP DATA 1
-> B RX DATA 1 if passed
```

The Panel does not buffer a complete sender window until END.

This matters because the real inter-frame delay on A/B should be visible at the receiver too.

END is only the protocol boundary telling the receiver that the sender has finished the current window.

## 8. How streaming loss decisions work

For manual loss, the Panel already knows the configured indexes.

For random probability, each expected index is selected independently using the configured probability.

For exact random count on an initial window, the first DATA frame exposes `total_packets`, so the Panel can preselect exactly N indexes from:

```text
0 .. total_packets-1
```

before forwarding the first frame.

For exact random count during retransmission, the Panel remembers the missing indexes contained in the successfully delivered NACK response. Those indexes define the next retry DATA window, allowing the Panel to preselect exact retry losses without buffering.

## 9. Half-duplex transaction ownership

Channel ownership is per reliable message transaction, not permanent radio direction.

Example when A owns the transaction:

```text
A -> B : DATA / END
B -> A : NACK
A -> B : missing DATA / END
B -> A : COMPLETE
```

Only one side transmits in each direction window, so the design fits a half-duplex LoRa radio.

After a delivered COMPLETE, the transaction owner releases the channel.

## 10. Both sides sending

Suppose:

```text
A queue = [A1, A2]
B queue = [B1]
```

Both can request the idle channel.

The Panel waits through the configured contention window, generates randomized backoff values and grants the smallest value.

The loser remains queued.

After COMPLETE releases the channel, any side with pending data may request again.

This is randomized arbitration, not strict round-robin fairness.

## 11. Node scenarios

A node scenario controls what one Tian process wants to send.

Terminal commands:

```text
/scenario list
/scenario select <number|name|path>
/scenario preview
/scenario make
```

Node scenarios contain:

```text
TEXT actions
IMAGE actions
per-action delay
scenario pacing
```

The terminal builder runs in the same stdin-owning thread as normal node input. This avoids multiple simultaneous `input()` calls stealing keystrokes.

The networking/main loop continues to run while the modal builder owns keyboard input.

## 12. Channel scenarios

A channel scenario controls what the simulated medium does.

Panel commands:

```text
/scenario list
/scenario select <number|name|path>
/scenario preview
/scenario make
```

Channel scenarios contain transmission sequences that can configure:

```text
DATA loss = none/manual/random_count/random_probability
Drop END
Drop NACK
Drop COMPLETE
random seed
contention window
max randomized backoff
```

Node and channel scenarios are deliberately separate concepts.

## 13. Lost-control recovery

### Lost END

```text
sender DATA arrives
END lost
receiver does not evaluate window yet
sender gets no response
sender timeout
sender retries END
receiver evaluates existing DATA
```

### Lost NACK

```text
receiver detects missing DATA
NACK lost
sender timeout
sender retries END
receiver still knows the same DATA is missing
receiver sends NACK again
```

### Lost COMPLETE

```text
receiver is already complete
COMPLETE lost
sender timeout
sender retries END
receiver remains complete
receiver sends COMPLETE again
```

## 14. Real TX delay and scenario pacing

These are separate mechanisms.

```text
/delay
    actual time between protocol frames sent by a Tian process

/pacing
    extra time between scripted node scenario actions
```

Current TX-delay presets:

```text
normal    0s
slow      0.25s
very-slow 1s
```

## 15. Observability path

Tian A/B expose high-level experiment traces for application encode/decode and transmission windows.

Per-frame node output prioritizes:

```text
[TX] / [RX]
-> DATA / END / NACK / COMPLETE
-> protocol/frame detail
```

High-level summaries use:

```text
[EXPRIMT]
```

The Panel can display concise ENCODE/TRANSMIT/DECODE information and optional full metadata.

These traces travel only through simulation control IPC; they are not inserted into LoRe frames.

## 16. Simulation IPC vs future serial

### Current simulator

```text
newline JSON over localhost TCP
encoded LoRe frame bytes represented as base64 inside JSON
```

### Future Tian <-> ESP32

`serial_transport.py` uses:

```text
2-byte big-endian encoded-frame length
followed by that many raw encoded LoRe bytes
```

The LoRe frame format and Tian reliability state should not need to change when replacing simulator IPC with ESP32 serial transport.

## 17. Current module layout

```text
lore_sim.py
    top-level launcher/menu

lore_protocol.py
    binary frame format, CRC, sender/receiver sessions

tian_software.py
    queue + reliability wrapper

tian_payload.py
    text/image application processing + AES-GCM

serial_transport.py
    future Tian <-> ESP32 serial envelope

simulation/common.py
    simulator JSON/base64 helpers

simulation/panel.py
    shared-medium engine, streaming DATA, contention, fault injection

simulation/live_panel.py
    enhanced live Panel terminal commands + channel builder

simulation/interactive_node.py
    live Tian A/B terminal runtime

simulation/node_scenario_manager.py
    node scenario store + terminal builder

simulation/channel_scenario_manager.py
    channel scenario store + terminal builder

simulation/experiment_trace.py
    experiment/metadata formatting

simulation/launch_live_terminals.py
    starts enhanced Panel + Tian A + Tian B
```

## 18. Current assumptions/limitations

- two communicating parties, A and B
- no destination ID in LoRe frame yet
- one active reliable transaction on the shared medium at a time
- centralized Panel arbitration is simulation-only
- fixed demo AES key
- current image mode is reduced JPEG preview transfer
- randomized contention does not guarantee strict fairness
- channel scenario sequences are global in chronological window order
- malformed/corrupt RF input handling still needs hardening for hardware use

The next architecture stage is to preserve this protocol behavior while replacing the Panel transport boundary with ESP32 serial + LoRa radio transport.
