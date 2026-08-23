# LoRe Project — Dynamic Tian Node Prototype

This branch builds on `feature/reliable-half-duplex-protocol` and turns Tian's
protocol into a transport-independent node runtime. The same Tian instance can
initiate reliable transfers and receive/reassemble transfers.

## What is implemented

- Reliable binary framing with CRC-16.
- `DATA`, `END`, `NACK`, and `COMPLETE` frames.
- Selective retransmission of missing DATA packets.
- Recovery from lost DATA, lost END, and lost response windows.
- `TianNode`, which can both send and receive using the same code.
- Independent receive sessions keyed by `(source_node_id, message_id)`.
- A 2-byte big-endian serial envelope for transporting encoded LoRe frames.
- An interactive serial-node runtime with packet tracing and response timeout
  handling.
- Tests for A->B, B->A, packet loss/NACK, lost END, lost COMPLETE, and serial
  framing.

## Architecture

```text
Tian application
      |
      v
TianNode
  - SenderSession
  - ReceiveSession(s)
  - DATA/END/NACK/COMPLETE
      |
      v
encoded LoRe Frame bytes
      |
      v
FramedSerialTransport
      |
      v
USB serial / future ESP32 bridge
```

The ESP32 does not need to understand images, encryption, reassembly, missing
packet decisions, or NACK generation. It only needs to move complete encoded
LoRe frames and later control the LoRa radio TX/RX state.

## Radio frame v1

All integers use network byte order (big-endian).

| Field | Bytes | Meaning |
|---|---:|---|
| Magic | 2 | `0xAA55` |
| Version | 1 | Protocol version (`1`) |
| Frame type | 1 | DATA/END/NACK/COMPLETE |
| Content type | 1 | Text/image/binary |
| Source node ID | 2 | Physical node identity |
| Message ID | 4 | Groups all packets from one message |
| Total/page count | 2 | DATA total, END expected total, or NACK page count |
| Packet/page index | 2 | DATA index, retry round, or NACK page index |
| Payload length | 1 | `0..180` |
| Payload | 0–180 | Message chunk or NACK indexes |
| CRC-16 | 2 | CRC-16/CCITT-FALSE over header + payload |

Maximum DATA frame: 198 bytes.

## Serial envelope

Serial transport adds a transport-only length prefix around each encoded LoRe
frame:

```text
+----------------------+-------------------------+
| uint16 frame length  | encoded LoRe Frame      |
| big-endian, 2 bytes  | frame_length bytes      |
+----------------------+-------------------------+
```

The prefix is not part of the radio protocol. A future ESP32 bridge should use
this same envelope on the laptop-facing USB serial link.

## Run protocol tests

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

## Run a Tian serial node

Node A:

```bash
python tian_serial_node.py --node-id 1 --port /dev/ttyUSB0
```

Node B:

```bash
python tian_serial_node.py --node-id 2 --port /dev/ttyUSB0
```

Commands:

```text
send hello from this node
status
quit
```

Example trace:

```text
TX node=1 msg=0x12345678 DATA #0/5
TX node=1 msg=0x12345678 END round=0
RX node=2 msg=0x12345678 NACK page #0/0
TX node=1 msg=0x12345678 DATA #3/5
TX node=1 msg=0x12345678 END round=1
RX node=2 msg=0x12345678 COMPLETE
```

## Current half-duplex rule

Each node is dynamically capable of sending and receiving, but two nodes should
not initiate new user transfers at exactly the same time yet. Normal protocol
turnaround is supported:

```text
A TX DATA...END -> B RX
A RX <- B TX NACK/COMPLETE
A TX retransmission...END -> B RX
```

A later channel-arbitration mechanism can resolve simultaneous initiation when
more realistic radio behavior is added.

## Next stage

Connect `FramedSerialTransport` to an ESP32 bridge. The ESP32 contract is small:

```text
laptop serial RX -> read length -> read frame -> radio_tx(frame bytes)
radio_rx(frame bytes) -> serial TX length + frame
```

This lets the reliability state machine remain in Tian while the ESP32 handles
transport and LoRa TX/RX switching.
