# Running the PoGO private server (one launcher)

Everything (DNS redirector + game server) now runs from a **single** process.

## Option A — the executable (no Python needed)
`dist\pogo-server.exe` is self-contained (Python + deps + the TLS certs are baked in).

- **Local (phone on the same Wi-Fi):** double-click `pogo-server.exe`. It prints the
  IP to point the phone's Wi-Fi DNS at.
- **Remote / specific IP:** `pogo-server.exe 203.0.113.7` (the IP the phone should reach).

## Option B — the script
- Local: `py run.py`  (or double-click `start.bat`)
- Remote: `py run.py <public-ip>`

The launcher prints something like:
```
Point the phone's Wi-Fi DNS at:   192.168.111.6
Game server : https://192.168.111.6:443
DNS redirect: udp 192.168.111.6:53
```

## On the phone (unchanged)
1. Install the patched APK (`pogo-0.29.0.metapatch.apk`) and the CA (`certs/ca.crt`) — one-time.
2. Wi-Fi → your network → **Static** IP settings → set **DNS 1 = the IP above** and
   leave **DNS 2 blank** (a real DNS 2 lets the phone bypass us and breaks login).
3. Launch the game, log in with any username/password.

## Making it remote (play off your home network)

The DNS-redirect approach works remotely too — the catch is the phone must be told
to use the server for DNS, and the server's ports must be reachable.

1. Run it on a host with a **public IP** (VPS, or your home IP with port-forwarding):
   `pogo-server.exe <public-ip>`   (so DNS hands out that public IP).
2. Open inbound **udp/53** and **tcp/443** to the host (cloud firewall + Windows Firewall).
3. On the phone, set Wi-Fi (or a VPN/Private-DNS profile) **DNS = the public IP**.
   - Plain Wi-Fi static DNS only applies on networks you control. For true
     "anywhere" use, put the phone on a small **VPN** to the server and point DNS at
     the VPN address — that's the robust path and avoids exposing port 53 publicly.

⚠️ A publicly reachable port-53 forwarder is an *open resolver* (can be abused for
traffic amplification). If you expose 53 to the internet, firewall it to only the
phone's IP, or prefer the VPN approach above.

## Firewall note (Windows)
Low ports bind without admin, but inbound traffic from the phone may be blocked by
Windows Firewall. If the phone can't reach the server, allow it:
```
netsh advfirewall firewall add rule name="pogo-dns"  dir=in action=allow protocol=UDP localport=53
netsh advfirewall firewall add rule name="pogo-https" dir=in action=allow protocol=TCP localport=443
```
(Run that in an **Administrator** command prompt.)
