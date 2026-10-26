from embody.sim import DuckBody
from embody.sim.main import build_parser, handle_line


class StubClient:
    def __init__(self):
        self.calls = []

    async def send_text(self, text):
        self.calls.append(("text", text))

    async def send_event(self, name, where=None, data=None):
        self.calls.append(("event", name, where))

    async def send_vad(self, on):
        self.calls.append(("vad", on))

    async def send_state(self):
        self.calls.append(("state",))


async def run(lines):
    c, b, out = StubClient(), DuckBody(), []
    results = [await handle_line(line, c, b, out.append) for line in lines]
    return c, b, out, results


async def test_text_and_blank():
    c, b, out, r = await run(["hello duck", "   "])
    assert c.calls == [("text", "hello duck")] and r == [True, True]


async def test_commands():
    c, b, out, r = await run(["/touch", "/touch wing", "/pickup", "/vad on", "/vad off", "/state"])
    assert c.calls == [
        ("event", "touch", "head"), ("event", "touch", "wing"), ("event", "picked_up", None),
        ("vad", True), ("vad", False), ("state",),
    ]
    assert b.pose == "picked_up" and b.touched
    c, b, out, r = await run(["/pickup", "/putdown"])
    assert b.pose == "upright" and c.calls[-1] == ("event", "put_down", None)


async def test_help_unknown_quit_and_bad_vad():
    c, b, out, r = await run(["/help", "/nope", "/vad maybe", "/quit", "/touch"])
    assert r == [True, True, True, False, True]
    assert any("/quit" in o for o in out) and any("unknown command" in o for o in out)
    assert any("usage" in o for o in out)


def test_parser_defaults(monkeypatch):
    monkeypatch.setenv("EMBODY_DEVICE_TOKEN", "envtok")
    a = build_parser().parse_args([])
    assert a.url == "ws://127.0.0.1:8765/ws" and a.id.startswith("sim-")
    assert a.token == "envtok" and not a.speak and not a.quiet
    a = build_parser().parse_args(["--url", "ws://x/ws", "--id", "d", "--token", "t", "--speak", "--quiet"])
    assert (a.url, a.id, a.token, a.speak, a.quiet) == ("ws://x/ws", "d", "t", True, True)
