"""
Tiny DNS server for the non-rooted-device setup.

Answers the Niantic/PTC hostnames with THIS PC's LAN IP (so the phone reaches our
server) and forwards every other query to a real upstream resolver (so the phone's
normal internet keeps working). Point the phone's Wi-Fi DNS at this PC's LAN IP.

Run:  py dns_redirect.py            # auto-detects LAN IP, binds 0.0.0.0:53
      REDIRECT_IP=192.168.1.50 py dns_redirect.py
Needs admin on Windows to bind UDP/53.
"""
import os
import socket
import struct
import threading

UPSTREAM = (os.environ.get("UPSTREAM", "8.8.8.8"), 53)
PORT = int(os.environ.get("DNS_PORT", "53"))

REDIRECT_HOSTS = {
    "pokemongo.zendesk.com",          # in-game Settings -> support -> Help Center
    "pgorelease.nianticlabs.com",
    "sso.pokemon.com",
    "holo.nianticlabs.com",
    "www.nianticlabs.com",
    "nianticlabs.com",
    "pokemon.com",
}


def lan_ip():
    if os.environ.get("REDIRECT_IP"):
        return os.environ["REDIRECT_IP"]
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))      # no traffic sent; reveals the LAN iface IP
        return s.getsockname()[0]
    finally:
        s.close()


REDIRECT_IP = lan_ip()


def parse_qname(data):
    """Return (qname_lower, end_offset) from the DNS question section."""
    pos = 12
    labels = []
    while True:
        ln = data[pos]
        if ln == 0:
            pos += 1
            break
        labels.append(data[pos + 1:pos + 1 + ln].decode("ascii", "replace"))
        pos += 1 + ln
    return ".".join(labels).lower(), pos


def build_a_response(query, ip):
    tid = query[:2]
    qname_end = parse_qname(query)[1]
    question = query[12:qname_end + 4]                  # qname + qtype + qclass
    header = tid + struct.pack(">HHHHH", 0x8180, 1, 1, 0, 0)  # QR+RD+RA, 1 q, 1 ans
    answer = (b"\xc0\x0c" +                              # name ptr to question
              struct.pack(">HHIH", 1, 1, 60, 4) +        # type A, class IN, ttl, rdlen
              socket.inet_aton(ip))
    return header + question + answer


def forward(query):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(4)
    try:
        s.sendto(query, UPSTREAM)
        return s.recvfrom(4096)[0]
    finally:
        s.close()


def handle(sock, data, addr):
    try:
        qname = parse_qname(data)[0]
        match = any(qname == h or qname.endswith("." + h) for h in REDIRECT_HOSTS)
        if match:
            print(f"[dns] {addr[0]}  {qname} -> {REDIRECT_IP} (REDIRECTED)", flush=True)
            sock.sendto(build_a_response(data, REDIRECT_IP), addr)
        else:
            print(f"[dns] {addr[0]}  {qname} (forwarded)", flush=True)
            sock.sendto(forward(data), addr)
    except Exception as e:
        print(f"[dns] error for {addr}: {e}", flush=True)


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", PORT))
    except OSError as e:
        print(f"Could not bind UDP/{PORT}: {e}\nRun as administrator, or free port {PORT}.")
        return
    print(f"DNS redirector on 0.0.0.0:{PORT}  ->  PoGO hosts resolve to {REDIRECT_IP}", flush=True)
    print(f"Set the phone's Wi-Fi DNS to {REDIRECT_IP}", flush=True)
    while True:
        try:
            data, addr = sock.recvfrom(4096)
            threading.Thread(target=handle, args=(sock, data, addr), daemon=True).start()
        except ConnectionResetError:
            continue            # Windows: ICMP port-unreachable surfaces here; ignore
        except Exception as e:  # never let the listener die
            print(f"[dns] loop error (continuing): {e}", flush=True)
            continue


if __name__ == "__main__":
    import time as _t
    while True:                 # auto-rebind if the socket ever dies
        try:
            main()
        except Exception as e:
            print(f"[dns] restarting after fatal: {e}", flush=True)
            _t.sleep(1)
