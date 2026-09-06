"""The HTTP plumbing for the review console.

Deliberately small and deliberately closed:

* it binds to the loopback interface, so nothing outside this machine can
  reach it;
* every write requires a token minted at start-up and embedded in the page, so
  another site open in the same browser cannot post decisions here;
* it serves exactly one document and four endpoints — there is no path that
  reads a file chosen by the request.

The session it mutates is immutable; requests swap one for the next under a
lock rather than editing shared state.
"""

from __future__ import annotations

import json
import secrets
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from recon.server.api import apply_decision, apply_promote, apply_reset, state_payload
from recon.server.page import render_console
from recon.server.session import ReviewSession, start_session

HOST = "127.0.0.1"
MAX_BODY_BYTES = 64 * 1024

Action = Callable[[ReviewSession, dict[str, Any]], tuple[ReviewSession, dict[str, Any]]]

WRITES: dict[str, Action] = {
    "/api/decision": apply_decision,
    "/api/promote": lambda session, _body: apply_promote(session),
    "/api/reset": lambda session, _body: apply_reset(session),
}


class _Holder:
    """The current session, swapped atomically."""

    def __init__(self, session: ReviewSession) -> None:
        self.session = session
        self.lock = threading.Lock()

    def apply(self, action: Action, body: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self.session, payload = action(self.session, body)
            return payload


class ConsoleHandler(BaseHTTPRequestHandler):
    """Serves one page and four endpoints. Nothing else is reachable.

    The three class attributes are filled in per server by `_make_handler`,
    which is why this class is never instantiated directly.
    """

    server_version = "recon-console"
    holder: _Holder
    token: str
    page: str

    def log_message(self, *_args: Any) -> None:
        """Stay quiet: the terminal running this is also running the demo."""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _authorised(self) -> bool:
        """The page knows the token; another site open in this browser does not."""
        if self.headers.get("X-Recon-Token") != self.token:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin.endswith(f"//{self.headers.get('Host', '')}")

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError("request body too large")
        if length == 0:
            return {}
        parsed = json.loads(self.rfile.read(length))
        if not isinstance(parsed, dict):
            raise ValueError("request body must be a JSON object")
        return parsed

    def do_GET(self) -> None:
        if self.path == "/":
            self._send(200, self.page.encode(), "text/html; charset=utf-8")
        elif self.path != "/api/state":
            self._json(404, {"error": "no such path"})
        elif not self._authorised():
            self._json(403, {"error": "bad or missing console token"})
        else:
            self._json(200, state_payload(self.holder.session))

    def do_POST(self) -> None:
        action = WRITES.get(self.path)
        if action is None:
            self._json(404, {"error": "no such path"})
            return
        if not self._authorised():
            self._json(403, {"error": "bad or missing console token"})
            return
        try:
            self._json(200, self.holder.apply(action, self._body()))
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        except json.JSONDecodeError:
            self._json(400, {"error": "body was not valid JSON"})


def _make_handler(holder: _Holder, token: str, page: str) -> type[ConsoleHandler]:
    """Bind one server's state onto a handler class."""
    return type(
        "BoundConsoleHandler",
        (ConsoleHandler,),
        {"holder": holder, "token": token, "page": page},
    )


def build_server(
    *,
    total_cases: int,
    seed: int,
    knowledge_path: Path,
    decisions_path: Path,
    port: int,
) -> tuple[ThreadingHTTPServer, str]:
    """Create the server without starting it. Returns the server and its URL."""
    session = start_session(
        total_cases=total_cases,
        seed=seed,
        knowledge_path=knowledge_path,
        decisions_path=decisions_path,
    )
    token = secrets.token_urlsafe(32)
    page = render_console(token, total_cases, seed)
    handler = _make_handler(_Holder(session), token, page)

    server = ThreadingHTTPServer((HOST, port), handler)
    return server, f"http://{HOST}:{server.server_address[1]}/"


def serve(
    *,
    total_cases: int,
    seed: int,
    knowledge_path: Path,
    decisions_path: Path,
    port: int = 8765,
) -> int:
    """Run the console until interrupted."""
    server, url = build_server(
        total_cases=total_cases,
        seed=seed,
        knowledge_path=knowledge_path,
        decisions_path=decisions_path,
        port=port,
    )
    print(f"  review console on {url}")
    print("  decisions append to", decisions_path)
    print("  ctrl-c to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        server.server_close()
    return 0
