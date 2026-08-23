"""Launch PoGO normally, then ATTACH Frida + hook within the ~10s window before
the game calls System.load("libNianticLabsPlugin.so"). Spawn-mode crashes the
ARM-translated app on LDPlayer; attach to a normally-running app is gentler."""
import os
import subprocess
import threading
import time
import frida

DEVICE = os.environ.get("DEVICE", "127.0.0.1:5555")
ADB = os.environ.get("ADB", r"C:\LDPlayer\LDPlayer9\adb.exe")
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


def adb(*args):
    subprocess.run([ADB, "-s", DEVICE, *args], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def adb_out(*args):
    return subprocess.run([ADB, "-s", DEVICE, *args], capture_output=True,
                          text=True).stdout.strip()


def main():
    adb("shell", "am", "force-stop", PKG)
    adb("logcat", "-c")
    dev = frida.get_device(DEVICE, timeout=20)
    # launch
    adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
    print("launched; racing to attach...", flush=True)
    def find_pid():
        out = adb_out("shell", "pidof", PKG)
        for tok in out.split():
            if tok.isdigit():
                return int(tok)
        # fallback: parse `ps` (Android 5.1 toolbox: USER PID PPID ... NAME)
        for line in adb_out("shell", "ps").splitlines():
            if line.rstrip().endswith(PKG):
                cols = line.split()
                if len(cols) >= 2 and cols[1].isdigit():
                    return int(cols[1])
        return None

    pid = None
    t0 = time.time()
    while time.time() - t0 < 12:
        pid = find_pid()
        if pid:
            break
        time.sleep(0.2)
    if not pid:
        print("process never appeared"); return
    print(f"attaching to pid {pid} at t+{time.time()-t0:.1f}s", flush=True)
    session = dev.attach(pid)
    script = session.create_script(open(os.path.join(HERE, "_hook.js"), encoding="utf-8").read())
    script.on("message", on_message)
    script.load()
    print(f"hook loaded at t+{time.time()-t0:.1f}s", flush=True)
    threading.Event().wait()


if __name__ == "__main__":
    main()
