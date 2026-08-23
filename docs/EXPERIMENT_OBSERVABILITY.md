# Experiment Observability: Tian Nodes + Panel

The live simulator is designed as an experiment, so it exposes more than the final text or reconstructed image.

The logging/preview system is observational only. It does not change LoRe protocol bytes or reliability behavior.

## 1. Two observability levels

```text
TIAN A / TIAN B
    endpoint view
    encode -> queue -> TX/RX frames -> retries -> decode -> final result

PANEL
    shared-channel view
    encode -> transmit -> PASS/DROP -> response/retry -> decode
    optional full metadata
```

## 2. `[EXPRIMT]` prefix

High-level Tian experiment information uses:

```text
[EXPRIMT]
```

This is intentionally shorter than the older `[EXPERIMENT]` label.

Examples:

```text
[EXPRIMT] === TIAN ENCODING PROCESS ===
[EXPRIMT] === INITIAL TRANSMISSION ===
[EXPRIMT] === SELECTIVE RETRANSMISSION ROUND 1 ===
[EXPRIMT] === TIAN DECODING PROCESS ===
```

## 3. TX/RX lines are the authoritative per-frame view

The node terminal prioritizes:

```text
TX or RX
-> protocol command
-> protocol-specific information
-> other frame information
```

Examples:

```text
[TX] DATA index=0 total=38 message_id=0x12345678 content=IMAGE frame_bytes=198
[RX] DATA index=0 total=38 message_id=0x12345678 content=IMAGE frame_bytes=198
[TX] END round=0 message_id=0x12345678 content=IMAGE frame_bytes=18
[RX] NACK [2, 5] message_id=0x12345678 content=IMAGE frame_bytes=...
[RX] COMPLETE message_id=0x12345678 content=IMAGE frame_bytes=18
```

The node no longer prints a second duplicate `[EXPRIMT] DATA ...` row for each frame.

The transmission-window summary is still shown once before the frames:

```text
[EXPRIMT] === INITIAL TRANSMISSION ===
[EXPRIMT] message_id=0x12345678 content=IMAGE
[EXPRIMT] DATA frames=38 indexes=[0, 1, ...] all_frames=39 encoded_window=...B
[EXPRIMT] tx_delay=slow inter_frame_delay=250ms
```

## 4. Tian encoding detail

Text trace can show:

```text
content type
UTF-8 byte count
text preview
8-byte application timestamp header
application byte count
AES-GCM processing
encrypted byte count
hex previews
```

Image trace additionally shows:

```text
source path
original byte count
original dimensions
RGB thumbnail dimensions
JPEG quality 50
JPEG byte count
zlib compression
compressed byte count
AES-GCM encrypted byte count
hex previews
```

This intentionally restores the detailed experimental feel of the original Tian demo.

## 5. Tian decode detail

When the receiver reconstructs a complete payload, it shows the reverse processing path before the final message line.

Text:

```text
AES-GCM authenticated decrypt
application timestamp/header extraction
UTF-8 decode
text preview
```

Image:

```text
AES-GCM decrypt
application payload extraction
zlib decompression
JPEG byte count
image dimensions
saved output path
```

Then the final application result is printed:

```text
[MESSAGE] TEXT from=1: Hello B
```

or:

```text
[MESSAGE] IMAGE from=1 saved=... size=... jpeg=...B
```

## 6. Retransmission visibility

If a receiver sends:

```text
NACK [2,5]
```

then the sender shows a selective retry window:

```text
[EXPRIMT] === SELECTIVE RETRANSMISSION ROUND 1 ===
[EXPRIMT] DATA frames=2 indexes=[2, 5] ...
[TX] DATA index=2 ...
[TX] DATA index=5 ...
[TX] END round=1 ...
```

If a control response is lost:

```text
[TIMEOUT] no NACK/COMPLETE -> retry protocol window
[EXPRIMT] === TIMEOUT RETRY ROUND ... ===
[TX] END ...
```

## 7. Real TX delay vs scenario pacing

These are different controls.

### Real protocol-frame delay

```text
/delay normal
/delay slow
/delay very-slow
/delay 0.5
```

Current presets:

```text
normal    = 0s between protocol frames
slow      = 0.25s between protocol frames
very-slow = 1s between protocol frames
```

This slows actual DATA / END / NACK / COMPLETE transmission from that Tian process.

### Scenario action pacing

```text
/pacing normal
/pacing slow
/pacing very-slow
```

This affects time between scripted node actions/messages, not individual protocol frames.

See:

```text
docs/REAL_PACKET_DELAY.md
docs/NODE_SCENARIO_PACING.md
```

## 8. Panel DATA is streamed live

The live Panel no longer buffers all DATA until END.

With `/delay slow`, the expected visual flow is:

```text
A [TX] DATA 0
Panel PASS/DROP A->B DATA#0
B [RX] DATA 0 if passed

0.25s later

A [TX] DATA 1
Panel PASS/DROP A->B DATA#1
B [RX] DATA 1 if passed
```

END is only the sender-window boundary used by the receiver to decide whether to send NACK or COMPLETE.

This streaming behavior is important when using the simulator to understand protocol timing.

## 9. Panel concise view

The Panel always shows concise experiment information such as:

```text
[PANEL] [ENCODE] A IMAGE source=... -> encrypted=...
[PANEL] A requests channel
[PANEL] [TRANSMIT] A msg=... content=IMAGE DATA=38 indexes=[...]
[PANEL] SEQ 1 ... PASS A->B DATA#0
[PANEL] SEQ 1 ... DROP A->B DATA#5
[PANEL] SEQ 1 ... PASS A->B END
[PANEL] SEQ 1 ... PASS B->A NACK[5]
[PANEL] [DECODE] B IMAGE encrypted=... -> 240x...
```

## 10. Panel metadata commands

```text
PANEL> /metadata current
PANEL> /metadata on
PANEL> /metadata off
PANEL> /metadata status
```

### `/metadata current`

Shows the latest captured metadata once.

Use this when you normally want concise logs but occasionally want a deep snapshot.

### `/metadata on`

Automatically prints full metadata for every new sender/retry sequence.

### `/metadata off`

Stops automatic full metadata. Concise Panel logs remain active.

### `/metadata status`

Shows whether automatic metadata mode is enabled.

## 11. Full sequence metadata

A sequence metadata snapshot can contain:

```text
sequence number
sequence name
sender
message ID
content type
window kind
expected DATA indexes
configured DATA-loss rule
actual chosen DATA indexes to drop
Drop END setting
Drop NACK setting
Drop COMPLETE setting
DATA frames seen
encoded DATA bytes
```

Frame metadata can include:

```text
frame type
content type
source node ID
message ID
total packet count
packet index
payload bytes
16-byte header size
2-byte CRC size
encoded frame size
CRC-16 value
encoded frame hex preview
```

## 12. Panel scenario builder and observability

Use:

```text
PANEL> /scenario make
```

to create packet-loss/control-loss experiments in the terminal.

This is separate from Tian A/B node scenario creation.

See:

```text
docs/CHANNEL_SCENARIO_BUILDER.md
```

for the exact meaning of DATA loss, Drop END, Drop NACK and Drop COMPLETE.

## 13. Observability does not change protocol bytes

Experiment trace dictionaries are sent only over localhost simulator control messages.

They are not inserted into LoRe DATA payloads.

The actual reliable protocol remains:

```text
DATA
END
NACK
COMPLETE
```

Therefore turning metadata on changes logging volume, not the simulated RF protocol.
