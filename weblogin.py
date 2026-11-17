"""Garmin sign-in page that runs on this computer.

The garmin_login tool opens it in the user's browser. The user types their
Garmin email, password and (if Garmin asks) the MFA code there, so the password
goes straight from this computer to Garmin and never passes through the chat.
Only the session tokens are saved (in TOKEN_DIR), never the password.

The page listens on 127.0.0.1 only, on a random port, under a random secret
path, and closes itself after the sign-in or after 15 minutes.
"""

import html
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from garminconnect import Garmin

TIMEOUT = 15 * 60  # seconds the page stays open


class LoginPage:
    def __init__(self, token_dir: Path):
        self.token_dir = token_dir
        self.secret = secrets.token_urlsafe(18)
        self.done = threading.Event()    # set after a successful sign-in
        self.closed = threading.Event()  # set when the page stops listening
        self.name: str | None = None     # Garmin display name after sign-in
        self._lock = threading.Lock()
        self._pending: tuple[Garmin, object] | None = None  # (client, state) while waiting for MFA
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(self))
        self.port = self.httpd.server_port
        self.url = f"http://127.0.0.1:{self.port}/{self.secret}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        t = threading.Timer(TIMEOUT, self.close)
        t.daemon = True
        t.start()

    @property
    def active(self) -> bool:
        return not self.closed.is_set()

    def close(self) -> None:
        if not self.closed.is_set():
            self.closed.set()
            threading.Thread(target=self.httpd.shutdown, daemon=True).start()

    # ------------------------------------------------------------ sign-in steps

    def sign_in(self, email: str, password: str) -> str:
        """Returns 'done' or 'mfa'. Raises with a readable message on failure."""
        with self._lock:
            g = Garmin(email=email, password=password, return_on_mfa=True)
            status, state = g.login()
            if status == "needs_mfa":
                self._pending = (g, state)
                return "mfa"
            self._finish(g)
            return "done"

    def submit_mfa(self, code: str) -> None:
        with self._lock:
            if not self._pending:
                raise RuntimeError("The sign-in expired. Please start again.")
            g, state = self._pending
            g.resume_login(state, code)
            self._pending = None
            self._finish(g)

    def _finish(self, g: Garmin) -> None:
        self.token_dir.mkdir(parents=True, exist_ok=True)
        g.client.dump(str(self.token_dir))
        check = Garmin()  # proves the saved tokens work on their own
        check.login(str(self.token_dir))
        self.name = check.get_full_name()
        self.done.set()
        t = threading.Timer(3, self.close)
        t.daemon = True
        t.start()


# ------------------------------------------------------------------ web page

STYLE = """
:root { --bg:#f6f7f9; --card:#fff; --text:#1c2430; --muted:#5d6878; --line:#d5dbe3;
        --accent:#0a6fd6; --accent-text:#fff; --bad:#b42318; --good:#137333; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#14181e; --card:#1d232b; --text:#e8edf3; --muted:#9aa6b5; --line:#35404d;
          --accent:#4c9ef0; --accent-text:#0b1520; --bad:#ff8a80; --good:#7ed492; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 420px; margin: 8vh auto; padding: 0 16px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:28px; }
h1 { font-size: 1.35rem; margin: 0 0 6px; }
p { margin: 0 0 16px; color: var(--muted); }
label { display:block; font-weight:600; margin: 14px 0 6px; }
input { width:100%; padding:10px 12px; font:inherit; color:var(--text); background:var(--bg);
        border:1px solid var(--line); border-radius:8px; }
button { margin-top:20px; width:100%; padding:11px; font:inherit; font-weight:600; border:0;
         border-radius:8px; background:var(--accent); color:var(--accent-text); cursor:pointer; }
button:disabled { opacity:.6; cursor:wait; }
.error { color: var(--bad); font-weight: 600; }
.ok { color: var(--good); font-weight: 600; }
small { display:block; margin-top:18px; color:var(--muted); }
p b { color: var(--text); }
.examples { list-style:none; padding:0; margin:0; }
.examples li { display:flex; gap:10px; align-items:center; padding:10px 0; border-top:1px solid var(--line); }
.examples span { flex:1; }
.examples .copy { width:auto; margin:0; padding:6px 10px; font-size:.85rem; background:transparent;
                  color:var(--accent); border:1px solid var(--line); }
"""

SCRIPT = """document.querySelectorAll('form').forEach(f => f.addEventListener('submit', () => {
  const b = f.querySelector('button'); b.disabled = true; b.textContent = 'Signing in…'; }));"""


def _page(body: str) -> bytes:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Garmin sign-in</title><style>{STYLE}</style></head>
<body><main><div class="card">{body}</div></main><script>{SCRIPT}</script></body></html>""".encode()


def _login_form(secret: str, error: str = "", email: str = "") -> bytes:
    err = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return _page(f"""<h1>Connect Claude to Garmin</h1>
<p>Sign in with your Garmin Connect account.</p>{err}
<form method="post" action="/{secret}/login">
<label for="email">Email</label>
<input id="email" name="email" type="email" autocomplete="username" required autofocus value="{html.escape(email)}">
<label for="password">Password</label>
<input id="password" name="password" type="password" autocomplete="current-password" required>
<button type="submit">Sign in</button></form>
<small>Your password goes straight from this computer to Garmin. It is not saved,
and Claude never sees it. Only a sign-in token is kept on this computer.</small>""")


def _mfa_form(secret: str, error: str = "") -> bytes:
    err = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return _page(f"""<h1>Enter the Garmin code</h1>
<p>Garmin sent you a security code (by email or text message).</p>{err}
<form method="post" action="/{secret}/mfa">
<label for="code">Code</label>
<input id="code" name="code" inputmode="numeric" autocomplete="one-time-code" required autofocus>
<button type="submit">Continue</button></form>""")


EXAMPLES = (
    "How did I sleep this week, and am I recovered enough for a hard session today?",
    "Summarize my training of the last 4 weeks.",
    "Plan 6x800 m intervals for Thursday and put them on my watch.",
    "Open my training dashboard.",
)


def _done_page(name: str | None) -> bytes:
    who = f" as {html.escape(name)}" if name else ""
    items = "".join(
        f'<li><span>{html.escape(q)}</span><button type="button" class="copy">Copy</button></li>'
        for q in EXAMPLES)
    return _page(f"""<h1 class="ok">Signed in{who}</h1>
<p>All done. Close this tab and go back to Claude. Claude can now read your sleep,
recovery and training, and plan workouts that sync to your watch.</p>
<p><b>Try asking Claude:</b></p><ul class="examples">{items}</ul>
<script>document.querySelectorAll('.copy').forEach(b => b.addEventListener('click', () => {{
  navigator.clipboard.writeText(b.previousElementSibling.textContent);
  b.textContent = 'Copied'; setTimeout(() => b.textContent = 'Copy', 1500); }}));</script>""")


def _closed_page() -> bytes:
    return _page("""<h1>This sign-in page has expired</h1>
<p>Go back to Claude and ask it to sign you in to Garmin again.</p>""")


def _friendly(e: Exception, mfa: bool = False) -> str:
    low = str(e).lower()
    if "429" in low or "too many" in low:
        return "Garmin is temporarily blocking sign-ins (too many attempts). Wait 15 minutes, then try again."
    if mfa:
        return "That code didn't work. Please check it and try again."
    if "401" in low or "credential" in low or "password" in low or "authentication" in low:
        return "Garmin didn't accept that email or password. Please try again."
    return f"Sign-in failed: {str(e)[:300]}"


def _make_handler(page: LoginPage):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # never write to stdout/stderr (MCP uses stdio)
            pass

        def _send(self, body: bytes, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _ok_request(self) -> bool:
            # Host check blocks DNS rebinding; the secret path blocks other local pages.
            if self.headers.get("Host") not in (f"127.0.0.1:{page.port}", f"localhost:{page.port}"):
                self._send(b"Forbidden", 403)
                return False
            if not self.path.startswith(f"/{page.secret}"):
                self._send(b"Not found", 404)
                return False
            return True

        def do_GET(self):
            if not self._ok_request():
                return
            if page.done.is_set():
                self._send(_done_page(page.name))
            elif page.closed.is_set():
                self._send(_closed_page())
            else:
                self._send(_login_form(page.secret))

        def do_POST(self):
            if not self._ok_request():
                return
            if page.done.is_set():
                return self._send(_done_page(page.name))
            if page.closed.is_set():
                return self._send(_closed_page())
            size = min(int(self.headers.get("Content-Length") or 0), 10_000)
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(size).decode("utf-8", "replace")).items()}
            action = self.path[len(page.secret) + 1:]
            if action == "/login":
                email = form.get("email", "").strip()
                try:
                    step = page.sign_in(email, form.get("password", ""))
                except Exception as e:  # noqa: BLE001
                    return self._send(_login_form(page.secret, _friendly(e), email))
                return self._send(_mfa_form(page.secret) if step == "mfa" else _done_page(page.name))
            if action == "/mfa":
                try:
                    page.submit_mfa(form.get("code", "").strip())
                except Exception as e:  # noqa: BLE001
                    if page._pending is None:
                        return self._send(_login_form(page.secret, _friendly(e)))
                    return self._send(_mfa_form(page.secret, _friendly(e, mfa=True)))
                return self._send(_done_page(page.name))
            self._send(b"Not found", 404)

    return Handler
