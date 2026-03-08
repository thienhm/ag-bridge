#!/usr/bin/env python3
"""HTTP Callback Server — receives results from Antigravity agent via curl.

The agent sends a POST to /api/result with {"id": "...", "summary": "..."}
after completing a command. This server resolves the matching asyncio Future
so bot.py can forward the result to Telegram.
"""

import asyncio
import logging

from aiohttp import web

logger = logging.getLogger("ag-bridge.callback")


async def handle_result(request: web.Request) -> web.Response:
    """Handle POST /api/result from the agent's curl command."""
    pending_commands: dict = request.app["pending_commands"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Invalid JSON"}, status=400
        )

    cmd_id = body.get("id")
    summary = body.get("summary", "")

    if not cmd_id:
        return web.json_response(
            {"error": "Missing 'id' field"}, status=400
        )

    if cmd_id not in pending_commands:
        logger.warning(f"Result for unknown command: {cmd_id}")
        return web.json_response(
            {"error": f"Unknown command ID: {cmd_id}"}, status=404
        )

    future = pending_commands[cmd_id]
    if not future.done():
        future.set_result({
            "status": body.get("status", "success"),
            "summary": summary,
        })
        logger.info(f"Result received for command {cmd_id}: {summary[:80]}")

    return web.json_response({"ok": True})


def create_app(pending_commands: dict) -> web.Application:
    """Create the aiohttp web application with routes."""
    app = web.Application()
    app["pending_commands"] = pending_commands
    app.router.add_post("/api/result", handle_result)
    return app


async def start_server(port: int, pending_commands: dict) -> web.AppRunner:
    """Start the callback HTTP server as a background task.

    Args:
        port: Port to listen on (default 3001).
        pending_commands: Shared dict of command_id -> asyncio.Future.

    Returns:
        The AppRunner instance (for cleanup).
    """
    app = create_app(pending_commands)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Callback server listening on port {port}")
    return runner
