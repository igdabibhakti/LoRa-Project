# LoRe Project — Dynamic Both-Send Tian Software

This branch extends the reliable half-duplex protocol so **both Tian Software instances can queue and initiate messages**, while only one transfer owns the shared radio channel at a time.

Tian Software remains responsible for message/protocol work. The ESP32 remains a future transport/radio bridge.

## Architecture

```text
User/Application
  -> Tian Software
     - encode/decode
     - packetize/reassemble
     - DATA / END / NACK / COMPLETE
     - CRC validation
     - retransmission
     - outgoing queue
     - channel-request state
  -> serial_transport.py
     - [2-byte big-endian length][encoded LoRe frame]
  -> ESP32 USB serial bridge
  -> LoRa module TX/RX (half duplex)
  -> RF
  -> LoRa module
  -> ESP32 bridge
  -> serial_transport.py
  -> Tian Software
  -> User/Application
```

The simulator replaces only the ESP32/LoRa middle transport. The two Tian Software instances still run as independent programs.

## Channel arbitration

Both sides may have queued messages. If A and B request an idle channel together, the simulation panel gives each a randomized contention backoff. The smallest backoff acquires the channel; the other remains queued.

The current owner keeps the channel for the whole reliable transaction:

```text
DATA... -> END -> NACK -> retransmit -> END -> COMPLETE
```

Ownership is released only after COMPLETE is successfully delivered to the sender. A lost END, NACK, or COMPLETE therefore does not incorrectly free the channel.

Later, the simulated listen/backoff decision can be replaced by ESP32 + LoRa Channel Activity Detection/listen-before-talk without changing Tian's queue/reliability logic.

## Recommended terminal-first workflow

Everything can now be controlled from terminal without hand-editing JSON.

Start with:

```bash
python3 lore_sim.py
```

or simply:

```bash
./RUN_ME.sh
```

The menu lets you:

1. Create a scenario interactively and immediately run it.
2. Load an existing JSON scenario and run it.
3. Create/save a JSON scenario without running it.
4. Review/validate an existing JSON scenario.
5. Run the included example.

When creating a scenario, the terminal asks for messages and then for an unlimited number of sequences. Each sequence can use:

- no DATA loss;
- manual indexes such as `1,2,5`;
- random exact-count loss;
- random-probability loss;
- optional END loss;
- optional NACK loss;
- optional COMPLETE loss.

The generated JSON is saved under `simulation/scenarios/`, so a terminal-created test can be repeated later exactly. A fixed random seed reproduces the same randomized selections; a blank seed produces new randomness each run.

After configuration, the launcher opens three separate terminals:

```text
Simulation Control / Monitor Panel
Tian Software A
Tian Software B
```

The JSON method still works directly:

```bash
python3 simulation/launch_three_terminals.py --scenario simulation/scenarios/my_test.json
```

## Manual three-process simulator

You may also run each process yourself.

### Terminal 1 — Simulation control / monitor panel

```bash
python3 -m simulation.panel --scenario simulation/scenarios/example.json
```

### Terminal 2 — Tian Software A

```bash
python3 -m simulation.node_process --name A --id 1
```

### Terminal 3 — Tian Software B

```bash
python3 -m simulation.node_process --name B --id 2
```

The two Tian terminals show their own TX/RX, queue, timeout, NACK, retransmission and received-message traces. The panel shows arbitration, sequence number, selected random-loss indexes, PASS/DROP decisions, channel release and final statistics.

## Unlimited configurable loss sequences

`simulation/scenarios/example.json` contains an ordered `sequences` list. Add as many entries as you want.

Each sequence applies to **one sender TX window and the NACK/COMPLETE response caused by that window**. This means later sequences naturally control later retransmission rounds.

### No DATA loss

```json
{"name":"clean", "data_loss":{"mode":"none"}}
```

### Manual packet indexes

```json
{"name":"round 1", "data_loss":{"mode":"manual", "indexes":[1,2,5]}}
```

Example progressive test:

```text
Sequence 1: drop [1,2,5]
Sequence 2: retransmission window drops [2,5]
Sequence 3: retransmission window drops [5]
Sequence 4: clean
```

The receiver should generate successively smaller NACKs until COMPLETE.

### Random exact count

```json
{"name":"random 3", "data_loss":{"mode":"random_count", "count":3}}
```

The panel randomly chooses exactly three indexes **from the DATA packets actually present in that sequence's current TX window**.

### Random probability

```json
{"name":"random 20 percent", "data_loss":{"mode":"random_probability", "probability":0.20}}
```

Every DATA packet in that sequence has a 20% independent drop chance.

### Reproducible randomness

At the top of the scenario:

```json
"seed": 48291
```

Use the same seed to reproduce the same arbitration and random-loss choices. Set it to `null` for different choices each run.

## Control-frame fault injection

Any sequence may additionally contain:

```json
"drop_end": true,
"drop_nack": true,
"drop_complete": true
```

These can be combined with DATA loss. If END/NACK/COMPLETE is lost, the sender's response timeout causes Tian Software to retry END and continue the protocol.

## Serial contract for ESP32

`serial_transport.py` is the stable Tian Software ↔ ESP32 boundary.

```text
[uint16 big-endian frame length][encoded LoRe frame bytes]
```

Current maximum DATA frame is 198 bytes:

```text
16-byte protocol header
180-byte payload
2-byte CRC-16
```

Future ESP32 firmware should only need:

```text
Laptop USB serial RX
 -> read 2-byte frame length
 -> read exactly N frame bytes
 -> radio TX frame bytes

Radio RX frame bytes
 -> prepend 2-byte length
 -> USB serial TX
```

ESP32 does **not** need to reconstruct files, decide missing indexes, create NACKs, decrypt content, or own Tian protocol state.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The branch includes the original reliability tests plus `test_tian_software_dynamic.py` for two-way Tian Software transfer and retransmission.
