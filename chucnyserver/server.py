"""
PoGO 0.29 private server — single HTTPS listener that serves both the fake PTC
SSO (sso.pokemon.com) and the game RPC (pgorelease.nianticlabs.com), routed by
the Host header. Both hostnames resolve to this machine via your DNS redirect,
and one multi-SAN cert (see gen_certs.py) covers them all.

Run:  py server.py            # listens on 0.0.0.0:443
      PORT=8443 py server.py  # custom port (for local testing without root)
"""
import datetime
import os
import ssl
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import helpcenter
import rpc
import shop
import sso

HERE = os.path.dirname(os.path.abspath(__file__))
CERT_DIR = os.environ.get("CERT_DIR", os.path.join(HERE, "certs"))
CERT = os.path.join(CERT_DIR, "server.crt")
KEY = os.path.join(CERT_DIR, "server.key")
PORT = int(os.environ.get("PORT", "443"))
BIND = os.environ.get("BIND", "0.0.0.0")


def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    for line in str(msg).splitlines() or [""]:
        print(f"{ts}  {line}", flush=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):       # silence default noisy logging
        pass

    def _read_body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(n) if n else b""

    def _dispatch(self, method):
        host = (self.headers.get("Host", "") or "").split(":")[0].lower()
        path, _, query = self.path.partition("?")
        body = self._read_body()
        try:
            # Log every non-RPC request. When a login "just fails", this is the
            # difference between knowing the client reached us and guessing.
            if not path.startswith("/plfe"):
                log(f"[http] {method} https://{host}{path}"
                    + (f"?{query}" if query else ""))
            if "zendesk" in host or path.startswith("/hc"):
                # The in-game support button lands here. Player-facing, unlike
                # the World Manager, which stays on localhost.
                status, headers, out = helpcenter.handle(method, path, query,
                                                         self.headers, body, log)
            elif path.startswith("/shop"):
                # The phone-facing shop. Served from the game host so the DNS
                # redirect and our CA already cover it -- no extra setup.
                status, headers, out = shop.handle(method, path, query,
                                                   self.headers, body, log)
            elif "pokemon.com" in host:
                status, headers, out = sso.handle(method, path, query,
                                                  self.headers, body, log)
            elif "niantic" in host or path.startswith("/plfe"):
                status, headers, out = rpc.handle(method, path, query,
                                                  self.headers, body, log)
            else:
                log(f"[?] {method} host={host!r} {path} (unrouted)")
                status, headers, out = 404, {"Content-Type": "text/plain"}, b"?"
        except Exception as e:
            import traceback
            log(f"[!] handler error: {e}\n{traceback.format_exc()}")
            status, headers, out = 500, {"Content-Type": "text/plain"}, b"err"

        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        if out:
            self.wfile.write(out)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


def main():
    if not (os.path.exists(CERT) and os.path.exists(KEY)):
        log("Missing certs. Run:  py gen_certs.py")
        sys.exit(1)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)
    # 0.29-era Mono/BoringSSL clients negotiate older suites; be permissive.
    try:
        ctx.minimum_version = ssl.TLSVersion.TLSv1
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    except (ssl.SSLError, ValueError):
        pass

    class LoggingHTTPSServer(ThreadingHTTPServer):
        # socketserver silently swallows SSL handshake failures (except OSError:
        # return). Log them so we can see WHY a client (e.g. native RPC) is rejected
        # -- 'bad certificate' => client distrusts our CA; 'unsupported protocol' /
        # 'no shared cipher' => TLS-version/cipher mismatch.
        def get_request(self):
            try:
                return super().get_request()
            except ssl.SSLError as e:
                log(f"[tls] handshake FAILED: {e!r}")
                raise OSError(str(e)) from e

    httpd = LoggingHTTPSServer((BIND, PORT), Handler)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True,
                                   do_handshake_on_connect=True)
    log(f"PoGO private server listening on https://{BIND}:{PORT}")
    log("Routes: *.pokemon.com -> PTC SSO   |   *.nianticlabs.com -> RPC")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("shutting down")


if __name__ == "__main__":
    main()
