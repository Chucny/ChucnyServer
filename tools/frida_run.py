"""Spawn PoGO under Frida with _hook.js applied, then keep the session alive."""
import os
import sys
import threading
import frida

DEVICE_ID = os.environ.get("DEVICE", "127.0.0.1:5555")
PKG = "com.nianticlabs.pokemongo"
HERE = os.path.dirname(os.path.abspath(__file__))


def on_message(message, data):
    t = message.get("type")
    if t == "send":
        print("[send]", message.get("payload"), flush=True)
    elif t == "log":
        print("[log]", message.get("payload"), flush=True)
    elif t == "error":
        print("[error]", message.get("stack") or message.get("description"), flush=True)
    else:
        print("[msg]", message, flush=True)


def main():
    dev = frida.get_device(DEVICE_ID, timeout=20)
    print("device:", dev, flush=True)
    pid = dev.spawn([PKG])
    print("spawned", PKG, "pid", pid, flush=True)
    session = dev.attach(pid)
    script = session.create_script(open(os.path.join(HERE, "_hook.js"), encoding="utf-8").read())
    script.on("message", on_message)
    script.load()
    dev.resume(pid)
    print("resumed; hook live. streaming (Ctrl-C / kill to stop)...", flush=True)
    threading.Event().wait()   # keep process (and session/hook) alive


if __name__ == "__main__":
    main()
