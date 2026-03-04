# 🤖 ag-bridge

> Control [Antigravity](https://blog.google/technology/google-deepmind/) remotely via Telegram.

**ag-bridge** is a lightweight Telegram bot that bridges your phone to Antigravity IDE using Chrome DevTools Protocol (CDP). Send any prompt from Telegram and get results back — like having your AI pair programmer in your pocket.

## How It Works

```
┌──────────────┐              ┌──────────────────────────────┐
│  Your Phone  │   Telegram   │          bot.py              │
│  (Telegram)  │ ◄──────────► │                              │
└──────────────┘              │  ┌────────────┐ ┌─────────┐ │
                              │  │ cdp_bridge │ │callback_ │ │
                              │  │   .py      │ │server.py │ │
                              │  └─────┬──────┘ └────▲────┘ │
                              └────────┼─────────────┼──────┘
                                       │             │
                              CDP inject prompt   curl result
                              localhost:9222     localhost:3001
                                       │             │
                                       ▼             │
                              ┌──────────────────────┴───────┐
                              │       Antigravity IDE         │
                              └──────────────────────────────┘
```

1. You send a message to your Telegram bot
2. The bot injects it into Antigravity's chat via CDP
3. Antigravity executes the prompt with full tool access
4. The agent curls the result back to the bot's HTTP server
5. The result is sent back to you on Telegram

## Prerequisites

- **macOS** with Python 3.9+
- **Antigravity** launched with `--remote-debugging-port=9222`
- **Telegram account** + bot created via [@BotFather](https://t.me/BotFather)

## Installation

### 1. Clone this repo

```bash
git clone https://github.com/thienhm/ag-bridge.git
```

### 2. Install dependencies

```bash
pip3 install -r ag-bridge/requirements.txt
```

### 3. Add `ag-bridge` to your PATH

Add to your `~/.zshrc` (adjust the path to where you cloned):

```bash
export AG_BRIDGE_HOME="/path/to/ag-bridge"
export PATH="$AG_BRIDGE_HOME:$PATH"
```

### 4. Set up your bot

```bash
ag-bridge onboard
```

This walks you through creating a Telegram bot and configuring ports.

> **Already configured?** Use `ag-bridge configure` to update settings.

## Usage

### 1. Launch Antigravity with CDP

```bash
/Applications/Antigravity.app/Contents/MacOS/Antigravity --remote-debugging-port=9222
```

### 2. Start the bot

```bash
ag-bridge start
```

### 3. Send commands from Telegram

Just message your bot like you would in the IDE:

- "Run the tests"
- "What files changed today?"
- "Fix the lint errors in utils.py"
- "Create a new feature branch for login"

The bot injects your prompt directly into Antigravity — no special setup per workspace needed.

### Bot commands

| Command   | Description                             |
| --------- | --------------------------------------- |
| `/status` | Check if Antigravity is reachable (CDP) |
| `/help`   | Show available commands                 |

## Architecture

| Component           | File                 | Purpose                          |
| ------------------- | -------------------- | -------------------------------- |
| **Bot**             | `bot.py`             | Telegram bot + orchestration     |
| **CDP Bridge**      | `cdp_bridge.py`      | CDP target discovery + injection |
| **Callback Server** | `callback_server.py` | HTTP server for agent results    |
| **CLI**             | `ag-bridge`          | Setup and management CLI         |

## Limitations

- **One command at a time** — commands are processed sequentially
- **Requires CDP flag** — Antigravity must be launched with `--remote-debugging-port=9222`
- **Text responses only** — no file attachments or screenshots (yet)
- **Same Mac** — bot and Antigravity must be on the same machine
- **10 min timeout** — long-running tasks will time out

## Security

- Only messages from `allowed_chat_ids` are processed
- Bot token and chat IDs are stored in `config.json` (gitignored)
- CDP and callback server are localhost-only

## License

MIT
