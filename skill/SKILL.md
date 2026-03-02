---
name: bridge-watcher
description: Watch the bridge for remote commands from Telegram and execute them. Start with "Watch the bridge for remote commands", "start ag-bridge", "start the bridge", or "start the bridge for remote work". Stop with "stop ag-bridge", "stop the bridge", or "disconnect the bridge".
---

# Bridge Watcher

## Overview

This skill turns your Antigravity session into a remote command processor.
It connects to the Telegram bridge bot via a Unix domain socket and waits
for commands sent from your phone via Telegram.

## Context Economy (MANDATORY)

> Every token in this conversation is finite. The bridge must survive for hours
> and dozens of commands. These rules are non-negotiable.

### Watch Loop Rules

- **`WaitDurationSeconds=300`** on every `command_status` poll (returns early when a command arrives)
- **`OutputCharacterCount=500`** on every `command_status` poll
- **ZERO text output** when no command is found — immediately poll again with no commentary
- **Never re-read** this skill file, config files, or any reference docs after initial setup

### Command Execution Rules

- **Cap all tool outputs** — use the smallest reasonable `OutputCharacterCount` and line ranges
- **No reasoning narration** — don't explain what you're about to do, just do it
- **No acknowledgment** — don't say "I received a command to..." — execute immediately
- **Terse Telegram results** — 1-3 sentences max, summarize don't echo raw output

### DO NOT (Context Waste)

- DO NOT produce any text response when no command is found in a poll
- DO NOT re-read SKILL.md, config.json, or reference docs mid-session
- DO NOT echo the command prompt back before executing it
- DO NOT narrate your plan or reasoning process during execution
- DO NOT include raw tool output in Telegram result summaries — always summarize
- DO NOT print status messages like "Checking for commands..." or "No command found"

## Prerequisites

- The bridge bot must already be running in a separate terminal: `ag-bridge start`
- Config must exist at `~/.ag-bridge/config.json` with valid bot_token and chat IDs

## Startup Procedure

**Step 1: Start the bridge client as a background command.**

```
run_command: python3 scripts/bridge_client.py
```

Use `WaitMsBeforeAsync=2000` to capture initial connection output.

**Step 2: Verify connection.**

Check `command_status` for the bridge client process.

Expected output:

```
[bridge] Connecting to ~/.ag-bridge/bridge.sock...
[bridge] Connected.
[bridge] Session started for workspace: /path/to/workspace
[bridge] Waiting for command...
```

If you see `ERROR: Cannot connect`, the bot is not running. **Tell the user:**

> ⚠️ Bot is not running. Please start it in a separate terminal: `ag-bridge start`

Do NOT attempt to start the bot yourself — this wastes context tokens.

**Step 3: Enter the watch loop.**

## Watch Loop

Repeat these steps indefinitely until the user says stop or sends `/stop` from Telegram:

### 1. Check for commands

Call `command_status` on the bridge client process with `WaitDurationSeconds=300` and `OutputCharacterCount=500`.
Look for lines containing `[COMMAND]` in the output.

### 2. If no command found

The `command_status` call will return after up to 5 minutes if no command arrives (it returns early when one does).
Produce **zero text output**. Immediately loop back to step 1 with no commentary.

### 3. If command found

Parse the JSON string that follows the `[COMMAND]` tag on that line.

Example:

```
[COMMAND]{"type":"command","id":"abc123","prompt":"Run tests","chat_id":123456,"ts":1709272800}
```

Extract:

- `id` — the command ID (needed for the result)
- `prompt` — what the user wants you to do

### 4. Check for stop command

If the `prompt` is `/stop`, `stop`, or `disconnect`:

- Follow the **Shutdown Procedure** below.
- Do NOT execute it as a normal prompt.

### 5. Execute the prompt

**Treat the prompt as if the user typed it directly into this Antigravity session.**

Use ALL available tools as needed:

- `run_command` for terminal commands
- `view_file`, `write_to_file` for file operations
- `grep_search`, `find_by_name` for searching
- `view_file_outline` for code exploration
- Any other tool that helps fulfill the request

Do whatever the prompt asks, using your full capabilities.

### 6. Compose and send the result

Compose a **1-3 sentence** summary. Summarize, don't echo raw output. Include:

- The outcome (success/failure)
- Key finding or result (if any)

Send the result back using `send_command_input` on the bridge client process:

```json
{"type":"result","id":"<command_id>","status":"success","summary":"<your summary here>","ts":<current_timestamp>}
```

**Important:**

- Send as a **single line** (no line breaks within the JSON)
- Include a newline character at the end
- Use the same `id` from the command
- Set `status` to `"success"` or `"error"`

### 7. Loop

Go back to step 1. Continue watching for the next command.

## Error Handling

- If a command fails or errors out, send a result with `"status": "error"`
  and describe the error in `summary`
- If the bridge client process dies, restart it (go back to Startup step 1)
- If the bot is not running, tell the user to start it manually: `ag-bridge start`

## Shutdown Procedure

Triggered when the user says "stop ag-bridge", "stop the bridge", or "disconnect the bridge"
in the Antigravity chat, OR when a `/stop` command is received from Telegram.

**Step 1: Send a goodbye result (if triggered from Telegram).**

If the stop was received as a Telegram command, send a result back first:

```json
{"type":"result","id":"<command_id>","status":"success","summary":"🔴 Bridge session ended. Goodbye!","ts":<current_timestamp>}
```

**Step 2: Terminate the bridge client.**

Use `send_command_input` with `Terminate: true` on the bridge client process.

The bot continues running in the user's terminal — do NOT attempt to terminate it.

**Step 3: Confirm to the user.**

Report to the user in the Antigravity chat:

> 🔴 Bridge disconnected. Client process terminated. Bot is still running in your terminal.

## Example Session

User starts Antigravity in a dedicated IDE tab and says:

> "Watch the bridge for remote commands"

Antigravity follows this skill:

1. Starts `bridge_client.py` as background process
2. Verifies connection succeeded
3. Enters watch loop, waiting for commands...
4. User sends **"What files changed today?"** via Telegram
5. Antigravity runs `git log --oneline --since="today"` and summarizes the changes
6. Sends result back → user sees it on Telegram
7. Goes back to waiting for next command
