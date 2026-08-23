# Experiment Observability: Tian Nodes + Panel

This simulator is an experiment, so the live mode now shows more than the final text or reconstructed image.

The observability design has two levels:

```text
TIAN A / TIAN B
    detailed endpoint view
    encode -> queue -> channel -> frames -> retries -> decode -> result

PANEL
    central experiment view
    encode -> transmit -> packet loss/retry -> decode
    optional full metadata dump
```

The reliability protocol itself is unchanged by these logs. The trace information is observational only.

## 1. What each Tian node now shows

When A or B sends text/image, it prints the Tian application processing first.

Text example:

```text
[EXPERIMENT] === TIAN ENCODING PROCESS ===
[EXPERIMENT] direction: ENCODE
[EXPERIMENT] content_type: TEXT
[EXPERIMENT] raw_bytes: 7
[EXPERIMENT] raw_preview: Hello B
[EXPERIMENT] application_header_bytes: 8
[EXPERIMENT] encryption: AES-GCM (12B nonce + cipher + 16B tag)
[EXPERIMENT] encrypted_bytes: ...
[EXPERIMENT] raw_hex: ...
[EXPERIMENT] encrypted_hex: ...
```

Image processing additionally shows values such as:

```text
original file size
original dimensions
RGB thumbnail dimensions
JPEG quality 50
JPEG byte count
zlib compressed byte count
AES-GCM encrypted byte count
hex previews of important processing stages
```

This intentionally resembles the original Tian demo, which exposed image compression, encryption, hex data, and final decode steps.

## 2. Transmission detail on each Tian node

After the node obtains the channel, it prints a transmission-window summary.

Example:

```text
[EXPERIMENT] === INITIAL TRANSMISSION ===
[EXPERIMENT] message_id=0x12345678 content=IMAGE
[EXPERIMENT] DATA frames=7 indexes=[0, 1, 2, 3, 4, 5, 6] all_frames=8 encoded_window=...B
[EXPERIMENT] DATA index=0/7 frame=198B payload=180B header=16B crc=0x....
...
[EXPERIMENT] END frame=18B payload=0B header=16B crc=0x....
```

Individual TX/RX lines also contain experiment identifiers:

```text
[TX] DATA index=0 total=7 message_id=0x12345678 content=IMAGE frame_bytes=198
[RX] NACK [2, 5] message_id=0x12345678 content=IMAGE frame_bytes=...
```

This makes it easier to connect a user-level text/image with the actual protocol frames.

## 3. Retransmission visibility

If a NACK requests missing DATA packets, the sender prints a new window:

```text
[EXPERIMENT] === SELECTIVE RETRANSMISSION ROUND 1 ===
[EXPERIMENT] DATA frames=2 indexes=[2, 5]
...
```

If NACK/COMPLETE is lost and a timeout happens:

```text
[TIMEOUT] no NACK/COMPLETE -> retry protocol window
[EXPERIMENT] === TIMEOUT RETRY ROUND 2 ===
...
```

So the node terminal can be used to study exactly which packets were sent initially and which packets were resent.

## 4. Decode detail on receiver

When a full message is reconstructed, the receiver shows the decode process before printing the final message.

Text example:

```text
[EXPERIMENT] === TIAN DECODING PROCESS ===
[EXPERIMENT] content_type: TEXT
[EXPERIMENT] encrypted_bytes: ...
[EXPERIMENT] decryption: AES-GCM authenticated decrypt
[EXPERIMENT] application_header_bytes: 8
[EXPERIMENT] result: UTF-8 text
[EXPERIMENT] text_preview: Hello B

[MESSAGE] TEXT from=1: Hello B
```

Image example also shows:

```text
AES-GCM decrypt
application payload extraction
zlib -> JPEG decompression
JPEG byte count
final dimensions
saved output path
```

## 5. Panel always shows concise ENCODE -> TRANSMIT -> DECODE

The panel remains the central packet/channel monitor, but it now also receives observational traces from A and B.

Typical output:

```text
[PANEL] [ENCODE] A TEXT source=7B -> encrypted=43B 'Hello B'
[PANEL] A requests channel
[PANEL] [TRANSMIT] A msg=0x12345678 content=TEXT DATA=1 indexes=[0] window=...B
[PANEL] SEQ 1 live-clean-default PASS A->B DATA#0
[PANEL] SEQ 1 live-clean-default PASS A->B END
[PANEL] SEQ 1 live-clean-default PASS B->A COMPLETE
[PANEL] [DECODE] B TEXT encrypted=43B -> Hello B
```

This concise view stays enabled even when full metadata mode is OFF.

## 6. Panel metadata commands

Type commands directly into the PANEL terminal.

### Show the latest snapshot once

```text
PANEL> /metadata current
```

This prints the most recently captured metadata without enabling continuous metadata spam.

Use this when you normally want a clean panel but occasionally want to inspect the latest transfer deeply.

Aliases accepted by the implementation include `now` and `preview`.

### Automatically preview metadata for every sequence

```text
PANEL> /metadata on
```

Now every DATA/END TX or retransmission window prints its full sequence metadata automatically.

This mode is useful for an experiment where every retry window must be recorded and visually inspected.

### Turn automatic metadata back off

```text
PANEL> /metadata off
```

Concise ENCODE / TRANSMIT / DECODE and PASS/DROP logs remain visible.

### Check mode

```text
PANEL> /metadata status
```

### Show panel commands

```text
PANEL> /help
```

## 7. What full sequence metadata contains

For each TX/retry sequence the panel can show:

```text
sequence number
sequence name
sender
message ID
content type
configured DATA-loss rule
actual chosen DATA indexes to drop
drop_end
drop_nack
drop_complete
number of DATA frames
encoded DATA bytes
```

Each DATA frame also includes:

```text
frame type
content type
source node ID
message ID
total packet count
packet index
payload byte count
protocol header byte count
CRC byte count
encoded frame byte count
CRC-16 value
hex preview of the encoded frame
```

## 8. `current` versus `on`

The intended distinction is simple:

```text
/metadata current
    show the latest metadata ONCE
    then return to concise normal display

/metadata on
    automatically show metadata on EVERY new TX/retry sequence
    keep doing this until /metadata off
```

For a normal interactive test, start with metadata OFF.

For example:

```text
A sends image
panel shows normal packet flow
PANEL> /metadata current
inspect the latest image-transfer metadata
continue normally
```

For a formal experiment where every retry sequence matters:

```text
PANEL> /metadata on
```

before starting A/B scenarios.

## 9. Relationship to node scenario delay/pacing

Scenario timing and metadata are independent.

For example:

```text
A> /delay slow
```

makes A's scenario easier to watch by adding +2 seconds between actions.

Meanwhile:

```text
PANEL> /metadata on
```

makes the panel print full metadata for each actual protocol TX/retry sequence.

A useful teaching/debugging setup is therefore:

```text
A pacing = slow
B pacing = slow
Panel metadata = on
```

This gives enough time to read encode, arbitration, packet, retry, and decode information as it happens.

## 10. Important: observability does not change protocol bytes

The codec trace dictionaries and experiment displays are not embedded into LoRe DATA frames.

They travel only through the localhost simulation control connection so the panel can display them.

The actual reliable protocol still sends the normal encoded LoRe frames:

```text
DATA
END
NACK
COMPLETE
```

This distinction matters when interpreting experiment results: enabling metadata display changes logging volume, not the simulated radio protocol.
