#!/usr/bin/env python3
"""Bridge client: connects to bot's Unix domain socket, translates to stdout/stdin.

- Receives command JSON from socket → prints to stdout
- Reads result JSON from stdin → sends through socket
- Sends session_start on connect
"""

import socket
import sys
import os
import json
import time
import threading

DEFAULT_SOCKET = os.path.expanduser("~/.ag-bridge/bridge.sock")


def get_workspace():
    """Detect current workspace from cwd."""
    return os.getcwd()


def connect(socket_path):
    """Connect to the bridge socket server."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(socket_path)
    return sock


def send_json(sock, data):
    """Send a JSON message (newline-delimited)."""
    msg = json.dumps(data) + "\n"
    sock.sendall(msg.encode("utf-8"))


def recv_json(sock):
    """Receive a newline-delimited JSON message.

    Reads from socket until a full newline-delimited JSON line is received.
    """
    buf = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("Socket closed")
        buf += chunk
        if b"\n" in buf:
            line, _ = buf.split(b"\n", 1)
            return json.loads(line.decode("utf-8"))


def stdin_reader(sock):
    """Thread: reads result lines from stdin and sends through socket."""
    try:
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                # Try parsing as JSON first
                result = json.loads(line)
            except json.JSONDecodeError:
                # If not valid JSON, wrap it as a plain text result
                result = {
                    "type": "result",
                    "id": "unknown",
                    "status": "success",
                    "summary": line,
                    "ts": time.time(),
                }
            send_json(sock, result)
            print(f"[bridge] Result sent.", flush=True)
    except (ConnectionError, BrokenPipeError, OSError):
        print("[bridge] Connection lost (stdin reader).", flush=True)


def main():
    socket_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOCKET
    workspace = get_workspace()

    print(f"[bridge] Connecting to {socket_path}...", flush=True)

    try:
        sock = connect(socket_path)
    except (ConnectionRefusedError, FileNotFoundError) as e:
        print(f"[bridge] ERROR: Cannot connect to socket: {e}", flush=True)
        print(
            "[bridge] Make sure the bot is running: python3 ~/.ag-bridge/bot.py",
            flush=True,
        )
        sys.exit(1)

    print("[bridge] Connected.", flush=True)

    # Send session start
    send_json(
        sock,
        {"type": "session_start", "workspace": workspace, "ts": time.time()},
    )
    print(f"[bridge] Session started for workspace: {workspace}", flush=True)

    # Start stdin reader thread (for sending results back)
    reader_thread = threading.Thread(target=stdin_reader, args=(sock,), daemon=True)
    reader_thread.start()

    # Main loop: receive commands from socket, print to stdout
    try:
        while True:
            print("[bridge] Waiting for command...", flush=True)
            command = recv_json(sock)

            if command.get("type") == "command":
                # Print command as a tagged line for Antigravity to parse
                print(f"[COMMAND]{json.dumps(command)}", flush=True)
    except (ConnectionError, BrokenPipeError, OSError):
        print("[bridge] Connection lost.", flush=True)
    except KeyboardInterrupt:
        print("[bridge] Shutting down.", flush=True)
    finally:
        sock.close()


if __name__ == "__main__":
    main()
