"""``embody-duck``: terminal REPL around the software duck."""
from __future__ import annotations

import argparse
import asyncio
import os
import socket
import sys
import threading

from .body import DuckBody
from .client import DuckClient

HELP = """\
type text to talk to the duck. commands:
  /touch [where]   touch the duck (default: head)
  /pickup          pick the duck up
  /putdown         put it back down
  /tilt            tilt it
  /vad on|off      pretend you started / stopped speaking
  /state           show the duck and send a state frame
  /help            this help
  /quit            exit (Ctrl-C / Ctrl-D also work)"""


async def handle_line(line: str, client: DuckClient, body: DuckBody, out=print) -> bool:
    """Process one REPL line. Returns False when the REPL should exit."""
    line = line.strip()
    if not line:
        return True
    if not line.startswith("/"):
        await client.send_text(line)
        return True
    cmd, *rest = line.split()
    cmd = cmd.lower()
    if cmd in ("/quit", "/exit", "/q"):
        return False
    if cmd == "/help":
        out(HELP)
    elif cmd == "/touch":
        where = rest[0] if rest else "head"
        body.wake()
        body.touched = True
        asyncio.get_running_loop().call_later(2.0, setattr, body, "touched", False)
        await client.send_event("touch", where=where)
        out(body.render())
    elif cmd == "/pickup":
        body.wake()
        body.pose = "picked_up"
        await client.send_event("picked_up")
        out(body.render())
    elif cmd == "/putdown":
        body.pose = "upright"
        await client.send_event("put_down")
        out(body.render())
    elif cmd == "/tilt":
        body.pose = "tilted"
        await client.send_event("tilted")
        out(body.render())
    elif cmd == "/vad":
        if not rest or rest[0].lower() not in ("on", "off"):
            out("usage: /vad on|off")
        else:
            await client.send_vad(rest[0].lower() == "on")
    elif cmd == "/state":
        out(body.render())
        await client.send_state()
    else:
        out(f"unknown command {cmd}; try /help")
    return True


def _start_stdin_reader(loop: asyncio.AbstractEventLoop, q: asyncio.Queue) -> None:
    """Daemon thread so a blocked read never delays interpreter exit."""
    def reader() -> None:
        while True:
            try:
                line = sys.stdin.readline()
            except Exception:
                line = ""
            if loop.is_closed():
                return
            loop.call_soon_threadsafe(q.put_nowait, line if line else None)
            if not line:
                return

    threading.Thread(target=reader, name="duck-stdin", daemon=True).start()


async def amain(args: argparse.Namespace) -> None:
    body = DuckBody()
    client = DuckClient(
        args.url, args.id, args.token, body, print, speak=args.speak, quiet=args.quiet,
    )
    runner = asyncio.create_task(client.run())
    q: asyncio.Queue[str | None] = asyncio.Queue()
    _start_stdin_reader(asyncio.get_running_loop(), q)
    print(f"embody-duck {args.id} -> {args.url}   (/help for commands)")
    print(body.render())
    try:
        while True:
            line = await q.get()
            if line is None or not await handle_line(line, client, body):
                break
    finally:
        await client.stop()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
        print("bye")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="embody-duck", description="Embody software duck simulator")
    p.add_argument("--url", default="ws://127.0.0.1:8765/ws", help="gateway WebSocket URL")
    p.add_argument("--id", default=f"sim-{socket.gethostname()}", help="device id")
    p.add_argument("--token", default=os.environ.get("EMBODY_DEVICE_TOKEN"),
                   help="device token (default: $EMBODY_DEVICE_TOKEN)")
    p.add_argument("--speak", action="store_true", help="speak replies with say/espeak if available")
    p.add_argument("--quiet", action="store_true", help="only print the duck's speech and errors")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        print("\nbye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
