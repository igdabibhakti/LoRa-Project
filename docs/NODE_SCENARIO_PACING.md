# Per-Node Scenario Pacing (`/delay`)

Live Tian A and Tian B now each have an independent scenario pacing control.

This setting changes **only how quickly a loaded node scenario queues its next scripted action**. It does not slow down manually typed messages, LoRe packet transmission, NACK/COMPLETE timing, or the channel panel.

## Fast mental model

```text
JSON action delay + node pacing delay = wait before that scripted action
```

The first scripted action does not receive the extra pacing delay. From the second action onward, the selected node pacing is added to each action's JSON `delay`.

## Presets normal people can understand quickly

| Command | Extra pause between scripted actions | What it feels like |
| --- | ---: | --- |
| `/delay normal` | +0 seconds | Normal simulation speed. Uses the JSON delays exactly as written. |
| `/delay slow` | +2 seconds | Easy to watch. Good when a person wants to follow the terminal logs. |
| `/delay very-slow` | +5 seconds | Demo/debug speed. Plenty of time to read every step. |
| `/delay 1.5` | +1.5 seconds | Custom pacing. Any non-negative number is accepted. |

Default is:

```text
/delay normal
```

## Example: NORMAL versus SLOW

Suppose a Tian A scenario contains:

```json
{
  "name": "A three-message demo",
  "actions": [
    {"delay": 0, "type": "text", "text": "Message 1"},
    {"delay": 1, "type": "text", "text": "Message 2"},
    {"delay": 1, "type": "text", "text": "Message 3"}
  ]
}
```

### NORMAL

Run:

```text
A> /delay normal
A> /run
```

Expected scenario timing is approximately:

```text
0s   Message 1 queued
1s   Message 2 queued
2s   Message 3 queued
```

Why? `normal` adds zero seconds, so only the JSON delays are used.

### SLOW

Run:

```text
A> /delay slow
A> /run
```

Expected scenario timing is approximately:

```text
0s   Message 1 queued
3s   Message 2 queued     (JSON 1s + slow 2s)
6s   Message 3 queued     (JSON 1s + slow 2s)
```

This is usually the easiest mode for a human watching the three terminals.

### VERY SLOW

Run:

```text
A> /delay very-slow
A> /run
```

Expected scenario timing is approximately:

```text
0s   Message 1 queued
6s   Message 2 queued     (JSON 1s + 5s)
12s  Message 3 queued     (JSON 1s + 5s)
```

Use this when demonstrating packet flow to someone or reading the panel carefully.

## Check the current pacing

Type `/delay` without an argument:

```text
A> /delay
```

Example output:

```text
[DELAY] slow = +2s between scripted actions
[DELAY] examples: normal=+0s, slow=+2s, very-slow=+5s, /delay 1.5=+1.5s
```

`/scenario` and `/status` also report the active pacing setting.

## A and B are independent

You can make A run normally and B run slowly:

```text
A> /delay normal
B> /delay slow
```

This is intentional. Each Tian process owns its own scenario player.

Example:

```text
Tian A scenario pacing = normal (+0s)
Tian B scenario pacing = slow   (+2s)
```

A changing its pacing does not change B.

## Change pacing before running a scenario

Recommended workflow:

```text
A> /load simulation/scenarios/node_a_example.json
A> /delay slow
A> /scenario
A> /run
```

For B:

```text
B> /load simulation/scenarios/node_b_example.json
B> /delay normal
B> /run
```

## Change pacing while a scenario is running

The command can be changed while the node is alive. The new value is used when later actions calculate their wait time. For the most predictable demonstration, set the pacing before `/run`.

## Start with pacing from the command line

The live launcher supports separate values for A and B:

```bash
python3 simulation/launch_live_terminals.py \
  --a-scenario simulation/scenarios/node_a_example.json \
  --b-scenario simulation/scenarios/node_b_example.json \
  --a-delay normal \
  --b-delay slow \
  --autorun
```

This means:

```text
A scenario = loaded and starts at NORMAL speed
B scenario = loaded and starts at SLOW speed
```

Custom values also work:

```bash
--a-delay 1.5
--b-delay 4
```

## Easy menu behavior

When `./RUN_ME.sh` -> `LIVE INTERACTIVE A <-> B` is selected and a startup node scenario is provided, the launcher now explains the available speeds:

```text
normal    = +0 seconds between scripted actions; uses JSON delays exactly
slow      = +2 seconds between scripted actions; easy to follow by eye
very-slow = +5 seconds between scripted actions; best for demos/debugging
number    = custom extra seconds, for example 1.5
```

A and B are asked separately, so they may start at different speeds.

## Important: this is NOT radio delay

`/delay slow` does NOT mean "make every LoRa packet take 2 seconds longer."

It only affects the scenario generator:

```text
scenario action
      |
      | wait JSON delay + node pacing
      v
Tian outgoing queue
      |
      v
normal channel contention / DATA / END / NACK / COMPLETE
```

If you want to simulate propagation latency, packet loss, NACK loss, or COMPLETE loss, that belongs to the **channel/panel simulation**, not this node pacing command.

## Recommended presets

For everyday automated tests:

```text
/delay normal
```

For watching the protocol manually:

```text
/delay slow
```

For teaching, presentations, screenshots, or careful debugging:

```text
/delay very-slow
```
