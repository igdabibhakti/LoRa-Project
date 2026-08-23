# LoRe Project — Dynamic Both-Send Tian Software

This branch implements reliable half-duplex Tian Software with two independent Tian Software processes, channel contention, queued sending, configurable packet/control-frame loss, and a serial-ready ESP32 boundary.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 lore_sim.py
```

Choose **Quick Test**.

## Quick Test payloads

For each sender, choose:

```text
1) Text
2) Image
```

Text is encoded as UTF-8, timestamped, AES-GCM encrypted, packetized, transferred, reassembled, decrypted and printed once at the receiver.

Image follows Tian's earlier image path:

```text
image -> RGB -> thumbnail up to 240x240 -> JPEG Q50 -> zlib -> timestamp -> AES-GCM -> LoRe packets
```

The receiver reassembles, decrypts, decompresses, and saves the restored JPEG under `received/`.

## Loss sequence syntax

```text
1,2,5 | 2,5 | random:1 | 20% | none+nack | none
```

Each `|` is the next TX/retransmission sequence.

- `1,2,5` = drop zero-based DATA packet indexes 1, 2, 5
- `random:2` = drop exactly 2 random DATA packets from that TX window
- `20%` = independent 20% DATA loss probability
- `none` = clean DATA window
- `+end` = also drop END
- `+nack` = also drop NACK
- `+complete` = also drop COMPLETE

Packet trace uses explicit zero-based indexing, for example:

```text
DATA index=6 total=7
```

## Three-process simulation

Quick Test opens:

1. Simulation control/monitor panel
2. Tian Software A terminal
3. Tian Software B terminal

If both send at once, both request the channel. Randomized backoff chooses the first channel owner. The other remains queued until the current `DATA -> END -> NACK/retry -> COMPLETE` transaction finishes.

## ESP32 pipeline

```text
Text/Image
  -> Tian payload encode/compress/encrypt
  -> Tian reliable protocol (DATA/END/NACK/COMPLETE)
  -> serial_transport.py
  -> [2-byte big-endian frame length][encoded LoRe frame]
  -> ESP32
  -> LoRa TX/RX
  -> RF
  -> ESP32
  -> serial_transport.py
  -> Tian reliable reassembly
  -> Tian decrypt/decode/restore
```

The ESP32 does not need to understand image compression, encryption, missing-packet calculation, NACK construction, or message reconstruction. It only transports encoded LoRe frames.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Current tests include two-way reliable transfer plus Tian text and image payload round trips.
