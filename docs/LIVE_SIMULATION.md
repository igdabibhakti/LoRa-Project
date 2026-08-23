# Live Two-Tian Interactive Simulation

This guide explains the new live simulation mode step by step. Read this file first if you want to understand how to run two interactive Tian Software instances, send text/images manually, load a separate scenario into each Tian process, and optionally apply packet-loss behavior from the channel panel.

## 1. What changed

The simulator now supports two different styles:

```text
PREDEFINED MODE
Panel loads the messages before startup.
A and B mainly execute the prepared test.

LIVE MODE
A and B stay open as interactive terminals.
You can type text, send images, and run a scenario on either side while the simulation is already running.
```

The original predefined/JSON simulator is still available. Live mode is an additional mode, not a replacement.

## 2. Live mode has THREE separate terminals

When live mode starts, three independent programs are opened:

```text
Terminal 1 = Simulation Control / Channel Monitor Panel
Terminal 2 = Tian Software A (node_id = 1)
Terminal 3 = Tian Software B (node_id = 2)
```

Think of them like this:

```text
YOU / SCENARIO                                  YOU / SCENARIO
     |                                               |
     v                                               v
+-------------+                                 +-------------+
|   TIAN A    |                                 |   TIAN B    |
+-------------+                                 +-------------+
       \                                             /
        \                                           /
         +----------- CHANNEL PANEL ---------------+
             contention + packet-loss simulation
```

The panel is NOT the chat program. It is the simulated shared LoRa medium.

## 3. Very important: there are TWO kinds of scenario

This is the most important concept in the new version.

### Node scenario

A node scenario tells one Tian process WHAT IT WANTS TO SEND.

Examples:

```text
A sends "Hello B"
wait 2 seconds
A sends an image
wait 3 seconds
A sends "done"
```

A and B can each have their own independent node scenario.

### Channel scenario

A channel scenario tells the panel WHAT HAPPENS TO THE TRANSMISSION.

Examples:

```text
Drop DATA packet #2
Drop one random packet
Drop NACK
Drop COMPLETE
use random seed 12345
```

So remember:

```text
NODE SCENARIO    = what A or B wants to send
CHANNEL SCENARIO = what the simulated radio medium does to packets
```

Do not put packet-loss settings inside a node scenario.
Do not put chat messages inside the live channel scenario.

## 4. First-time setup

From the repository directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Then start the simulator with:

```bash
./RUN_ME.sh
```

or:

```bash
python3 lore_sim.py
```

## 5. Start live mode from the menu

The menu contains:

```text
1) QUICK TEST (predefined messages)
2) LIVE INTERACTIVE A <-> B
3) Run saved JSON channel scenario
4) View / validate JSON channel scenario
5) Run included example
6) Exit
```

Choose:

```text
2
```

The launcher asks:

```text
A scenario path (Enter = manual only):
B scenario path (Enter = manual only):
```

For your first test, press Enter for both.

That means:

```text
A = manual
B = manual
Panel = clean live channel
```

Three terminals will open.

## 6. First manual text test

In Tian A type:

```text
A> Hello B
```

Normal text without a `/` command is treated as a text message.

A should show activity similar to:

```text
[QUEUE] TEXT 'Hello B' ...
[CHANNEL] requested
[CHANNEL] GRANTED ...
[TX] DATA ...
[TX] END ...
[RX] COMPLETE
[TRANSFER] COMPLETE
```

B should show something similar to:

```text
[RX] DATA ...
[RX] END ...
[TX] COMPLETE

[MESSAGE] TEXT from=1: Hello B
```

Now reply from B:

```text
B> Hello A
```

A should receive it.

At the same time, the panel terminal shows which frames passed through the simulated channel.

## 7. Send an image manually

In either Tian terminal:

```text
/image <path>
```

Example:

```text
A> /image ~/Pictures/test.png
```

or:

```text
B> /image /home/robito/Pictures/reply.jpg
```

The sender processes, encrypts, packetizes, and queues the image using the normal Tian pipeline.

The receiver reconstructs the processed image and saves it under:

```text
received/
```

Example output:

```text
[MESSAGE] IMAGE from=1 saved=... size=... jpeg=...B
```

The current image mode is still the reduced JPEG-preview transfer described in the main README; it is not byte-perfect PNG preservation.

## 8. Tian terminal commands

Both A and B support the same commands:

```text
normal text
    Send text manually.

/image <path>
    Send an image manually.

/load <file.json>
    Load a node scenario into THIS Tian process only.

/run
    Start the loaded scenario.

/pause
    Pause the currently running node scenario.

/resume
    Resume it.

/stop
    Stop scenario playback.

/scenario
    Show loaded scenario file and progress.

/status
    Show queue, transfer, channel-request and scenario status.

/help
    Print command help.

/quit
    Exit that Tian process.
```

## 9. How to create a scenario for Tian A

A node scenario is a JSON file with this shape:

```json
{
  "name": "My Tian A scenario",
  "actions": [
    {
      "delay": 0,
      "type": "text",
      "text": "Hello from A"
    },
    {
      "delay": 2,
      "type": "text",
      "text": "Second A message"
    }
  ]
}
```

The required part is:

```json
"actions": []
```

Each action must have:

```text
type = "text" or "image"
```

`delay` is optional and defaults to 0, but normally you should include it for readability.

The repository includes a ready-to-run example specifically for A:

```text
simulation/scenarios/node_a_example.json
```

## 10. How to create a scenario for Tian B

B uses exactly the same JSON format.

Example:

```json
{
  "name": "My Tian B scenario",
  "actions": [
    {
      "delay": 1,
      "type": "text",
      "text": "Hello from B"
    },
    {
      "delay": 2,
      "type": "text",
      "text": "Second B message"
    }
  ]
}
```

The repository includes:

```text
simulation/scenarios/node_b_example.json
```

A and B scenario files do NOT need to be identical.

They are independent.

## 11. What `delay` actually means

Example:

```json
{
  "delay": 3,
  "type": "text",
  "text": "hello"
}
```

means:

```text
when this action becomes the next action,
wait 3 seconds,
then place this message into the Tian outgoing queue.
```

It does NOT mean "send exactly at second 3 from the beginning of the whole simulation".

The delays are processed action by action.

Example:

```json
{
  "actions": [
    {"delay": 0, "type": "text", "text": "one"},
    {"delay": 2, "type": "text", "text": "two"},
    {"delay": 5, "type": "text", "text": "three"}
  ]
}
```

Conceptually:

```text
start
 |
 +-- immediately queue "one"
 |
 +-- wait 2 seconds
 |   queue "two"
 |
 +-- wait 5 seconds
     queue "three"
```

Channel contention may delay the ACTUAL RF-style transmission because queueing a message and winning the shared channel are separate things.

## 12. Add an image to a node scenario

Use:

```json
{
  "delay": 2,
  "type": "image",
  "path": "test.png"
}
```

Complete example:

```json
{
  "name": "A text and image test",
  "actions": [
    {
      "delay": 0,
      "type": "text",
      "text": "B, I will send an image"
    },
    {
      "delay": 2,
      "type": "image",
      "path": "test.png"
    },
    {
      "delay": 3,
      "type": "text",
      "text": "Image has been queued"
    }
  ]
}
```

### Relative image paths

If the scenario file is:

```text
/home/robito/LoRa-Project/my_scenarios/a_test.json
```

and it contains:

```json
"path": "photo.png"
```

then the program looks for:

```text
/home/robito/LoRa-Project/my_scenarios/photo.png
```

Relative image paths are resolved relative to the node scenario JSON file itself.

You may also use an absolute path:

```json
"path": "/home/robito/Pictures/photo.png"
```

## 13. Load a scenario manually into A

Start live mode with A and B manual.

Then in A:

```text
A> /load simulation/scenarios/node_a_example.json
```

Expected output:

```text
[SCENARIO] loaded 3 actions from .../node_a_example.json
```

Check it:

```text
A> /scenario
```

Then start it:

```text
A> /run
```

A will begin queueing the actions one by one.

B is still fully interactive.

You can reply manually from B while A's scenario is running.

## 14. Load a different scenario manually into B

In B:

```text
B> /load simulation/scenarios/node_b_example.json
B> /scenario
B> /run
```

Now A and B each have their own independent scenario player.

This is the important part:

```text
A scenario state != B scenario state
```

Pausing A does not pause B.
Stopping B does not stop A.
Loading a new file into A does not replace B's file.

## 15. Run BOTH node scenarios at once

Start live mode manually, then:

Tian A:

```text
A> /load simulation/scenarios/node_a_example.json
A> /run
```

Tian B:

```text
B> /load simulation/scenarios/node_b_example.json
B> /run
```

Now both sides independently generate traffic.

If they request the channel near the same time, the panel performs contention.

Example:

```text
[PANEL] A requests channel
[PANEL] B requests channel
[PANEL] contention A:63ms, B:21ms -> B wins
```

B transmits first.

After its current reliable transaction reaches delivered `COMPLETE`, the channel is released and a waiting transfer can continue.

## 16. Manual input still works while a scenario is running

This is intentional.

Example:

```text
A> /load simulation/scenarios/node_a_example.json
A> /run
```

While it runs, you may still type:

```text
A> this is a manual message during the scenario
```

The manual message enters the same Tian outgoing queue.

So one Tian terminal can generate traffic from BOTH sources:

```text
manual keyboard input
        +
scenario actions
        |
        v
same Tian outgoing queue
```

This lets you test more realistic traffic conditions.

## 17. Load node scenarios BEFORE the terminals open

The easy menu asks for optional A and B scenario paths.

Example answers:

```text
A scenario path:
simulation/scenarios/node_a_example.json

B scenario path:
simulation/scenarios/node_b_example.json
```

Then it asks:

```text
Autorun loaded scenario(s)? y/n
```

Choose `y` if you want them to start immediately.

Choose `n` if you want the files loaded but want to type `/run` manually in each Tian terminal.

## 18. Direct command-line startup with scenarios for BOTH nodes

Instead of using the menu:

```bash
python3 simulation/launch_live_terminals.py \
  --a-scenario simulation/scenarios/node_a_example.json \
  --b-scenario simulation/scenarios/node_b_example.json \
  --autorun
```

This means:

```text
Panel = default live channel
A = node_a_example.json, automatically running
B = node_b_example.json, automatically running
```

You can also script only one side:

```bash
python3 simulation/launch_live_terminals.py \
  --a-scenario simulation/scenarios/node_a_example.json \
  --autorun
```

Meaning:

```text
A = scripted
B = manual
```

Or:

```bash
python3 simulation/launch_live_terminals.py \
  --b-scenario simulation/scenarios/node_b_example.json \
  --autorun
```

Meaning:

```text
A = manual
B = scripted
```

## 19. Pause, resume and stop one node scenario

Suppose A is running a scenario.

Pause only A:

```text
A> /pause
```

Resume only A:

```text
A> /resume
```

Stop only A's scenario player:

```text
A> /stop
```

See progress:

```text
A> /scenario
```

or:

```text
A> /status
```

Note: `/stop` stops future scenario actions. Messages already placed in the Tian outgoing queue are still normal queued transfers.

## 20. Node scenario validation rules

The current parser checks these rules when `/load` is used:

```text
1. JSON must contain actions[]
2. actions must be a list
3. each action type must be "text" or "image"
4. delay must be a number >= 0
```

Examples that are invalid:

```json
{"messages": []}
```

because live node scenarios require:

```json
{"actions": []}
```

Invalid type:

```json
{"actions": [{"type": "video"}]}
```

Invalid delay:

```json
{"actions": [{"type": "text", "delay": -3, "text": "bad"}]}
```

## 21. Default live CHANNEL scenario

The default panel configuration is:

```text
simulation/scenarios/live_channel.json
```

It is a clean channel:

```json
{
  "seed": null,
  "contention_window_ms": 80,
  "max_backoff_ms": 120,
  "messages": [],
  "sequences": [
    {
      "name": "live-clean-default",
      "data_loss": {
        "mode": "none"
      }
    }
  ]
}
```

The empty `messages` list is correct in live mode because A and B generate the messages themselves.

## 22. Use node scenarios AND packet loss together

You may run:

```text
A = scripted
B = scripted
Panel = lossy channel
```

For example, make a new channel JSON:

```json
{
  "seed": 12345,
  "contention_window_ms": 80,
  "max_backoff_ms": 120,
  "messages": [],
  "sequences": [
    {
      "name": "lose-one-random-data",
      "data_loss": {
        "mode": "random_count",
        "count": 1
      }
    },
    {
      "name": "clean-retry",
      "data_loss": {
        "mode": "none"
      }
    }
  ]
}
```

Save it, for example, as:

```text
simulation/scenarios/live_loss_test.json
```

Then launch:

```bash
python3 simulation/launch_live_terminals.py \
  --panel-scenario simulation/scenarios/live_loss_test.json \
  --a-scenario simulation/scenarios/node_a_example.json \
  --b-scenario simulation/scenarios/node_b_example.json \
  --autorun
```

Now:

```text
A scenario controls A's application traffic
B scenario controls B's application traffic
live_loss_test.json controls channel faults
```

## 23. Channel sequences are GLOBAL

This behavior is important for experiments.

The panel has one chronological sequence list.

It is NOT:

```text
A has channel sequence list A
B has channel sequence list B
```

Instead:

```text
next TX window -> next panel sequence
next TX/retry window -> next panel sequence
next TX/retry window -> next panel sequence
```

regardless of which node currently owns the transaction.

So if A consumes sequence 1 and sequence 2 during retransmission, B's next transmission may begin at sequence 3.

This is separate from node scenarios, which ARE per-node.

## 24. What happens when both nodes send at nearly the same time

Both call for channel access:

```text
A ---- REQUEST_CHANNEL ----\
                            > PANEL
B ---- REQUEST_CHANNEL ----/
```

The panel waits for the configured contention window and chooses randomized backoff values.

Smallest backoff wins.

Example:

```text
A = 70 ms
B = 25 ms
B wins
```

The winner owns the reliable message transaction until delivered `COMPLETE`.

The actual direction can still switch during that transaction:

```text
B -> A : DATA
B -> A : END
A -> B : NACK (if missing)
B -> A : retransmitted DATA
B -> A : END
A -> B : COMPLETE
```

After delivered `COMPLETE`, ownership is released.

## 25. What to watch in the three terminals

### A/B Tian terminal

Useful lines:

```text
[QUEUE]
[CHANNEL] requested
[CHANNEL] GRANTED
[TX]
[RX]
[TIMEOUT]
[TRANSFER] COMPLETE
[MESSAGE]
[SCENARIO]
```

### Panel terminal

Useful lines:

```text
connected
requests channel
contention
PASS
DROP
channel released
```

Example:

```text
[PANEL] A requests channel
[PANEL] B requests channel
[PANEL] contention A:63ms, B:21ms -> B wins
[PANEL] SEQ 1 live-clean-default PASS B->A DATA#0
[PANEL] SEQ 1 live-clean-default PASS B->A END
[PANEL] SEQ 1 live-clean-default PASS A->B COMPLETE
[PANEL] channel released by B after delivered COMPLETE
```

## 26. Recommended learning/test order

Do these in order so you know which layer caused a problem.

### Test 1 - manual A -> B

```text
A> hello B
```

Verify B receives it.

### Test 2 - manual B -> A

```text
B> hello A
```

Verify A receives it.

### Test 3 - manual image

```text
A> /image <valid-image-path>
```

Verify B saves it.

### Test 4 - A scenario only

```text
A> /load simulation/scenarios/node_a_example.json
A> /run
```

Keep B manual.

### Test 5 - B scenario only

```text
B> /load simulation/scenarios/node_b_example.json
B> /run
```

### Test 6 - A and B scenarios together

Run both examples.

Watch contention.

### Test 7 - scenario + manual input

Run A's scenario, then manually type another A message during playback.

### Test 8 - scenario + packet loss

Use a custom `--panel-scenario` with DATA loss.

Verify NACK/selective retransmission.

### Test 9 - NACK or COMPLETE loss

Use a panel sequence containing `drop_nack` or `drop_complete` and verify timeout recovery.

## 27. Common mistakes

### Mistake: using the old scenario format for a node

Wrong node file:

```json
{
  "messages": [...],
  "sequences": [...]
}
```

That is a panel/predefined scenario format.

Correct node file:

```json
{
  "name": "A test",
  "actions": [...]
}
```

### Mistake: putting sender A/B in each action

You do NOT need:

```json
"sender": "A"
```

inside a node scenario.

Why?

Because the file is loaded by a specific running process.

If A loads it, all actions belong to A.
If B loads it, all actions belong to B.

### Mistake: expecting `delay` to reserve the channel

`delay` controls when the application action is queued.
It does not bypass channel contention.

### Mistake: assuming /stop deletes already queued messages

It does not.
It stops the scenario player from creating future actions.

### Mistake: relative image path points to the repository

Relative image paths are resolved from the JSON file directory, not necessarily the repository root.

## 28. Manual three-terminal launch

If the automatic terminal launcher cannot find `konsole`, `gnome-terminal`, or `xterm`, run these manually.

Terminal 1:

```bash
python3 -m simulation.panel \
  --live \
  --scenario simulation/scenarios/live_channel.json
```

Terminal 2:

```bash
python3 -m simulation.interactive_node \
  --name A \
  --id 1
```

Terminal 3:

```bash
python3 -m simulation.interactive_node \
  --name B \
  --id 2
```

Preload A:

```bash
python3 -m simulation.interactive_node \
  --name A \
  --id 1 \
  --scenario simulation/scenarios/node_a_example.json \
  --autorun
```

Preload B:

```bash
python3 -m simulation.interactive_node \
  --name B \
  --id 2 \
  --scenario simulation/scenarios/node_b_example.json \
  --autorun
```

Start the panel first so A and B have something to connect to.

## 29. Files related to this feature

```text
lore_sim.py
    Main easy menu.

simulation/launch_live_terminals.py
    Opens live panel + Tian A + Tian B.

simulation/interactive_node.py
    Live Tian process, terminal commands and per-node scenario player.

simulation/panel.py
    Shared medium, contention and fault injection; --live keeps it running.

simulation/scenarios/live_channel.json
    Default clean channel configuration.

simulation/scenarios/node_example.json
    Small generic node-scenario example.

simulation/scenarios/node_a_example.json
    Explicit example for A.

simulation/scenarios/node_b_example.json
    Explicit example for B.

received/
    Reconstructed received images.
```

## 30. Mental model to remember

If you remember only one diagram, use this one:

```text
   node_a_example.json                     node_b_example.json
          |                                      |
          v                                      v
   +-------------+                        +-------------+
   |   TIAN A    |                        |   TIAN B    |
   | manual too  |                        | manual too  |
   +-------------+                        +-------------+
          |                                      |
          +---------------+  +-------------------+
                          |  |
                          v  v
                    +-------------+
                    |    PANEL    |
                    | contention  |
                    | packet loss |
                    +-------------+
                          ^
                          |
                live_channel.json
```

In one sentence:

**A's JSON controls A, B's JSON controls B, and the panel JSON controls the simulated radio channel between them.**
