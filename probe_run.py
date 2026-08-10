import frida
dev = frida.get_device("127.0.0.1:5555", timeout=20)
# attach to any process (system_server) just to run JS runtime
sess = dev.attach("system_server")
s = sess.create_script(open("_probe.js", encoding="utf-8").read())
out=[]
s.on("message", lambda m,d: out.append(m))
s.load()
import time; time.sleep(1)
for m in out: print(m.get("payload") or m)
