# Live Two-Tian Interactive Simulation

This mode runs **three independent terminal processes** and keeps them open for interactive use:

```text
Terminal 1  Simulation Control / Channel Monitor Panel
Terminal 2  Tian Software A
Terminal 3  Tian Software B
```

Unlike the original predefined simulation, messages do not have to be placed in the panel scenario before startup. Tian A and Tian B can send text and images while the program is already running.

The existing predefined/JSON simulation remains available and is not replaced by this mode.

## Start it

Recommended:

```bash
./RUN_ME.sh
```

Then choose:

```text
2) LIVE INTERACTIVE A <-> B
```

The launcher optionally asks for a startup node scenario for A and/or B. Press Enter for a fully manual node.

You can also launch live mode directly:

```bash
python3 simulation/launch_live_terminals.py
```

With optional per-node scenarios:

```bash
python3 simulation/launch_live_terminals.py \
  --a-scenario simulation/scenarios/node_example.json \
  --b-scenario simulation/scenarios/node_example.json \
  --autorun
```

## Tian terminal commands

Both A and B use the same commands.

```text
normal text
    Queue and send a text message.

/image <path>
    Process, queue, and send an image.

/load <file.json>
    Load a node action scenario into this Tian process.

/run
    Start the loaded node scenario.

/pause
    Pause the loaded node scenario.

/resume
    Resume the loaded node scenario.

/stop
    Stop scenario playback.

/scenario
    Show loaded scenario and progress.

/status
    Show queue / transfer / scenario status.

/help
    Show command help.

/quit
    Exit this Tian process.
```

Example manual conversation:

```text
A> Hello B
```

B receives the reconstructed text and may immediately reply:

```text
B> Hello A, received!
```

Image example:

```text
A> /image ~/Pictures/test.png
```

The receiver saves the processed/reconstructed image under `received/` exactly like the existing Tian image simulation path.

## Two different scenario concepts

Live mode deliberately separates **what a Tian user wants to send** from **what happens to the simulated radio channel**.

### 1. Node scenario

A node scenario belongs to Tian A or Tian B. It describes application actions such as sending text or an image.

Example:

```json
{
  "name": "A scripted sender",
  "actions": [
    {
      "delay": 0,
      "type": "text",
      "text": "Hello from A"
    },
    {
      "delay": 2,
      "type": "image",
      "path": "test.png"
    },
    {
      "delay": 3,
      "type": "text",
      "text": "Image queued"
    }
  ]
}
```

`delay` is the number of seconds to wait **after the previous action becomes current** before enqueueing that action.

Relative image paths are resolved relative to the node scenario JSON file.

The included example is:

```text
simulation/scenarios/node_example.json
```

### 2. Panel / channel scenario

The panel scenario describes the simulated shared medium: contention timing, random seed, DATA loss, END loss, NACK loss, and COMPLETE loss.

Live mode defaults to:

```text
simulation/scenarios/live_channel.json
```

Its default is a clean channel. Existing sequence behavior is still used by the live panel, so a custom channel scenario can inject loss while the users type interactively.

This means a useful test can be:

```text
Tian A
  human/manual input

Tian B
  scripted node actions

Panel
  packet-loss scenario
```

or any other combination.

## Manual + scenario input can coexist

Loading or running a node scenario does **not** disable terminal input.

For example, A can run a scripted sequence while you manually type another message:

```text
A> /load simulation/scenarios/node_example.json
A> /run
[SCENARIO] TEXT 'Hello from loaded node scenario'

A> manual message while scenario is active
```

Both messages enter the normal Tian outgoing queue and compete for the same simulated half-duplex channel as every other transfer.

## Simultaneous A/B sending

If A and B both queue messages near the same time, both request the channel. The existing panel contention logic chooses a winner using randomized backoff.

Conceptually:

```text
A requests channel ----\
                       > Panel contention -> one winner
B requests channel ----/
```

The winner owns the current reliable message transaction until the receiver's `COMPLETE` is successfully delivered.

During that transaction the direction still switches as required by the half-duplex protocol:

```text
Sender -> Receiver : DATA / END
Receiver -> Sender : NACK
Sender -> Receiver : missing DATA / END
Receiver -> Sender : COMPLETE
```

After `COMPLETE`, the channel is released. Any waiting Tian process remains eligible to transmit next.

## What the panel shows

The panel remains a monitor and simulated medium. It is not the chat UI.

Typical output:

```text
[PANEL] A requests channel
[PANEL] B requests channel
[PANEL] contention A:63ms, B:21ms -> B wins
[PANEL] SEQ 1 live-clean-default PASS B->A DATA#0
[PANEL] SEQ 1 live-clean-default PASS B->A END
[PANEL] SEQ 1 live-clean-default PASS A->B COMPLETE
[PANEL] channel released by B after delivered COMPLETE
```

This lets you interact with the two Tian terminals while watching packet-level activity separately.

## Architecture

```text
       Tian A terminal                  Tian B terminal
   manual text / images             manual text / images
   optional node scenario           optional node scenario
             |                               |
             v                               v
       TianSoftware A                   TianSoftware B
             |                               |
             +------------+ +----------------+
                          | |
                          v v
                 Simulation Panel
             arbitration + fault injection
                          |
                 simulated half-duplex
```

The live mode reuses the existing Tian reliability implementation. It does not create a second DATA/END/NACK/COMPLETE protocol.

## Files added/changed for live mode

```text
simulation/interactive_node.py
    Interactive Tian A/B process, terminal commands, node scenario playback.

simulation/launch_live_terminals.py
    Opens Panel + A + B in separate terminal windows.

simulation/panel.py
    Adds --live mode so the panel stays running and does not preload/finish after a fixed message list.

simulation/scenarios/live_channel.json
    Default clean live channel configuration.

simulation/scenarios/node_example.json
    Example per-node action scenario.

lore_sim.py
    Adds LIVE INTERACTIVE A <-> B to the easy menu.
```

## Important current behavior

- Live mode still assumes exactly two parties: A and B.
- Tian frame format still has a source node ID but no explicit destination ID.
- Node scenarios generate application messages; panel scenarios generate channel conditions.
- Scenario actions and manually typed messages use the same Tian outgoing queue.
- Images still use the current processed JPEG-preview pipeline documented in the main README; this is not exact PNG byte preservation.
- If configured panel loss sequences run out, later TX windows fall back to clean `default-N` sequences.
- Closing one Tian terminal removes it from the live panel; frames cannot be delivered to a disconnected peer.

## Suggested tests

### Manual -> manual

Type text in A, verify B receives it, then reply from B.

### Image -> manual

Use `/image <path>` in A and verify B reconstructs/saves it.

### Scripted -> manual

Load `node_example.json` in A, run it, and manually reply from B.

### Scripted -> scripted

Start both A and B with node scenarios and `--autorun`; watch contention in the panel.

### Mixed contention

Run an A scenario and manually type in B at nearly the same time. Verify one wins, completes, releases the channel, and the waiting transfer follows.

### Fault injection

Launch the live panel with a custom channel scenario containing DATA/NACK/COMPLETE loss and verify the same retransmission and timeout behavior used by the predefined simulator.
