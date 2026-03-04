#!/usr/bin/env python3
"""Telegram ↔ Antigravity Bridge Bot (v2).

Uses CDP (Chrome DevTools Protocol) for prompt injection and
an HTTP callback server for receiving results.

- Telegram message → CDP injects prompt into Antigravity
- Agent executes → curls result to HTTP callback server
- Result forwarded back to Telegram
"""

import asyncio
import json
import logging
import os
import uuid

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters

import cdp_bridge
import callback_server

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("ag-bridge")

CONFIG_PATH = os.path.expanduser("~/.ag-bridge/config.json")

# Pending commands: command_id -> asyncio.Future
pending_commands: dict[str, asyncio.Future] = {}


def load_config():
    """Load configuration from JSON file."""
    if not os.path.exists(CONFIG_PATH):
        logger.error(f"Config not found: {CONFIG_PATH}")
        logger.error("Create it with: ag-bridge onboard")
        raise SystemExit(1)

    with open(CONFIG_PATH) as f:
        config = json.load(f)

    if config.get("bot_token", "").startswith("YOUR_"):
        logger.error("Please set your bot_token in config.json")
        raise SystemExit(1)

    if not config.get("allowed_chat_ids"):
        logger.warning("No allowed_chat_ids configured — bot will reject all messages")

    # Defaults for new config fields
    config.setdefault("cdp_port", 9222)
    config.setdefault("callback_port", 3001)
    config.setdefault("timeout", 600)  # 10 minutes

    return config


def wrap_prompt(prompt: str, cmd_id: str, callback_port: int) -> str:
    """Wrap a user prompt with the HTTP callback instruction footer."""
    return (
        f"{prompt}\n\n"
        f"When done, send your result (no need to ask for approval):\n"
        f"curl -s -X POST http://localhost:{callback_port}/api/result "
        f"-H 'Content-Type: application/json' "
        f"-d '{{\"id\":\"{cmd_id}\",\"summary\":\"<1-3 sentence summary>\"}}'"
    )


# --- Telegram Handlers ---


async def handle_message(update: Update, context):
    """Handle incoming Telegram messages."""
    config = context.bot_data["config"]

    # Security: only allow configured chat IDs
    if update.effective_chat.id not in config.get("allowed_chat_ids", []):
        await update.message.reply_text("⛔ Unauthorized.")
        logger.warning(f"Rejected message from chat_id: {update.effective_chat.id}")
        return

    prompt = update.message.text
    logger.info(f"Received prompt from {update.effective_chat.id}: {prompt[:80]}...")

    # Check CDP availability
    cdp_port = config["cdp_port"]
    ws_url = await cdp_bridge.discover_target(cdp_port)

    if not ws_url:
        await update.message.reply_text(
            "❌ Cannot reach Antigravity IDE.\n\n"
            "Make sure Antigravity is running with:\n"
            f"`/Applications/Antigravity.app/Contents/MacOS/Antigravity "
            f"--remote-debugging-port={cdp_port}`",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text("📨 Injecting prompt...")

    # Generate command ID and wrap prompt
    cmd_id = str(uuid.uuid4())[:8]
    callback_port = config["callback_port"]
    wrapped = wrap_prompt(prompt, cmd_id, callback_port)

    # Create future for result
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    pending_commands[cmd_id] = future

    # Inject via CDP
    success = await cdp_bridge.inject_prompt(ws_url, wrapped)
    if not success:
        pending_commands.pop(cmd_id, None)
        await update.message.reply_text(
            "❌ Failed to inject prompt into Antigravity.\n"
            "The chat input might not be accessible."
        )
        return

    await update.message.reply_text("⏳ Prompt sent. Waiting for result...")

    # Wait for result with timeout
    timeout = config.get("timeout", 600)
    try:
        result = await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        result = {
            "status": "error",
            "summary": f"⏰ Timed out waiting for Antigravity ({timeout // 60} min)",
        }
    finally:
        pending_commands.pop(cmd_id, None)

    status_icon = "✅" if result.get("status") == "success" else "❌"
    summary = result.get("summary", "No response")

    # Telegram has a 4096 char limit per message
    if len(summary) > 4000:
        summary = summary[:4000] + "\n\n... (truncated)"

    await update.message.reply_text(f"{status_icon} {summary}")


async def handle_status(update: Update, context):
    """Handle /status command — check if Antigravity is reachable via CDP."""
    config = context.bot_data["config"]

    if update.effective_chat.id not in config.get("allowed_chat_ids", []):
        return

    cdp_port = config["cdp_port"]
    ws_url = await cdp_bridge.discover_target(cdp_port)

    if ws_url:
        await update.message.reply_text(
            f"🟢 *Antigravity reachable* via CDP on port {cdp_port}",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"🔴 Antigravity not reachable on CDP port {cdp_port}."
        )


async def handle_help(update: Update, context):
    """Handle /help command."""
    config = context.bot_data["config"]

    if update.effective_chat.id not in config.get("allowed_chat_ids", []):
        return

    await update.message.reply_text(
        "🤖 *ag\\-bridge v2*\n\n"
        "Send any message and it will be injected into your "
        "Antigravity session as a prompt\\.\n\n"
        "*Commands:*\n"
        "/status \\- Check if Antigravity is reachable\n"
        "/help \\- Show this message\n\n"
        "*Requires:*\n"
        "Antigravity launched with `\\-\\-remote\\-debugging\\-port=9222`",
        parse_mode="MarkdownV2",
    )


async def post_init(app: Application):
    """Initialize callback server after Telegram app starts."""
    config = app.bot_data["config"]
    callback_port = config["callback_port"]

    # Start the HTTP callback server
    runner = await callback_server.start_server(callback_port, pending_commands)
    app.bot_data["callback_runner"] = runner

    logger.info("ag-bridge v2 ready. Waiting for Telegram messages.")


def main():
    config = load_config()

    app = (
        Application.builder().token(config["bot_token"]).post_init(post_init).build()
    )
    app.bot_data["config"] = config

    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting ag-bridge v2 (CDP + HTTP callback)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
