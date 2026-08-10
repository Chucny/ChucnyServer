"""
PoGO private server — ONE launcher that runs everything in a single process:
the DNS redirector (UDP 53) and the game server (TCP 443, fake PTC SSO + RPC).

  Local (same Wi-Fi as the phone):
      py run.py                      # auto-detects this PC's LAN IP
  Remote (server with a public IP / VPS):
      py run.py 203.0.113.7          # the IP the phone should be pointed at
      RUN_IP=203.0.113.7 py run.py

Point the phone's Wi-Fi DNS at the IP this prints. Both 53/udp and 443/tcp must be
reachable from the phone (open them in the firewall; on Windows low ports are fine
without admin, but a firewall *allow* rule for inbound may be needed).

Build a standalone .exe (no Python needed on the target):
      py -m PyInstaller --onefile --name pogo-server \
         --add-data "certs;certs" --collect-all s2sphere run.py
"""
import os
import socket
import sys
import threading
import time

# ---- resource base (works when frozen by PyInstaller too) -------------------
if getattr(sys, "frozen", False):
    BASE = sys._MEIPASS                         # bundled read-only data
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)


def detect_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))              # no packets sent; reveals iface IP
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _setup_logging():
    """Tee ALL console output to server-log.txt next to the exe/script, so the
    full RPC / asset / map trace can be sent for debugging (the game client strips
    its own logs, so this server log is our only window into what happened)."""
    log_dir = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
               else os.path.dirname(os.path.abspath(__file__)))
    # APPEND, don't truncate. Opening "w" wiped the log on every restart, so
    # anything that happened in the previous session -- exactly the session you
    # want to look at when something "stopped working" -- was already gone by the
    # time anyone went looking. Roll over at 5 MB so it can't grow forever.
    log_path = os.path.join(log_dir, "server-log.txt")
    try:
        if os.path.getsize(log_path) > 5_000_000:
            os.replace(log_path, log_path + ".1")
    except OSError:
        pass
    try:
        logf = open(log_path, "a", encoding="utf-8", buffering=1)  # line-buffered
    except OSError:
        return
    try:
        import datetime as _dt
        stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logf.write("\n" + "=" * 60 + "\n")
        logf.write(f"  bracky's PoGO private server  --  session started {stamp}\n")
        logf.write("=" * 60 + "\n")
    except Exception:
        pass

    class _Tee:
        def __init__(self, *streams):
            self.streams = streams

        def write(self, t):
            for s in self.streams:
                if s:
                    try:
                        s.write(t); s.flush()
                    except Exception:
                        pass
            return len(t)

        def flush(self):
            for s in self.streams:
                if s:
                    try:
                        s.flush()
                    except Exception:
                        pass

    sys.stdout = _Tee(sys.__stdout__, logf)
    sys.stderr = _Tee(sys.__stderr__, logf)


def main():
    _setup_logging()
    redirect_ip = (sys.argv[1] if len(sys.argv) > 1
                   else os.environ.get("RUN_IP") or detect_ip())
    # hand config to the imported modules via env (read at their import time)
    os.environ["REDIRECT_IP"] = redirect_ip
    os.environ.setdefault("PORT", "443")
    os.environ.setdefault("BIND", "0.0.0.0")
    os.environ.setdefault("DNS_PORT", "53")
    os.environ.setdefault("CERT_DIR", os.path.join(BASE, "certs"))
    # Serve the real 2016 game master so the client has Pokemon templates and will
    # actually request + render the wild Pokemon (asset bundles now shipped in
    # assets/). Set SERVE_GAME_MASTER=0 to fall back to the bare template set.
    os.environ.setdefault("SERVE_GAME_MASTER", "1")

    import server
    import dns_redirect

    if not (os.path.exists(server.CERT) and os.path.exists(server.KEY)):
        print(f"!! TLS certs not found in {os.environ['CERT_DIR']}.\n"
              f"   Run gen_certs.py once, or ship the certs/ folder alongside this.")
        sys.exit(1)

    # World Manager (localhost only -- never exposed to the phone/network)
    try:
        import settings as _cfg
        admin_port = _cfg.get("server", "world_manager_port", env="ADMIN_PORT", cast=int)
    except Exception:
        admin_port = int(os.environ.get("ADMIN_PORT", "8080"))
    try:
        import admin
        admin.start(port=admin_port)
        admin_url = f"http://127.0.0.1:{admin_port}"
    except Exception as e:
        admin_url = f"(failed to start: {e})"

    print("=" * 60)
    print("  PoGO private server  --  built by bracky")
    print("  a Pokemon GO 0.29 (July 2016) server, made from scratch")
    print("-" * 60)
    print(f"  World Manager (this PC):          {admin_url}")
    print(f"  Point the phone's Wi-Fi DNS at:   {redirect_ip}")
    print(f"  Game server : https://{redirect_ip}:{os.environ['PORT']}")
    print(f"  DNS redirect: udp {redirect_ip}:{os.environ['DNS_PORT']}")
    print("  (Ctrl-C to stop)")
    print("=" * 60)
    print("  bracky's PoGO server -- everything below is live server activity")
    print()

    # DNS in a supervised background thread (auto-restarts if it ever dies)
    def dns_loop():
        while True:
            try:
                dns_redirect.main()
            except Exception as e:
                print(f"[dns] restarting after: {e}", flush=True)
                time.sleep(1)
    threading.Thread(target=dns_loop, daemon=True).start()

    # HTTPS server on the main thread (blocks until Ctrl-C)
    try:
        server.main()
    except KeyboardInterrupt:
        print("\nshutting down.")


if __name__ == "__main__":
    main()
