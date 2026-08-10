"""
Help Center -- https://pokemongo.zendesk.com/hc

The in-game Settings screen has a support button that opens that URL in the
phone's browser. We redirect the host and serve this instead, which makes it the
one place a PLAYER can reach from inside the game without being told a URL.

What it does: lets a trainer nominate a PokeStop or Gym where they're standing.
Nominations land in nominations.json and show up in the World Manager for
approval -- this is the player-facing half, deliberately separate from the
World Manager, which is the admin tool and stays on localhost.
"""
import json
import os
import sys
import threading
import time

_lock = threading.Lock()


def _data_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


FILE = os.path.join(_data_dir(), "nominations.json")


def _load():
    try:
        with open(FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return [n for n in d.get("nominations", []) if isinstance(n, dict)]
    except (OSError, ValueError):
        return []


def _save(rows):
    try:
        tmp = FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"nominations": rows}, fh, indent=1)
        os.replace(tmp, FILE)
    except OSError:
        pass


ONE_A_DAY_MS = 24 * 60 * 60 * 1000


def _photo_dir():
    import protocol
    return protocol.PHOTO_DIR


def save_photo(data_url, nom_id):
    """Write an uploaded photo into photos/ and return its filename.

    The page shrinks the image before sending, so this stays small. Anything
    that isn't a plain base64 image is dropped rather than trusted.
    """
    import base64
    if not data_url or not data_url.startswith("data:image/"):
        return ""
    try:
        head, b64 = data_url.split(",", 1)
        ext = "jpg" if "jpeg" in head or "jpg" in head else "png"
        raw = base64.b64decode(b64)
        if len(raw) > 3_000_000:                     # 3 MB is already generous
            return ""
        d = _photo_dir()
        os.makedirs(d, exist_ok=True)
        fn = f"{nom_id}.{ext}"
        with open(os.path.join(d, fn), "wb") as fh:
            fh.write(raw)
        return fn
    except Exception:
        return ""


def last_nomination(player):
    p = (player or "").lower()
    with _lock:
        times = [r.get("when", 0) for r in _load()
                 if (r.get("player") or "").lower() == p]
    return max(times) if times else 0


def cooldown_left(player):
    """Milliseconds until this trainer may nominate again. One a day, so a walk
    round the block can't fill the map with junk."""
    last = last_nomination(player)
    if not last:
        return 0
    return max(0, ONE_A_DAY_MS - (int(time.time() * 1000) - last))


def add(player, kind, name, lat, lng, note, photo_data=""):
    """Record a nomination and place it straight away -- these are auto-accepted."""
    import places
    nom_id = "nom-%d" % int(time.time() * 1000)
    photo = save_photo(photo_data, nom_id)
    row = {"id": nom_id,
           "player": player, "kind": "gym" if kind == "gym" else "stop",
           "name": (name or "").strip()[:40] or "Unnamed",
           "lat": round(float(lat), 6), "lng": round(float(lng), 6),
           "note": (note or "").strip()[:200], "photo": photo,
           "status": "approved", "when": int(time.time() * 1000)}
    places.add_fort(row["lat"], row["lng"], row["kind"], row["name"], photo)
    with _lock:
        rows = _load()
        rows.append(row)
        _save(rows)
    return row


def recent(n=25):
    with _lock:
        return _load()[-n:]


def mine(player):
    with _lock:
        return [r for r in _load()
                if (r.get("player") or "").lower() == (player or "").lower()][-20:]


def resolve(nom_id, status):
    """Mark a nomination approved/rejected. Returns the row so the caller can
    place the fort."""
    with _lock:
        rows = _load()
        for r in rows:
            if r["id"] == nom_id:
                r["status"] = status
                r["resolved"] = int(time.time() * 1000)
                _save(rows)
                return dict(r)
    return None


PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Help Center</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
 *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
 body{margin:0;font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif;
  color:#33474f;background:#f4f8f6;min-height:100vh}
 header{background:linear-gradient(180deg,#1f6f8b,#17566d);color:#fff;
  padding:18px 18px 16px;box-shadow:0 2px 10px rgba(0,0,0,.2)}
 header h1{margin:0;font-size:22px;font-weight:800;letter-spacing:.02em}
 header p{margin:5px 0 0;font-size:13px;color:rgba(255,255,255,.8)}
 .wrap{max-width:560px;margin:0 auto;padding:16px 14px 40px}
 .card{background:#fff;border:1px solid #e2eae6;border-radius:14px;padding:16px;
  margin-bottom:14px;box-shadow:0 2px 8px rgba(0,0,0,.05)}
 .card h2{margin:0 0 4px;font-size:16px;font-weight:800;color:#22404c}
 .card p.sub{margin:0 0 12px;font-size:12.5px;color:#7d94a1;line-height:1.55}
 label{display:block;font-size:12px;font-weight:700;color:#5b7683;margin:12px 0 5px;
  text-transform:uppercase;letter-spacing:.04em}
 input[type=text],textarea{width:100%;font:inherit;font-size:16px;color:#22404c;
  background:#f7fbf9;border:2px solid #dde8e3;border-radius:11px;padding:12px}
 input:focus,textarea:focus{outline:none;border-color:#38a58c;background:#fff}
 textarea{min-height:70px;resize:vertical}
 .kinds{display:flex;gap:10px}
 .kinds button{flex:1;padding:13px 8px;border-radius:12px;border:2px solid #dde8e3;
  background:#f7fbf9;font:inherit;font-size:15px;font-weight:700;color:#5b7683;cursor:pointer}
 .kinds button.on{background:#e6f5ef;border-color:#38a58c;color:#1d6f5c}
 #map{height:260px;border-radius:12px;margin-top:6px;border:2px solid #dde8e3;
  background:#e8eee9}
 .coords{font-size:12px;color:#7d94a1;margin-top:7px;text-align:center}
 .coords b{color:#22404c}
 .shot{display:flex;gap:12px;align-items:center;margin-top:6px}
 .shot .prev{width:78px;height:78px;border-radius:12px;flex:none;background:#eef4f1
  center/cover no-repeat;border:2px dashed #cfdcd6;display:grid;place-items:center;
  color:#a8bcb4;font-size:11px;text-align:center;overflow:hidden}
 .pick{flex:1;border:2px solid #dde8e3;background:#f7fbf9;border-radius:11px;
  padding:13px;font:inherit;font-size:14px;font-weight:700;color:#5b7683;
  text-align:center;cursor:pointer}
 .pick:active{background:#e6f5ef;border-color:#38a58c}
 input[type=file]{display:none}
 .go{width:100%;margin-top:16px;border:0;border-radius:999px;padding:15px;font:inherit;
  font-weight:800;font-size:16px;color:#fff;cursor:pointer;
  background:linear-gradient(180deg,#3ec39f,#22987c);box-shadow:0 4px 0 #17705c}
 .go:active{transform:translateY(2px);box-shadow:0 2px 0 #17705c}
 .go[disabled]{background:#adbdc4;box-shadow:0 4px 0 #8b9aa1}
 .quota{margin-top:10px;text-align:center;font-size:12.5px;color:#8a6410;
  background:#fff5e0;border-radius:10px;padding:10px}
 .row{display:flex;align-items:center;gap:10px;padding:11px 0;
  border-bottom:1px solid #eef3f0;font-size:14px}
 .row:last-child{border-bottom:0}
 .row .t{flex:1}
 .row .t small{display:block;color:#8ba0ab;font-size:11.5px;margin-top:2px}
 .row .th{width:40px;height:40px;border-radius:9px;background:#eef4f1 center/cover no-repeat;flex:none}
 .pill{font-size:11px;font-weight:800;padding:4px 9px;border-radius:999px;
  text-transform:uppercase;background:#dff3e6;color:#1d6f43}
 .empty{color:#9fb2bb;font-size:13px;text-align:center;padding:12px}
 #toast{position:fixed;left:50%;bottom:24px;transform:translate(-50%,14px);
  background:#22404c;color:#fff;padding:13px 20px;border-radius:13px;font-size:14px;
  font-weight:600;max-width:88vw;text-align:center;opacity:0;transition:.25s;
  pointer-events:none;z-index:2000}
 #toast.on{opacity:1;transform:translate(-50%,0)}
 #toast.bad{background:#8a2732}
</style></head><body>
<header>
  <h1>Help Center</h1>
  <p>Add a PokeStop or Gym near you</p>
</header>
<div class="wrap">
  <div class="card">
    <h2>Add a place</h2>
    <p class="sub">Drag the map so the pin sits on the spot, add a photo, and it
      goes into the game straight away. One a day.</p>

    <label>What is it</label>
    <div class="kinds">
      <button id="k-stop" class="on" onclick="setKind('stop')">PokeStop</button>
      <button id="k-gym" onclick="setKind('gym')">Gym</button>
    </div>

    <label>Where</label>
    <div id="map"></div>
    <div class="coords" id="coords">Finding you&hellip;</div>

    <label>Photo</label>
    <div class="shot">
      <div class="prev" id="prev">no photo</div>
      <div class="pick" onclick="document.getElementById('file').click()">
        Choose a photo</div>
      <input type="file" id="file" accept="image/*" onchange="pickPhoto(this)">
    </div>

    <label>Name</label>
    <input type="text" id="name" placeholder="e.g. The Old Oak Tree" maxlength="40">
    <label>About it</label>
    <textarea id="note" placeholder="A sentence about it" maxlength="200"></textarea>
    <label>Your trainer name</label>
    <input type="text" id="who" placeholder="trainer name" autocapitalize="off" spellcheck="false">

    <button class="go" id="send" onclick="send()">ADD IT</button>
    <div class="quota" id="quota" style="display:none"></div>
  </div>

  <div class="card">
    <h2>Yours</h2>
    <p class="sub">Everything you've added.</p>
    <div id="list"><div class="empty">Nothing yet.</div></div>
  </div>
</div>
<div id="toast"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const $ = id => document.getElementById(id);
let kind = 'stop', pos = null, photo = '', map = null, marker = null;
function setKind(k){
  kind = k;
  $('k-stop').className = k === 'stop' ? 'on' : '';
  $('k-gym').className  = k === 'gym'  ? 'on' : '';
}
function toast(m, bad){
  const t = $('toast'); t.textContent = m; t.className = 'on' + (bad ? ' bad' : '');
  clearTimeout(t._t); t._t = setTimeout(function(){ t.className=''; }, 3000);
}
async function api(path, body){
  const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'},
                               body: JSON.stringify(body||{})});
  return r.json();
}
function showCoords(){
  $('coords').innerHTML = 'Pin at <b>' + pos.lat.toFixed(5) + ', ' + pos.lng.toFixed(5)
                        + '</b> &mdash; drag the map to move it';
}
function initMap(lat, lng){
  pos = {lat: lat, lng: lng};
  if (typeof L === 'undefined'){        // no internet for the tiles; coords still work
    $('map').style.display = 'none';
    $('coords').innerHTML = 'Using where you are: <b>' + lat.toFixed(5) + ', '
                          + lng.toFixed(5) + '</b>';
    return;
  }
  map = L.map('map', {zoomControl:true}).setView([lat, lng], 18);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
              {maxZoom:19, attribution:'&copy; OpenStreetMap'}).addTo(map);
  marker = L.marker([lat, lng], {draggable:true}).addTo(map);
  marker.on('dragend', function(){
    const p = marker.getLatLng(); pos = {lat:p.lat, lng:p.lng}; showCoords();
  });
  map.on('click', function(e){
    marker.setLatLng(e.latlng); pos = {lat:e.latlng.lat, lng:e.latlng.lng}; showCoords();
  });
  showCoords();
  setTimeout(function(){ map.invalidateSize(); }, 200);
}
// Shrink on the device before uploading -- a modern phone photo is several MB
// and none of that detail survives on a 40px marker anyway.
function pickPhoto(input){
  const f = input.files && input.files[0];
  if (!f) return;
  const img = new Image(), rd = new FileReader();
  rd.onload = function(){ img.src = rd.result; };
  img.onload = function(){
    const max = 640, sc = Math.min(1, max / Math.max(img.width, img.height));
    const c = document.createElement('canvas');
    c.width = Math.round(img.width * sc); c.height = Math.round(img.height * sc);
    c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
    photo = c.toDataURL('image/jpeg', 0.82);
    $('prev').style.backgroundImage = 'url(' + photo + ')';
    $('prev').textContent = '';
  };
  rd.readAsDataURL(f);
}
async function send(){
  if (!pos) return toast('Still finding where you are', true);
  if (!$('who').value.trim()) return toast('Enter your trainer name', true);
  if (!photo) return toast('Add a photo first', true);
  $('send').disabled = true;
  const r = await api('/hc/nominate', {
    player: $('who').value.trim(), kind: kind, name: $('name').value,
    note: $('note').value, photo: photo, lat: pos.lat, lng: pos.lng});
  $('send').disabled = false;
  toast(r.message, !r.ok);
  if (r.ok){
    $('name').value=''; $('note').value=''; photo='';
    $('prev').style.backgroundImage=''; $('prev').textContent='no photo';
    refresh();
  }
  if (r.wait_ms) showQuota(r.wait_ms);
}
function showQuota(ms){
  if (!ms){ $('quota').style.display='none'; $('send').disabled=false; return; }
  const h = Math.floor(ms/3600000), m = Math.round((ms%3600000)/60000);
  $('quota').style.display='block';
  $('quota').textContent = 'You have used today\u2019s place. Next one in '
                         + (h ? h + 'h ' : '') + m + 'm.';
  $('send').disabled = true;
}
async function refresh(){
  const who = $('who').value.trim();
  if (!who) return;
  const r = await api('/hc/mine', {player: who});
  showQuota(r.wait_ms || 0);
  const box = $('list');
  if (!r.rows || !r.rows.length){
    box.innerHTML = '<div class="empty">Nothing yet.</div>'; return;
  }
  box.innerHTML = '';
  r.rows.slice().reverse().forEach(function(n){
    const d = document.createElement('div'); d.className='row';
    d.innerHTML =
      '<div class="th"' + (n.photo ? ' style="background-image:url(/hc/photo/'
        + encodeURIComponent(n.photo) + ')"' : '') + '></div>'
      + '<div class="t">' + n.name
      + '<small>' + (n.kind === 'gym' ? 'Gym' : 'PokeStop') + ' &middot; '
      + n.lat.toFixed(4) + ', ' + n.lng.toFixed(4) + '</small></div>'
      + '<span class="pill">in game</span>';
    box.appendChild(d);
  });
}
$('who').addEventListener('change', refresh);
(async function(){
  const r = await api('/hc/where', {});
  if (r.player && !$('who').value) $('who').value = r.player;
  if (navigator.geolocation){
    navigator.geolocation.getCurrentPosition(
      function(p){ initMap(p.coords.latitude, p.coords.longitude); refresh(); },
      function(){ initMap(r.lat || 0, r.lng || 0); refresh(); },
      {enableHighAccuracy:true, timeout:8000});
  } else {
    initMap(r.lat || 0, r.lng || 0); refresh();
  }
})();
</script></body></html>"""


def _json(obj, code=200):
    return code, {"Content-Type": "application/json",
                  "Cache-Control": "no-store"}, json.dumps(obj).encode("utf-8")


def handle(method, path, query, headers, body, log):
    if path in ("/", "/hc", "/hc/", "/hc/en-us", "/help"):
        return (200, {"Content-Type": "text/html; charset=utf-8",
                      "Cache-Control": "no-store"}, PAGE.encode("utf-8"))
    try:
        d = json.loads(body.decode("utf-8")) if body else {}
    except ValueError:
        d = {}

    if path == "/hc/where":
        import rpc
        return _json({"lat": rpc._last_loc[0], "lng": rpc._last_loc[1],
                      "player": rpc._last_user[0]})

    if path == "/hc/nominate":
        who = (d.get("player") or "").strip()
        if not who:
            return _json({"ok": False, "message": "Enter your trainer name."})
        wait = cooldown_left(who)
        if wait > 0:
            return _json({"ok": False, "wait_ms": wait,
                          "message": "You've already added a place today."})
        try:
            lat, lng = float(d.get("lat")), float(d.get("lng"))
        except (TypeError, ValueError):
            return _json({"ok": False, "message": "No location on that one."})
        if not (abs(lat) > 1e-6 or abs(lng) > 1e-6):
            return _json({"ok": False, "message": "No location on that one."})
        row = add(who, d.get("kind"), d.get("name"), lat, lng,
                  d.get("note"), d.get("photo"))
        log(f"[help] {row['player']} added a {row['kind']}: {row['name']!r} at "
            f"{row['lat']:.5f},{row['lng']:.5f}"
            + (f" (photo {row['photo']})" if row["photo"] else " (no photo)"))
        return _json({"ok": True, "wait_ms": cooldown_left(who),
                      "message": "Added. Look for it on the map."})

    if path == "/hc/mine":
        who = d.get("player")
        return _json({"rows": mine(who), "wait_ms": cooldown_left(who)})

    if path.startswith("/hc/photo/"):
        import urllib.parse as _up
        name = os.path.basename(_up.unquote(path[len("/hc/photo/"):]))
        fp = os.path.join(_photo_dir(), name)
        if name and os.path.isfile(fp):
            ext = os.path.splitext(name)[1].lower()
            ct = "image/png" if ext == ".png" else "image/jpeg"
            with open(fp, "rb") as fh:
                return 200, {"Content-Type": ct,
                             "Cache-Control": "public, max-age=3600"}, fh.read()
        return 404, {"Content-Type": "text/plain"}, b"no photo"

    return 404, {"Content-Type": "text/plain"}, b"no"
