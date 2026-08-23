# LoRe Reliable Half-Duplex Protocol

This document describes the actual protocol implemented in `lore_protocol.py` on this branch.

## 1. Purpose

The protocol moves an already-prepared application payload reliably over a lossy half-duplex link.

It does not know how images are compressed, how AES-GCM works, how serial ports work, or which LoRa library is used. Those concerns are deliberately outside the protocol layer.

## 2. Constants

Current implementation:

```text
MAGIC_HEADER        0xAA55
PROTOCOL_VERSION    1
CHUNK_SIZE          180 bytes
HEADER_SIZE         16 bytes
CRC_SIZE            2 bytes
MAX DATA FRAME      198 bytes
```

CRC is CRC-16/CCITT-FALSE, implemented with an initial value of `0xFFFF`.

## 3. Frame types

```text
DATA      = 1
END       = 2
NACK      = 3
COMPLETE  = 4
```

Content types:

```text
TEXT      = 1
IMAGE     = 2
BINARY    = 3
```

## 4. Binary frame layout

The 16-byte header uses:

```text
>HBBBHIHHB
```

All multi-byte fields are big-endian.

Field layout:

```text
magic_header      uint16   2 bytes
version           uint8    1 byte
frame_type        uint8    1 byte
content_type      uint8    1 byte
source_node_id    uint16   2 bytes
message_id        uint32   4 bytes
total_packets     uint16   2 bytes
packet_index      uint16   2 bytes
payload_length    uint8    1 byte
--------------------------------
header                     16 bytes
payload                    0..180 bytes
crc16                      2 bytes
```

The CRC covers:

```text
header + payload
```

The CRC itself is appended afterward.

## 5. Meaning of shared fields

### `source_node_id`

Identifies the sender of the frame. Current A/B simulation uses IDs 1 and 2.

### `message_id`

A non-zero 32-bit identifier generated for each new outbound message unless one is explicitly supplied.

All DATA/END/NACK/COMPLETE frames for one transfer refer to the same `message_id`.

### `content_type`

Tells Tian Software whether reconstructed application bytes represent TEXT, IMAGE, or BINARY content.

## 6. DATA frame

A DATA frame carries one application chunk.

For DATA:

```text
total_packets = number of DATA frames in whole message
packet_index   = zero-based position of this chunk
payload        = up to 180 bytes
```

Example:

```text
DATA index=0 total=7
DATA index=1 total=7
...
DATA index=6 total=7
```

There are seven DATA frames total, indexes `0..6`.

The protocol supports up to 65,535 DATA frames because `total_packets` and `packet_index` are uint16.

At 180 bytes per DATA payload, the theoretical protocol chunk payload ceiling is approximately:

```text
65,535 * 180 = 11,796,300 bytes
```

This is a protocol-field limit only, not a recommendation for LoRa transfer size.

## 7. END frame

END marks the end of the sender's current transmission window.

An initial transfer is conceptually:

```text
DATA 0
DATA 1
...
DATA N
END round=0
```

After a NACK, a retransmission window is:

```text
missing DATA frames only
END round=1
```

Later retransmissions increment the END `packet_index` as the retransmission round number.

END carries no payload.

## 8. Receive session and missing detection

The receiver tracks a session by:

```text
(source_node_id, message_id)
```

It stores DATA payloads in a dictionary keyed by packet index.

When END arrives, missing indexes are computed as every index from `0` through `total_packets-1` that is not present.

Example:

```text
expected: [0,1,2,3,4,5,6]
received: [0,1,3,4,6]
missing : [2,5]
```

Receiver response:

```text
NACK [2,5]
```

## 9. Duplicate DATA handling

Receiving the same packet index again with identical payload is acceptable because assigning the same bytes to that index is harmless.

If a duplicate index arrives with different payload bytes, the receive session raises a protocol error:

```text
duplicate packet index contains different data
```

## 10. NACK format

A NACK payload contains missing packet indexes encoded as big-endian uint16 values.

Example missing list:

```text
[2, 5, 300]
```

is serialized as three uint16 values.

A single NACK payload can hold at most:

```text
180 / 2 = 90 indexes
```

because each missing index uses 2 bytes.

## 11. Multi-page NACK

If more than 90 DATA indexes are missing, the receiver splits the missing list across multiple NACK frames.

For a NACK frame:

```text
total_packets = NACK page count
packet_index   = NACK page number, zero-based
payload        = missing indexes in that page
```

Example:

```text
NACK page 0/3
NACK page 1/3
NACK page 2/3
```

The sender waits until all pages are collected before deciding which DATA frames to retransmit.

## 12. Selective retransmission

The sender does not resend the entire message after a NACK.

If the receiver sends:

```text
NACK [3,6]
```

then the next sender window is:

```text
DATA 3
DATA 6
END round=1
```

This is the main bandwidth-saving reliability mechanism.

## 13. COMPLETE

If the receiver has every DATA frame when END arrives, it sends:

```text
COMPLETE
```

COMPLETE carries no payload.

When the sender receives the matching COMPLETE, its sender session transitions to COMPLETE and the reliable message transaction is finished.

In the shared-medium simulator, a successfully delivered COMPLETE also causes channel ownership to be released.

## 14. Lost DATA example

```text
A -> B DATA 0   delivered
A -> B DATA 1   lost
A -> B DATA 2   delivered
A -> B END      delivered

B detects missing [1]
B -> A NACK [1]

A -> B DATA 1
A -> B END round=1

B now complete
B -> A COMPLETE
```

## 15. Lost END recovery

If DATA frames arrive but END is lost, the receiver does not yet know the sender is finished with that window.

The sender waits for NACK/COMPLETE. If no response arrives before the runtime timeout, Tian Software retransmits END only:

```text
TIMEOUT
-> retry END
```

The receiver can then evaluate its existing stored DATA and answer normally.

## 16. Lost NACK recovery

Example:

```text
A sends DATA, one packet missing
A sends END
B sends NACK [2]
NACK is lost
```

A receives no response and times out.

A resends END.

B still has the same receive session and still knows DATA 2 is missing, so it sends NACK [2] again.

A then retransmits DATA 2.

## 17. Lost COMPLETE recovery

If the receiver already has the whole message but COMPLETE is lost:

```text
receiver COMPLETE -> lost
sender timeout
sender retries END
receiver sees message is still complete
receiver sends COMPLETE again
```

This is why the receive session is preserved after successful reconstruction.

## 18. Sender state

`SenderState` contains:

```text
READY
WAITING_FOR_RESPONSE
COMPLETE
FAILED
```

The sender begins in READY.

After `initial_window()` it waits for a response.

A valid NACK increments the retransmission round and keeps the sender waiting.

A valid COMPLETE moves the sender to COMPLETE.

Exceeding configured retransmission rounds causes FAILED.

## 19. Retransmission limit

`SenderSession` defaults to 5 retransmission rounds when used directly.

`tian_software.py` currently constructs Tian Software with a default maximum of 20 retransmission rounds, so the integrated runtime is more permissive than the bare protocol default.

## 20. Validation rules

The implementation rejects protocol inconsistencies including:

- invalid magic header
- unsupported protocol version
- incorrect encoded frame length
- CRC mismatch
- unknown enum field values
- payload over 180 bytes
- DATA with zero total packet count
- DATA index outside total count
- END or COMPLETE with payload
- malformed odd-length NACK payload
- source ID changing during a message
- message ID changing during a message
- content type changing during a message
- total packet count changing during a message
- inconsistent DATA sequence at sender construction
- incomplete NACK page set
- NACK requesting an out-of-range DATA index

## 21. CRC and real RF corruption

Every encoded frame has CRC protection, and `Frame.decode()` raises a `ProtocolError` if corruption causes a CRC mismatch.

The unit tests verify CRC corruption detection.

However, the current live simulation runtime directly decodes incoming frames without a hardened outer error-handling policy for arbitrary malformed RF input. Before real-radio production use, malformed/corrupt frame handling should explicitly catch protocol decode errors, discard the bad frame, log it, and allow normal END/NACK recovery to request missing DATA later.

## 22. Addressing limitation

Current frames contain:

```text
source_node_id
```

but no destination-node ID.

This is sufficient for the present two-party A/B link because the medium always routes to the opposite side.

A multi-node LoRa network will need an addressing/routing design, likely including a destination ID or equivalent link-layer addressing.

## 23. Half-duplex rule

The protocol is designed around alternating windows:

```text
sender TX -> receiver RX
receiver TX response -> sender RX
sender TX retry -> receiver RX
...
```

It never requires one radio to transmit and receive simultaneously.

## 24. Protocol-level simulator

`lore_protocol.py` still includes `simulate_half_duplex_transfer()` for deterministic unit-level testing.

It can inject one-shot:

- DATA loss
- first END loss
- first response-window loss

The newer three-process simulator in `simulation/` is the higher-level tool for repeated configurable sequences and both-send contention.

## 25. Tests that exercise the protocol

`tests/test_lore_protocol.py` verifies:

- 16-byte header size
- frame round trip
- CRC corruption detection
- 180-byte payload maximum
- packet indexes beyond 255
- receiver missing detection
- selective retransmission
- DATA-loss recovery
- lost-END recovery
- lost-response recovery
- paged NACK behavior
- source consistency
- rejection of invalid simulated drop indexes

Run:

```bash
python3 -m unittest tests.test_lore_protocol -v
```
