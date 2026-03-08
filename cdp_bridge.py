#!/usr/bin/env python3
"""CDP Bridge — Chrome DevTools Protocol client for Antigravity prompt injection.

Discovers the Antigravity IDE target via CDP and injects prompts into the chat input.
Antigravity must be running with --remote-debugging-port (handled by `ag-bridge start`).
"""

import asyncio
import json
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger("ag-bridge.cdp")

# Script to find and focus the chat input element in Antigravity's webview.
# Tries common selectors for the prompt input field.
FIND_AND_FOCUS_INPUT_JS = """(() => {
    // Try known selectors for the Antigravity chat input
    const selectors = [
        'textarea[placeholder]',
        '[contenteditable="true"]',
        'textarea',
        '.chat-input textarea',
        '.input-area textarea',
    ];
    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el) {
            el.focus();
            // Clear any existing content
            if (el.tagName === 'TEXTAREA') {
                el.value = '';
                el.dispatchEvent(new Event('input', { bubbles: true }));
            } else {
                el.textContent = '';
            }
            return { found: true, selector: sel, tag: el.tagName };
        }
    }
    return { found: false };
})()"""


async def discover_target(port: int = 9222) -> Optional[str]:
    """Discover the Antigravity IDE CDP target and return its WebSocket debug URL.

    Args:
        port: The CDP remote debugging port (default 9222).

    Returns:
        The WebSocket debugger URL for the Antigravity workbench page,
        or None if no suitable target is found.
    """
    url = f"http://localhost:{port}/json/list"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    logger.error(f"CDP discovery failed: HTTP {resp.status}")
                    return None
                targets = await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.error(f"CDP discovery failed: {e}")
        return None

    # Filter for workbench/Antigravity page targets
    for target in targets:
        target_url = target.get("url", "")
        title = target.get("title", "")
        target_type = target.get("type", "")

        if (
            "workbench.html" in target_url
            or "Antigravity" in title
            or (target_type == "page" and "devtools" not in target_url)
        ):
            ws_url = target.get("webSocketDebuggerUrl")
            if ws_url:
                logger.info(f"Found CDP target: {title or target_url}")
                return ws_url

    logger.warning(f"No Antigravity target found among {len(targets)} targets")
    return None


async def inject_prompt(ws_debug_url: str, text: str) -> bool:
    """Inject a prompt into Antigravity's chat input via CDP.

    Connects to the CDP WebSocket, finds the chat input element, focuses it,
    inserts the text, and presses Enter.

    Args:
        ws_debug_url: The WebSocket debugger URL for the target page.
        text: The full prompt text to inject (already wrapped with callback footer).

    Returns:
        True if injection succeeded, False otherwise.
    """
    msg_id = 0

    async def send_cdp(ws, method: str, params: dict = None) -> dict:
        nonlocal msg_id
        msg_id += 1
        message = {"id": msg_id, "method": method}
        if params:
            message["params"] = params
        await ws.send_json(message)

        # Wait for the matching response
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("id") == msg_id:
                    return data
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                raise ConnectionError(f"WebSocket closed: {msg}")
        raise ConnectionError("WebSocket ended without response")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                ws_debug_url, max_msg_size=16 * 1024 * 1024
            ) as ws:
                try:
                    # Step 1: Find and focus the chat input
                    result = await send_cdp(ws, "Runtime.evaluate", {
                        "expression": FIND_AND_FOCUS_INPUT_JS,
                        "returnByValue": True,
                    })

                    eval_result = result.get("result", {}).get("result", {})
                    value = eval_result.get("value", {})

                    if not value.get("found"):
                        logger.error("Could not find chat input element")
                        return False

                    logger.info(
                        f"Found input: {value.get('selector')} ({value.get('tag')})"
                    )

                    # Small delay to ensure focus is established
                    await asyncio.sleep(0.1)

                    # Step 2: Insert the prompt text
                    await send_cdp(ws, "Input.insertText", {"text": text})

                    # Small delay before pressing Enter
                    await asyncio.sleep(0.1)

                    # Step 3: Press Enter to submit
                    await send_cdp(ws, "Input.dispatchKeyEvent", {
                        "type": "keyDown",
                        "key": "Enter",
                        "code": "Enter",
                        "windowsVirtualKeyCode": 13,
                        "nativeVirtualKeyCode": 13,
                    })
                    await send_cdp(ws, "Input.dispatchKeyEvent", {
                        "type": "keyUp",
                        "key": "Enter",
                        "code": "Enter",
                        "windowsVirtualKeyCode": 13,
                        "nativeVirtualKeyCode": 13,
                    })

                    logger.info("Prompt injected successfully")
                    return True

                finally:
                    # Cleanly disable runtime to release debugger hold
                    try:
                        await ws.send_json(
                            {"id": 9999, "method": "Runtime.disable"}
                        )
                    except Exception:
                        pass

    except (aiohttp.ClientError, ConnectionError, asyncio.TimeoutError) as e:
        logger.error(f"CDP injection failed: {e}")
        return False
