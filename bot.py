#!/usr/bin/env python3
"""Telegram ↔ Antigravity Bridge Bot.

Runs a Telegram bot + Unix domain socket server.
- Telegram messages → socket commands → Antigravity
- Antigravity results → socket → Telegram replies
"""

import asyncio
import json
import os
import socket
import time
import uuid
import logging

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("ag-bridge")

CONFIG_PATH = os.path.expanduser("~/.ag-bridge/config.json")


def load_config():
    """Load configuration from JSON file."""
    if not os.path.exists(CONFIG_PATH):
        logger.error(f"Config not found: {CONFIG_PATH}")
        logger.error("Create it with: bot_token, allowed_chat_ids, socket_path")
        raise SystemExit(1)

    with open(CONFIG_PATH) as f:
        config = json.load(f)

    if config.get("bot_token", "").startswith("YOUR_"):
        logger.error("Please set your bot_token in config.json")
        raise SystemExit(1)

    if not config.get("allowed_chat_ids"):
        logger.warning("No allowed_chat_ids configured — bot will reject all messages")

    config["socket_path"] = os.path.expanduser(
        config.get("socket_path", "~/.ag-bridge/bridge.sock")
    )
    return config


class BridgeServer:
    """Manages the Unix domain socket server for bridge communication."""

    def __init__(self, config):
        self.config = config
        self.socket_path = config["socket_path"]
        self.server_sock = None
        self.client_conn = None
        self.client_buffer = b""
        self.pending_commands = {}  # id -> asyncio.Future
        self.active_workspace = None
        self.app = None  # Telegram app reference

    async def start_socket_server(self):
        """Start Unix domain socket server."""
        # Clean up stale socket file
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        self.server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_sock.bind(self.socket_path)
        self.server_sock.listen(1)
        self.server_sock.setblocking(False)

        logger.info(f"Socket server listening at {self.socket_path}")
        asyncio.get_event_loop().add_reader(
            self.server_sock.fileno(), self._accept_client
        )

    def _accept_client(self):
        """Accept a new client connection."""
        conn, _ = self.server_sock.accept()
        conn.setblocking(False)

        # Close existing client if any
        if self.client_conn:
            logger.info("Replacing existing bridge client connection")
            asyncio.get_event_loop().remove_reader(self.client_conn.fileno())
            self.client_conn.close()

        self.client_conn = conn
        self.client_buffer = b""
        logger.info("Bridge client connected")
        asyncio.get_event_loop().add_reader(conn.fileno(), self._read_client)

    def _read_client(self):
        """Read data from bridge client."""
        try:
            data = self.client_conn.recv(65536)
            if not data:
                self._client_disconnected()
                return
            self.client_buffer += data
            self._process_buffer()
        except (ConnectionError, OSError):
            self._client_disconnected()

    def _process_buffer(self):
        """Process newline-delimited JSON messages from buffer."""
        while b"\n" in self.client_buffer:
            line, self.client_buffer = self.client_buffer.split(b"\n", 1)
            try:
                msg = json.loads(line.decode("utf-8"))
                asyncio.get_event_loop().create_task(self._handle_message(msg))
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from client: {line}")

    async def _handle_message(self, msg):
        """Handle a message from the bridge client."""
        msg_type = msg.get("type")

        if msg_type == "session_start":
            self.active_workspace = msg.get("workspace", "unknown")
            workspace_name = os.path.basename(self.active_workspace)
            logger.info(f"Session started: {self.active_workspace}")
            await self._notify_telegram(
                f"🟢 *Antigravity session active*\n"
                f"Workspace: `{workspace_name}`\n"
                f"Ready to receive commands\\."
            )

        elif msg_type == "result":
            cmd_id = msg.get("id")
            if cmd_id in self.pending_commands:
                future = self.pending_commands[cmd_id]
                if not future.done():
                    future.set_result(msg)
            else:
                logger.warning(f"Received result for unknown command: {cmd_id}")

    def _client_disconnected(self):
        """Handle client disconnection."""
        logger.info("Bridge client disconnected")
        if self.client_conn:
            try:
                asyncio.get_event_loop().remove_reader(self.client_conn.fileno())
            except Exception:
                pass
            self.client_conn.close()
        self.client_conn = None
        self.active_workspace = None

        # Fail all pending commands
        for cmd_id, future in self.pending_commands.items():
            if not future.done():
                future.set_result(
                    {"status": "error", "summary": "Antigravity session disconnected"}
                )
        self.pending_commands.clear()

        asyncio.get_event_loop().create_task(
            self._notify_telegram("🔴 *Antigravity session disconnected*")
        )

    async def _notify_telegram(self, text):
        """Send a notification to all allowed chat IDs."""
        if not self.app:
            return
        for chat_id in self.config.get("allowed_chat_ids", []):
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id, text=text, parse_mode="MarkdownV2"
                )
            except Exception as e:
                logger.error(f"Failed to notify chat {chat_id}: {e}")

    async def send_command(self, prompt, chat_id):
        """Send a command to Antigravity and wait for result."""
        if not self.client_conn:
            return {
                "status": "error",
                "summary": (
                    "No active Antigravity session.\n"
                    "Start one in your IDE with: 'Watch the bridge'"
                ),
            }

        cmd_id = str(uuid.uuid4())[:8]
        command = {
            "type": "command",
            "id": cmd_id,
            "prompt": prompt,
            "chat_id": chat_id,
            "ts": time.time(),
        }

        # Create future for result
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self.pending_commands[cmd_id] = future

        # Send command through socket
        msg = json.dumps(command) + "\n"
        try:
            self.client_conn.sendall(msg.encode("utf-8"))
            logger.info(f"Command {cmd_id} sent: {prompt[:80]}...")
        except (ConnectionError, OSError):
            self._client_disconnected()
            return {"status": "error", "summary": "Connection lost to Antigravity"}

        # Wait for result with timeout (10 minutes for complex tasks)
        try:
            result = await asyncio.wait_for(future, timeout=600)
            return result
        except asyncio.TimeoutError:
            return {
                "status": "error",
                "summary": "⏰ Timed out waiting for Antigravity (10 min)",
            }
        finally:
            self.pending_commands.pop(cmd_id, None)

    async def cleanup(self):
        """Clean up socket resources."""
        if self.client_conn:
            self.client_conn.close()
        if self.server_sock:
            self.server_sock.close()
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)


# --- Telegram Handlers ---


async def handle_message(update: Update, context):
    """Handle incoming Telegram messages."""
    bridge: BridgeServer = context.bot_data["bridge"]
    config = context.bot_data["config"]

    # Security: only allow configured chat IDs
    if update.effective_chat.id not in config.get("allowed_chat_ids", []):
        await update.message.reply_text("⛔ Unauthorized.")
        logger.warning(f"Rejected message from chat_id: {update.effective_chat.id}")
        return

    prompt = update.message.text
    logger.info(f"Received prompt from {update.effective_chat.id}: {prompt[:80]}...")

    await update.message.reply_text("📨 Command queued. Processing...")

    result = await bridge.send_command(prompt, update.effective_chat.id)

    status_icon = "✅" if result.get("status") == "success" else "❌"
    summary = result.get("summary", "No response")

    # Telegram has a 4096 char limit per message — split if needed
    if len(summary) > 4000:
        summary = summary[:4000] + "\n\n... (truncated)"

    await update.message.reply_text(f"{status_icon} {summary}")


async def handle_status(update: Update, context):
    """Handle /status command — check if Antigravity session is active."""
    bridge: BridgeServer = context.bot_data["bridge"]
    config = context.bot_data["config"]

    if update.effective_chat.id not in config.get("allowed_chat_ids", []):
        return

    if bridge.active_workspace:
        workspace_name = os.path.basename(bridge.active_workspace)
        await update.message.reply_text(
            f"🟢 *Active session*\nWorkspace: `{workspace_name}`",
            parse_mode="MarkdownV2",
        )
    else:
        await update.message.reply_text("🔴 No active Antigravity session.")


async def handle_help(update: Update, context):
    """Handle /help command."""
    config = context.bot_data["config"]

    if update.effective_chat.id not in config.get("allowed_chat_ids", []):
        return

    await update.message.reply_text(
        "🤖 *Antigravity Bridge Bot*\n\n"
        "Send any message and it will be forwarded to your "
        "Antigravity session as a prompt\\.\n\n"
        "*Commands:*\n"
        "/status \\- Check if Antigravity session is active\n"
        "/help \\- Show this message",
        parse_mode="MarkdownV2",
    )


async def post_init(app: Application):
    """Initialize bridge server after Telegram app starts."""
    bridge: BridgeServer = app.bot_data["bridge"]
    bridge.app = app
    await bridge.start_socket_server()
    logger.info("Bridge bot ready and listening.")


def main():
    config = load_config()
    bridge = BridgeServer(config)

    app = (
        Application.builder().token(config["bot_token"]).post_init(post_init).build()
    )
    app.bot_data["bridge"] = bridge
    app.bot_data["config"] = config

    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting Telegram bridge bot...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
