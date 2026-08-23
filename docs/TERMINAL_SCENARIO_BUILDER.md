# Terminal-Only Tian Node Scenario Builder

This guide covers the terminal scenario-management system for the live two-Tian simulation.

The goal is simple: **normal users no longer need to open or edit JSON manually.** Each Tian terminal can list scenarios, select one, preview it, create a new one, copy/edit an old one, set action delays and scenario pacing, save a new JSON, and automatically preload that new file.

## The normal workflow

In either Tian A or Tian B:

```text
/scenario list
/scenario select 1
/scenario preview
/scenario make
```

`/protocol` is an alias for `/scenario`, so these also work:

```text
/protocol list
/protocol select 1
/protocol make
```

## 1. List available node scenarios

```text
A> /scenario list
```

Example:

```text
=== AVAILABLE NODE SCENARIOS ===
 1) Example scenario for Tian A | actions=3 | pacing=normal | simulation/scenarios/node_a_example.json
 2) Example scenario for Tian B | actions=3 | pacing=slow   | simulation/scenarios/node_b_example.json
 3) My demo scenario            | actions=4 | pacing=slow   | simulation/scenarios/nodes/my_demo.json
```

Only valid **node-action scenarios** are listed. Channel/panel JSON files are not treated as node scenarios because they do not contain `actions[]`.

## 2. Select an old scenario

By number:

```text
A> /scenario select 1
```

By filename/name/path:

```text
A> /scenario select node_a_example
```

Selecting a scenario does three things:

1. validates it,
2. preloads it into this Tian node,
3. prints a human-readable preview.

If that file contains saved pacing, the pacing is also applied automatically.

## 3. Preview the currently loaded scenario

```text
A> /scenario preview
```

Example:

```text
=== LOADED SCENARIO PREVIEW ===
Name   : Example scenario for Tian A
Pacing : normal
Actions:
   1) wait 0s -> TEXT 'Hello B'
   2) wait 2s -> IMAGE /home/user/Pictures/test.png
   3) wait 3s -> TEXT 'done'
```

No JSON syntax needs to be read.

## 4. Make a scenario entirely in the terminal

```text
A> /scenario make
```

If a scenario is already loaded, it is shown first and you are asked:

```text
Start this draft from:
1) Copy the currently loaded scenario (recommended for modifying it)
2) Start a blank scenario
3) Cancel
```

This means an old JSON acts as a template/preview. The original file is never overwritten.

The builder menu is:

```text
1) Preview draft
2) Add TEXT action
3) Add IMAGE action
4) Edit an action (including its delay)
5) Delete an action
6) Set scenario pacing
7) Rename scenario title
8) SAVE AS NEW JSON + PRELOAD IT
9) Cancel without saving
```

## 5. Add a text action

Choose:

```text
2) Add TEXT action
```

The terminal asks:

```text
Wait before this text action (seconds): 2
Text to send: Hello B
```

The builder stores the equivalent of:

```text
wait 2 seconds -> send 'Hello B'
```

You do not need to type JSON.

## 6. Add an image action

Choose:

```text
3) Add IMAGE action
```

Example prompts:

```text
Wait before this image action (seconds): 3
Image path: /home/user/Pictures/test.png
```

The builder checks that the file exists before adding it.

## 7. Edit an action and its delay

Choose:

```text
4) Edit an action
```

The current draft is displayed with numbered actions. Pick a number, then update the action delay and content/path.

Example:

```text
Action number: 2
Wait before this action (seconds) [2]: 5
Text [Hello B]: Hello B, this is the slower version
```

## 8. Two kinds of delay

There are two separate timing controls.

### Action delay

This belongs to one specific action.

Example:

```text
Action 1: wait 0s
Action 2: wait 2s
Action 3: wait 3s
```

### Scenario pacing

This is extra time added between later scripted actions for this node.

Presets:

```text
normal    = +0 seconds
slow      = +2 seconds
very-slow = +5 seconds
1.5       = custom +1.5 seconds
```

Example actions:

```text
Action 1 delay = 0s
Action 2 delay = 1s
Action 3 delay = 1s
```

With `normal`:

```text
0s -> Action 1
1s later -> Action 2
1s later -> Action 3
```

With `slow`:

```text
0s -> Action 1
3s later -> Action 2   (1s action delay + 2s pacing)
3s later -> Action 3   (1s action delay + 2s pacing)
```

This pacing changes only how fast the node scenario feeds new messages into Tian Software. It does not slow DATA/NACK/COMPLETE packets or fake LoRa airtime.

## 9. Save as a NEW JSON

Choose:

```text
8) SAVE AS NEW JSON + PRELOAD IT
```

The builder shows a final preview and asks for a filename.

Example:

```text
New filename: tian_a_demo_slow
```

It saves under:

```text
simulation/scenarios/nodes/tian_a_demo_slow.json
```

### Existing files are never overwritten

If `tian_a_demo_slow.json` already exists, the next file becomes:

```text
tian_a_demo_slow_2.json
```

then:

```text
tian_a_demo_slow_3.json
```

and so on.

This protects older experiments.

## 10. Automatic preload after save

Immediately after saving, the new file becomes the selected scenario for that Tian node.

Example output:

```text
[SAVED] New node scenario: .../simulation/scenarios/nodes/tian_a_demo_slow.json
[PRELOAD] This new scenario will now become the selected scenario for this Tian node.

=== LOADED SCENARIO PREVIEW ===
...

[SCENARIO] New file is preloaded. Type /run when ready.
```

Then simply run:

```text
A> /run
```

No `/load` is required after saving.

## 11. Change back to an older scenario

At any time:

```text
A> /scenario list
A> /scenario select 2
```

The newly selected old scenario replaces the currently preloaded scenario for future `/run` operations.

It does not modify or delete the new scenario you previously saved.

## 12. A and B are fully independent

Tian A can select/build one scenario while Tian B selects/builds another.

Example:

```text
A> /scenario select 1
B> /scenario select 3
```

Then:

```text
A> /delay normal
B> /delay slow
```

Each node has its own:

- selected scenario,
- scenario draft/editor,
- action list,
- action delays,
- pacing,
- run/pause/resume/stop state.

## 13. Saved pacing inside the generated JSON

The terminal builder still saves JSON internally so scenarios can be reused and versioned. A generated file conceptually contains:

```json
{
  "name": "Tian A demo",
  "pacing": "slow",
  "actions": [
    {
      "delay": 0,
      "type": "text",
      "text": "Hello B"
    },
    {
      "delay": 2,
      "type": "text",
      "text": "Second message"
    }
  ]
}
```

Users do not need to edit this manually.

When the scenario is selected later, its saved pacing is automatically restored.

## 14. `/delay` can temporarily change the loaded pacing

Even after selecting a scenario:

```text
A> /delay slow
```

or:

```text
A> /delay 1.5
```

The current loaded scenario playback uses that pacing.

If you want that changed pacing permanently stored as a reusable scenario, open `/scenario make`, copy the loaded scenario, choose the pacing in the builder, and save it as a new file.

## 15. Recommended beginner workflow

For a completely new scenario:

```text
/scenario make
```

Then use the numbered builder.

For modifying an old experiment:

```text
/scenario list
/scenario select 2
/scenario preview
/scenario make
```

Choose:

```text
1) Copy the currently loaded scenario
```

Edit it, save it under a new name, then:

```text
/run
```

That is the intended workflow and avoids direct JSON editing entirely.
