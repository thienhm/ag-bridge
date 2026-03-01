---
name: bridge-watcher
description: Watch the bridge for remote commands from Telegram and execute them. Start with "Watch the bridge for remote commands", "start ag-bridge", "start the bridge", or "start the bridge for remote work". Stop with "stop ag-bridge", "stop the bridge", or "disconnect the bridge".
---

# Bridge Watcher

## Overview

This skill turns your Antigravity session into a remote command processor.
It connects to the Telegram bridge bot via a Unix domain socket and waits
for commands sent from your phone via Telegram.

## Prerequisites

- The bridge bot must be running: `python3 ~/.ag-bridge/bot.py`
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

If you see `ERROR: Cannot connect`, the bot is not running. **Auto-start it:**

1. Start the bot as a background command:

   ```
   run_command: python3 ~/.ag-bridge/bot.py
   ```

   Use `WaitMsBeforeAsync=3000` to capture startup output.

2. Check `command_status` to verify the bot started successfully. Look for:

   ```
   Starting Telegram bridge bot...
   Socket server listening at ~/.ag-bridge/bridge.sock
   ```

3. Retry Step 1 — start the bridge client again and verify connection.

**Step 3: Enter the watch loop.**

## Watch Loop

Repeat these steps indefinitely until the user says stop or sends `/stop` from Telegram:

### 1. Check for commands

Call `command_status` on the bridge client process with `WaitDurationSeconds=30`.
Look for lines containing `[COMMAND]` in the output.

### 2. If no command found

The `command_status` call will return after 30 seconds if no command arrives.
Simply check again — loop back to step 1.

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

After completing the task, compose a concise summary of:

- What you did
- The outcome (success/failure)
- Any important output or findings

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
- If the bot is not running, auto-start it: `python3 ~/.ag-bridge/bot.py`
  as a background command, then retry the bridge client

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

**Step 3: Terminate the bot (if auto-started).**

If the bot was auto-started during Startup Step 2, terminate it as well using
`send_command_input` with `Terminate: true` on the bot process.

If the bot was already running before this session, leave it running.

**Step 4: Confirm to the user.**

Report to the user in the Antigravity chat:

> 🔴 Bridge disconnected. Bot and client processes terminated.

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
