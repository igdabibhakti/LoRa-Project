# Real Packet / Frame Delay

This document explains an important correction to the live Tian simulator.

## The old problem

Earlier versions exposed `/delay`, but that value only changed the timing between **scenario actions/messages**.

It did NOT slow the actual protocol-frame loop.

So even with a slow scenario you could still see:

```text
DATA #0
DATA #1
DATA #2
DATA #3
END
```

appear almost instantly.

That was confusing because the word `delay` sounded like packet delay.

## The corrected behavior

The controls are now deliberately separated:

```text
/delay  = REAL delay between transmitted protocol frames
/pacing = extra time between scenario actions/messages
```

### `/delay` — protocol transmission speed

Use this when you want to WATCH DATA packets individually.

```text
/delay normal
```

means:

```text
0 seconds between frames
```

This is the original simulator behavior and is very fast.

```text
/delay slow
```

means:

```text
0.25 seconds between frames
```

This is recommended for normal experiment observation. It is slow enough to see packet indexes progressing without making an image transfer excessively long.

```text
/delay very-slow
```

means:

```text
1 second between frames
```

This is useful for teaching, demos, screenshots, and debugging a specific retry sequence.

Custom values are supported:

```text
/delay 0.1
/delay 0.5
/delay 2
```

The number is seconds between protocol frames.

For example:

```text
/delay 0.5
```

with a transmission window containing:

```text
DATA #0
DATA #1
DATA #2
END
```

should look approximately like:

```text
t=0.0   DATA #0
t=0.5   DATA #1
t=1.0   DATA #2
t=1.5   END
```

The same pacing function is used when Tian sends a selective retransmission window such as:

```text
DATA #2
DATA #5
END
```

so `/delay 0.5` makes those frames visible at roughly half-second intervals too.

## `/pacing` — scenario action speed

Scenario pacing remains available, but it has a different command now:

```text
/pacing normal
/pacing slow
/pacing very-slow
/pacing 1.5
```

The presets are:

```text
normal     +0 seconds between scripted actions
slow       +2 seconds between scripted actions
very-slow  +5 seconds between scripted actions
```

This does NOT directly control DATA packet speed.

For example, a scenario could generate an image action and then wait before generating the next text action, while the image itself is transmitted packet-by-packet according to `/delay`.

## Example: recommended experiment setup

In Tian A:

```text
A> /delay slow
A> /pacing normal
```

In Tian B:

```text
B> /delay slow
B> /pacing normal
```

This gives:

```text
scenario actions = normal timing
protocol frames  = visible every 0.25 seconds
```

Then send an image:

```text
A> /image ~/Pictures/test.png
```

You should be able to watch:

```text
[TX] DATA index=0 ...
        0.25s
[TX] DATA index=1 ...
        0.25s
[TX] DATA index=2 ...
        0.25s
...
[TX] END ...
```

If the panel drops DATA #2 and #5, the retry should similarly show:

```text
[RX] NACK [2, 5]

[TX] DATA index=2 ...
        0.25s
[TX] DATA index=5 ...
        0.25s
[TX] END ...
```

## Why `slow` is 0.25 seconds rather than 2 seconds

A scenario message might consist of dozens or hundreds of DATA frames.

If `slow` meant two seconds per DATA frame, 100 DATA frames alone would require about 200 seconds before retries or protocol responses.

Therefore the packet-oriented presets are intentionally different from scenario-action pacing:

```text
PACKET / FRAME DELAY
normal     0s
slow       0.25s
very-slow  1s

SCENARIO ACTION PACING
normal     +0s
slow       +2s
very-slow  +5s
```

Use a custom `/delay 2` only when you explicitly want two seconds between frames.

## Status

Type:

```text
/status
```

The Tian terminal now reports both concepts separately:

```text
[STATUS] tx_delay=slow (0.25s between frames)
[SCENARIO] ... pacing=normal extra_action_delay=+0s
```

This makes it easy to confirm which timing control is currently active.
