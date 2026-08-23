# Per-Node Scenario Action Pacing (`/pacing`)

Live Tian A and Tian B each have an independent **scenario action pacing** control.

Important: this is NOT packet transmission delay.

The timing controls are now deliberately separated:

```text
/delay  = real delay between protocol frames (DATA/END/NACK/COMPLETE)
/pacing = extra delay between scripted scenario actions/messages
```

For real packet-by-packet slowing, see [`REAL_PACKET_DELAY.md`](REAL_PACKET_DELAY.md).

## Fast mental model

```text
JSON action delay + node scenario pacing = wait before that scripted action
```

The first scripted action does not receive the extra pacing delay. From the second action onward, the selected scenario pacing is added to each action's JSON `delay`.

## Presets

| Command | Extra pause between scripted actions | What it feels like |
| --- | ---: | --- |
| `/pacing normal` | +0 seconds | Uses the scenario action delays exactly as written. |
| `/pacing slow` | +2 seconds | Easier to follow the conversation/actions. |
| `/pacing very-slow` | +5 seconds | Demo/debug action pacing. |
| `/pacing 1.5` | +1.5 seconds | Custom pacing. |

Default is normally:

```text
/pacing normal
```

A scenario may also save its own `pacing` value, which is restored when that scenario is selected.

## Example

Suppose Tian A contains:

```json
{
  "name": "A three-message demo",
  "pacing": "normal",
  "actions": [
    {"delay": 0, "type": "text", "text": "Message 1"},
    {"delay": 1, "type": "text", "text": "Message 2"},
    {"delay": 1, "type": "text", "text": "Message 3"}
  ]
}
```

With:

```text
A> /pacing normal
```

approximately:

```text
0s  Message 1 queued
1s  Message 2 queued
2s  Message 3 queued
```

With:

```text
A> /pacing slow
```

approximately:

```text
0s  Message 1 queued
3s  Message 2 queued  (1s action delay + 2s pacing)
6s  Message 3 queued  (1s action delay + 2s pacing)
```

Notice that this says nothing about how quickly DATA #0, DATA #1, DATA #2 are transmitted inside each message.

To slow those actual frames, use:

```text
A> /delay slow
```

which currently means 0.25 seconds between protocol frames.

## Example combining both controls

```text
A> /pacing slow
A> /delay very-slow
```

means:

```text
Scenario actions/messages:
  +2 seconds extra between scripted actions

Inside each protocol transmission window:
  1 second between DATA/END/etc. frames sent by this Tian node
```

These are independent.

## Check current values

```text
A> /pacing
```

shows scenario action pacing.

```text
A> /delay
```

shows real transmission frame delay.

```text
A> /status
```

shows both.

## A and B are independent

Example:

```text
A> /pacing normal
A> /delay slow

B> /pacing very-slow
B> /delay normal
```

A can therefore generate scenario actions normally while showing its packets slowly, while B can generate actions very slowly but emit its own frames at normal simulator speed.

## Scenario builder

The terminal scenario builder still stores a scenario-level `pacing` field.

Use:

```text
/scenario make
```

then choose the pacing menu option. This controls scenario-action timing only.

Real per-frame transmission delay remains a live Tian runtime control (`/delay`) and is intentionally separate from the saved scenario action timing.
