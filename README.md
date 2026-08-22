# LoRe Project — Reliable Protocol Prototype

This branch improves Tian's original image/text prototype before adding the
laptop-to-ESP32 USB link. It still simulates the radio, but the data exchanged
by that simulator is now the same binary framing that the future transport can
carry.

## What changed

- Fixed the old packet-index mismatch. The comment claimed a 16-bit index but
  `>HBHBB` encoded only 8 bits. Packet indexes are now genuinely 16-bit.
- Added a random 32-bit message ID so packets from different messages are not
  mixed together.
- Added protocol version, source node ID, frame type, content type, and CRC-16.
- Added explicit `DATA`, `END`, `NACK`, and `COMPLETE` frames.
- Added paged NACKs when more than 90 packet indexes are missing.
- Added sender and receiver sessions that cache, validate, reassemble, and
  selectively retransmit packets.
- Added a deterministic half-duplex simulator with optional DATA, END, and
  response loss.
- Put the interactive program behind `main()` so the protocol can be imported
  later by serial/ESP32 code.
- Store the send timestamp once per encrypted message instead of repeating it
  in every radio packet.
- Preserve image aspect ratio when creating the 480-pixel preview.

## Half-duplex transfer

Only one side owns the radio during a window:

1. Sender TX / receiver RX: `DATA 0 ... DATA N, END`.
2. Both switch direction.
3. Receiver TX / sender RX: one or more `NACK` pages, or `COMPLETE`.
4. If NACKed, the sender retransmits only the requested DATA packets followed
   by another `END`.
5. If `END` or the response is lost, the sender times out and repeats `END`.

There is never a requirement for either LoRa module to transmit and receive at
the same time.

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
| Payload length | 1 | `0..180` for current DATA frames |
| Payload | 0–180 | Encrypted message chunk or NACK indexes |
| CRC-16 | 2 | CRC-16/CCITT-FALSE over header + payload |

The maximum current DATA frame is 198 bytes: 16-byte header, 180-byte payload,
and 2-byte CRC. That leaves room below a 255-byte LoRa packet limit.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python lora_demo.py
```

When prompted for simulated loss, enter zero-based DATA indexes such as `3,6`.
The demo will show the TX/RX windows, NACK, retransmission, and COMPLETE.

Run the tests with:

```bash
python -m unittest discover -s tests -v
```

## Next stage: ESP32 link

The future USB serial module should exchange encoded `Frame` bytes and wait for
ESP32 `TX_DONE` before submitting the next radio frame. The ESP32 does not need
to understand JPEG, zlib, AES-GCM, reassembly, or NACK decisions. Its eventual
radio-facing seam is intentionally small:

```text
laptop serial RX -> validate serial envelope -> radio_tx(frame bytes)
radio_rx(frame bytes, RSSI, SNR) -> serial TX -> laptop
```

The serial envelope itself is intentionally not implemented in this stage; it
will be added and loopback-tested before real LoRa code.
