# Playing on a real (non-rooted) Android device

This is the path that actually works: a **real Android phone is native ARM**, so the
translation-layer problems that killed every x86 emulator don't exist. The only
fix needed (the Android-7+ `System.load` absolute-path rule) is **baked into the
patched APK** via frida-gadget — no root required.

## What's prepared (all done, on this PC)

| Item | What it is |
|------|-----------|
| `work/pogo-0.29.0.objection.apk` | The game, repackaged with frida-gadget + our hook embedded + re-signed. Install **this**, not the original. |
| `work/server/dns_redirect.py` | DNS server: resolves the Niantic/PTC hosts to this PC, forwards the rest. |
| `work/server/server.py` | The game server (fake PTC login + RPC). |
| `work/server/certs/ca.crt` | The CA to install on the phone (user cert). |

## On the PC (start these; both need Administrator for ports 53/443)

```powershell
# terminal 1 - game server on :443
cd work\server ; py server.py
# terminal 2 - DNS redirector on :53
cd work\server ; py dns_redirect.py     # prints the LAN IP to use, e.g. 192.168.111.6
```
Note the **LAN IP** it prints — call it `PC_IP`. The phone must be on the **same Wi-Fi**.

## On the phone (one-time)

1. **Same Wi-Fi** as the PC.
2. **Point DNS at the PC.** Wi-Fi settings → your network → Modify/Advanced → IP
   settings = **Static**. Keep the assigned IP/gateway (or pick a free IP on the
   LAN), set **DNS 1 = `PC_IP`**. Save.
   - Quick check: open the phone browser to `https://pgorelease.nianticlabs.com` —
     you should get a TLS/connection from *our* server (a cert warning or empty
     reply), not Niantic. That confirms DNS + server reachability.
3. **Trust the CA.** Copy `certs/ca.crt` to the phone (USB, or `adb push`, or email
   to yourself). Settings → Security → *Encryption & credentials* → **Install a
   certificate → CA certificate** → pick `ca.crt`. Accept the "network may be
   monitored" warning. (The game targets API 23, so it trusts user certs.)
4. **Install the patched APK.** Either:
   - USB: `adb install work\pogo-0.29.0.objection.apk`, or
   - Copy the APK to the phone, enable "install unknown apps" for your file
     manager, tap it.
   - If an older PoGO is installed, uninstall it first (different signature).

## Play

Launch **Pokémon GO** → choose **Pokémon Trainer Club** → type **any username + any
password** → you should land in the game as that trainer. Watch the PC's `server.py`
console — you'll see the PTC login and the RPC handshake roll in.

## If something stalls (and how I'll see it over `adb logcat`)

- **Stuck on load / "failed to get game data":** the hook may not have fired. Check
  `adb logcat | findstr hook` for `[hook] System.load ... hook installed` and the
  `-> "<abs path>"` rewrite line. If absent, the gadget didn't load.
- **"Unable to authenticate" / cert error at PTC login:** this is the C#/Mono TLS
  path possibly not honoring the user CA. Tell me — I'll extend the embedded hook
  to bypass that validation (we already control the gadget).
- **Nothing hits `server.py`:** DNS isn't redirecting — re-check the browser test in
  step 2, and that both PC services show "listening".

## Why the emulators couldn't do this (for reference)

x86 emulators (LDPlayer, MEmu, BlueStacks) run ARM apps through a translation layer
(`libhoudini`/`libnb`). The game's networking plugin is loaded by an explicit
`System.load`, which bypasses that layer (x86 linker rejects the ARM binary), and
Frida — the only runtime fix — crashes the translation engine itself. A real ARM
phone has no translation layer, so the plugin loads natively and the gadget hook
runs cleanly.
