"""serve.py: a local static server of the page, bound to 127.0.0.1 only. The page is the built app in web/dist/ (checked in, so no Node is
needed); /presets/, /kits/ and /assets/ are served from web/public/ (the static data Vite copies into a build). `--kit DIR` mounts a user's
kit folder at /kits/user/ and adds it to /kits/index.json.

Local install only: this is how someone "brings their own drums". The server reads files and nothing else (GET/HEAD; no uploads, no writes)."""
import http.server, json, pathlib, posixpath, socketserver, sys, urllib.parse

STATIC = ("presets", "kits", "assets")      # served from web/public/ (the data folders), everything else from web/dist/ (the built page)


class Handler(http.server.SimpleHTTPRequestHandler):
    web = None; dist = None; public = None; kit = None; kit_meta = None

    def translate_path(self, path):
        path = posixpath.normpath(urllib.parse.unquote(urllib.parse.urlparse(path).path))
        parts = [p for p in path.split("/") if p and p not in (".", "..")]
        if self.kit and parts[:2] == ["kits", "user"]: return str(self.kit.joinpath(*parts[2:]))
        if parts and parts[0] in STATIC and (self.public / parts[0]).is_dir(): return str(self.public.joinpath(*parts))
        return str(self.dist.joinpath(*parts))

    def do_GET(self):
        if self.kit and urllib.parse.urlparse(self.path).path == "/kits/index.json":
            idx = {"version": 1, "kits": []}
            f = self.public / "kits" / "index.json"
            if f.exists():
                try: idx = json.load(open(f))
                except Exception: pass
            idx["kits"] = [dict(id="user", name=self.kit_meta.get("name", "My kit"))] + [k for k in idx.get("kits", []) if k.get("id") != "user"]      # first = the default kit
            body = json.dumps(idx).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        return super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store"); super().end_headers()

    def log_message(self, fmt, *a): pass


def run(web, kit=None, port=8814):
    Handler.web = pathlib.Path(web).resolve(); Handler.dist = Handler.web / "dist"; Handler.public = Handler.web / "public"
    if not (Handler.dist / "index.html").exists(): sys.exit(f"{Handler.dist}/index.html not found: the built page is missing (cd web && npm ci && npm run build)")
    if kit:
        k = pathlib.Path(kit).resolve()
        if not (k / "kit.json").exists(): sys.exit(f"{k}/kit.json not found (see docs/kits.md)")
        Handler.kit = k; Handler.kit_meta = json.load(open(k / "kit.json"))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler) as srv:
        print(f"midi2motion: http://127.0.0.1:{port}/  (page: {Handler.dist}; data: {Handler.public}{'; kit: ' + str(Handler.kit) if kit else ''})  Ctrl-C to stop", flush=True)
        try: srv.serve_forever()
        except KeyboardInterrupt: print("stopped")
