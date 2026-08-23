# Architecture

This document explains how the current LoRe/Tian Software branch is structured and why the responsibilities are divided the way they are.

## 1. System goal

The project is building a reliable half-duplex data link that can eventually move text and processed images over:

```text
Laptop
  -> Tian Software
  -> ESP32
  -> LoRa radio
  -> RF
  -> LoRa radio
  -> ESP32
  -> Tian Software
  -> Laptop application/user
```

The current branch replaces the ESP32 + LoRa middle with a simulation transport so the laptop-side logic can be tested first.

## 2. Main responsibilities

### Tian Software

Tian Software owns application and reliability logic:

- user/application payload input
- text encoding
- image preprocessing
- timestamp insertion
- AES-GCM encryption/decryption
- packetization into LoRe DATA frames
- END generation
- receive-session tracking
- missing-packet detection
- NACK generation
- selective retransmission
- COMPLETE processing
- outbound message queue
- timeout-driven END retry
- message reconstruction
- received text display
- received image output

### ESP32 later

The ESP32 is intended to be a transport/radio bridge:

- receive one encoded LoRe frame from Tian Software over serial
- transmit that frame through the LoRa radio
- receive an encoded LoRe frame from LoRa
- return that frame to Tian Software over serial
- manage radio TX/RX switching
- eventually provide real channel-clear / channel-activity information if required

The ESP32 should not need to understand JPEG, zlib, AES-GCM, missing indexes, or how NACKs are computed.

### Simulation panel now

The simulation panel temporarily replaces the shared RF medium. It:

- accepts connections from Tian Software A and B
- receives channel requests
- performs randomized contention/backoff
- tracks the current transaction owner
- routes encoded LoRe frames between A and B
- applies configured DATA/END/NACK/COMPLETE loss
- records PASS/DROP events and statistics
- releases the channel after a delivered COMPLETE

It does not perform Tian's reassembly or NACK logic.

## 3. Three-process design

The simulator deliberately runs as three independent processes:

```text
+---------------------------+
| Simulation Panel          |
| shared medium + faults    |
+-------------+-------------+
              |
        localhost TCP
        /             \
       /               \
+-----+------+      +---+--------+
| Tian A     |      | Tian B     |
| node_id=1  |      | node_id=2  |
+------------+      +------------+
```

This is important because A and B are not mock objects inside one simulator process. Each side executes its own Tian Software protocol state.

## 4. Application payload path

### Text

```text
text string
  -> UTF-8 bytes
  -> prepend 64-bit millisecond timestamp
  -> AES-GCM encrypt
  -> ContentType.TEXT
  -> packetize into DATA frames
```

On receive:

```text
reassembled encrypted payload
  -> AES-GCM decrypt
  -> remove timestamp
  -> UTF-8 decode
  -> print once
```

### Image

Current image mode is optimized for a compact image-transfer test:

```text
source image
  -> Pillow open
  -> convert RGB
  -> thumbnail to maximum 240 x 240
  -> JPEG quality 50
  -> zlib level 9
  -> prepend millisecond timestamp
  -> AES-GCM encrypt
  -> ContentType.IMAGE
  -> packetize
```

On receive:

```text
reassemble
  -> decrypt
  -> remove timestamp
  -> zlib decompress
  -> JPEG bytes
  -> save under received/
```

This is not an exact original-file transfer. A PNG source becomes a processed JPEG.

## 5. Protocol path

After the payload layer creates encrypted bytes:

```text
prepared payload
  -> make_data_frames()
  -> DATA 0
  -> DATA 1
  -> ...
  -> DATA N
  -> END
```

The receiver stores DATA by `packet_index`.

When END arrives, it calculates:

```text
expected indexes = 0 .. total_packets-1
received indexes = keys stored in receive session
missing = expected - received
```

If missing is not empty:

```text
receiver -> NACK [missing indexes]
```

If complete:

```text
receiver -> COMPLETE
```

## 6. Half-duplex transaction ownership

The design distinguishes **transaction ownership** from instantaneous radio direction.

If A wins the channel, A owns the reliable message transaction until COMPLETE, but B must still transmit responses.

Example:

```text
A owns transaction

A -> B : DATA 0,1,2,3
A -> B : END
B -> A : NACK [2]
A -> B : DATA 2
A -> B : END
B -> A : COMPLETE

release ownership
```

This fits one-radio half duplex because only one side transmits during each direction window.

## 7. Both sides sending at once

Suppose:

```text
A queue = [A1, A2]
B queue = [B1]
```

A and B both request the idle channel.

The simulator assigns random backoffs, for example:

```text
A = 34 ms
B = 79 ms
```

A wins and sends A1. B's B1 remains queued.

After A1 receives COMPLETE:

```text
channel -> IDLE
```

A may still have A2. B still has B1. Both are allowed to request again.

Therefore a later contention may be won by either A or B.

The design is not strict alternation. Winning one transaction does not permanently give the channel to that side, and losing one contention does not discard the queued message.

## 8. Queue behavior

`tian_software.py` stores outgoing messages in a FIFO deque.

`queue_message()` appends a prepared payload.

`begin_next_transfer()` removes the oldest queued message and creates a `SenderSession`.

A Tian Software process asks for channel access when:

- it has queued data, and
- it does not already have an active outbound transfer.

After a COMPLETE, if its queue still contains another message, it may request again.

## 9. Why ownership is per complete transaction

Releasing the channel after every DATA frame would allow unrelated transactions to interleave:

```text
A DATA 0
B DATA 0
A DATA 1
B DATA 1
...
```

That would complicate half-duplex scheduling and response ownership.

The current design instead keeps one reliable message transaction active through its DATA, END, NACK/retry, and COMPLETE cycle.

## 10. Simulation transport vs future serial transport

The simulator's inter-process transport is not the same as the ESP32 serial wire format.

### Simulation IPC

The panel and Tian processes communicate using newline-delimited JSON over localhost TCP. Encoded LoRe frames are base64 encoded so they can be carried inside JSON.

### Future Tian ↔ ESP32 serial

`serial_transport.py` uses:

```text
2-byte unsigned big-endian frame length
followed by exactly that many encoded LoRe frame bytes
```

This separation lets the RF simulation be removed later without changing the LoRe frame format or Tian reliability engine.

## 11. Current module layout

```text
lore_sim.py
  terminal menu, Quick Test, JSON scenario creation/selection

tian_payload.py
  application payload processing and encryption

tian_software.py
  queue and reliability engine wrapper

lore_protocol.py
  binary frames, CRC, receive/sender sessions

serial_transport.py
  future ESP32 serial framing

simulation/common.py
  simulator JSON/base64 socket helpers

simulation/panel.py
  medium, contention, loss injection

simulation/node_process.py
  one independent Tian Software runtime

simulation/launch_three_terminals.py
  starts panel, A, and B in separate terminals
```

## 12. Design assumptions today

The current implementation assumes:

- two communicating parties, A and B
- one half-duplex radio per physical side later
- one active reliable message transaction on the shared medium at a time
- source IDs are sufficient for the present two-party topology
- application encryption uses the same demo key at both ends
- simulation channel arbitration is centralized for testing

Future multi-node networking will need additional addressing and MAC design beyond the current branch.
