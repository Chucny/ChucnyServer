"""
chucnyserver Help Center & Wayfarer Portal
Handles in-game support redirection, PokéStop/Gym nominations, and photo storage.
"""

import base64
import json
import os
import sys
import threading
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

# Thread safety lock for JSON file state
_LOCK = threading.Lock()
ONE_DAY_MS = 24 * 60 * 60 * 1000


def _get_data_dir() -> str:
    """Returns the base directory for runtime dynamic storage."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


DATA_FILE = os.path.join(_get_data_dir(), "nominations.json")


# -----------------------------------------------------------------------------
# Storage Helpers
# -----------------------------------------------------------------------------

def _load_nominations() -> List[Dict[str, Any]]:
    """Loads nominations safely from disk."""
    if not os.path.isfile(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return [n for n in data.get("nominations", []) if isinstance(n, dict)]
    except (OSError, ValueError):
        return []


def _save_nominations(rows: List[Dict[str, Any]]) -> None:
    """Atomically writes nominations back to disk to prevent corrupt states."""
    tmp_path = DATA_FILE + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump({"nominations": rows}, fh, indent=2)
        os.replace(tmp_path, DATA_FILE)
    except OSError:
        pass


def _photo_dir() -> str:
    """Returns the photo upload directory from the active protocol context."""
    import protocol
    return protocol.PHOTO_DIR


def save_photo(data_url: str, nom_id: str) -> str:
    """Validates, decodes, and saves an uploaded base64 image string."""
    if not data_url or not data_url.startswith("data:image/"):
        return ""
    try:
        head, b64 = data_url.split(",", 1)
        ext = "jpg" if ("jpeg" in head or "jpg" in head) else "png"
        raw = base64.b64decode(b64)
        
        # Enforce 3MB maximum file payload
        if len(raw) > 3_000_000:
            return ""

        target_dir = _photo_dir()
        os.makedirs(target_dir, exist_ok=True)
        filename = f"{nom_id}.{ext}"
        
        with open(os.path.join(target_dir, filename), "wb") as fh:
            fh.write(raw)
            
        return filename
    except Exception:
        return ""


# -----------------------------------------------------------------------------
# Logic Functions
# -----------------------------------------------------------------------------

def last_nomination(player: str) -> int:
    """Gets the timestamp of the trainer's most recent nomination."""
    target_player = (player or "").strip().lower()
    if not target_player:
        return 0
        
    with _LOCK:
        times = [
            r.get("when", 0) for r in _load_nominations()
            if (r.get("player") or "").strip().lower() == target_player
        ]
    return max(times) if times else 0


def cooldown_left(player: str) -> int:
    """Returns remaining cooldown time in milliseconds before the player can nominate again."""
    last = last_nomination(player)
    if not last:
        return 0
    now = int(time.time() * 1000)
    return max(0, ONE_DAY_MS - (now - last))


def add(
    player: str,
    kind: str,
    name: str,
    lat: float,
    lng: float,
    note: str,
    photo_data: str = ""
) -> Dict[str, Any]:
    """Creates a new nomination and registers it into the world manager."""
    import places

    now_ms = int(time.time() * 1000)
    nom_id = f"nom-{now_ms}"
    photo_fn = save_photo(photo_data, nom_id)
    
    entry = {
        "id": nom_id,
        "player": (player or "").strip(),
        "kind": "gym" if kind == "gym" else "stop",
        "name": (name or "").strip()[:40] or "Unnamed Location",
        "lat": round(float(lat), 6),
        "lng": round(float(lng), 6),
        "note": (note or "").strip()[:200],
        "photo": photo_fn,
        "status": "approved",
        "when": now_ms
    }

    places.add_fort(
        entry["lat"], entry["lng"], entry["kind"], entry["name"], entry["photo"]
    )

    with _LOCK:
        rows = _load_nominations()
        rows.append(entry)
        _save_nominations(rows)

    return entry


def recent(n: int = 25) -> List[Dict[str, Any]]:
    """Fetches the N most recent nominations."""
    with _LOCK:
        return _load_nominations()[-n:]


def mine(player: str) -> List[Dict[str, Any]]:
    """Fetches up to 20 recent nominations for a given player."""
    target_player = (player or "").strip().lower()
    with _LOCK:
        return [
            r for r in _load_nominations()
            if (r.get("player") or "").strip().lower() == target_player
        ][-20:]


def resolve(nom_id: str, status: str) -> Optional[Dict[str, Any]]:
    """Updates status for a nomination record."""
    with _LOCK:
        rows = _load_nominations()
        for r in rows:
            if r.get("id") == nom_id:
                r["status"] = status
                r["resolved"] = int(time.time() * 1000)
                _save_nominations(rows)
                return dict(r)
    return None


# -----------------------------------------------------------------------------
# Front-End Web Page UI (Elegant Minimalist Black & White Niantic Styling)
# -----------------------------------------------------------------------------

PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
  <title>chucnyserver | Help Center</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <style>
    * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      color: #111111;
      background: #f7f7f8;
      min-height: 100vh;
    }
    header {
      background: #000000;
      color: #ffffff;
      padding: 24px 20px 20px;
      border-bottom: 3px solid #111111;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    header .brand {
      font-size: 11px;
      font-weight: 700;
      color: #888888;
      margin-bottom: 2px;
    }
    header h1 {
      margin: 0;
      font-size: 20px;
      font-weight: 900;
      letter-spacing: 0.05em;
    }
    .wrap {
      max-width: 520px;
      margin: 0 auto;
      padding: 20px 16px 40px;
    }
    .card {
      background: #ffffff;
      border: 1px solid #e1e1e6;
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 16px;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
    }
    .card h2 {
      margin: 0 0 6px;
      font-size: 15px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #000000;
    }
    .card p.sub {
      margin: 0 0 16px;
      font-size: 13px;
      color: #666666;
      line-height: 1.5;
    }
    label {
      display: block;
      font-size: 11px;
      font-weight: 800;
      color: #111111;
      margin: 16px 0 6px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    input[type=text], textarea {
      width: 100%;
      font: inherit;
      font-size: 15px;
      color: #000000;
      background: #fafafa;
      border: 1px solid #cccccc;
      border-radius: 6px;
      padding: 12px;
      transition: border-color 0.2s, background 0.2s;
    }
    input:focus, textarea:focus {
      outline: none;
      border-color: #000000;
      background: #ffffff;
    }
    textarea { min-height: 70px; resize: vertical; }
    
    .kinds { display: flex; gap: 8px; }
    .kinds button {
      flex: 1;
      padding: 12px;
      border-radius: 6px;
      border: 1px solid #cccccc;
      background: #fafafa;
      font: inherit;
      font-size: 13px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: #666666;
      cursor: pointer;
      transition: all 0.2s;
    }
    .kinds button.on {
      background: #000000;
      border-color: #000000;
      color: #ffffff;
    }
    #map {
      height: 240px;
      border-radius: 6px;
      margin-top: 6px;
      border: 1px solid #cccccc;
      background: #eeeeee;
    }
    .coords {
      font-size: 12px;
      color: #666666;
      margin-top: 8px;
      text-align: center;
    }
    .coords b { color: #000000; }
    
    .shot { display: flex; gap: 12px; align-items: center; margin-top: 6px; }
    .shot .prev {
      width: 72px;
      height: 72px;
      border-radius: 6px;
      flex: none;
      background: #f0f0f2 center/cover no-repeat;
      border: 1px dashed #aaaaaa;
      display: grid;
      place-items: center;
      color: #888888;
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      text-align: center;
    }
    .pick {
      flex: 1;
      border: 1px solid #000000;
      background: #ffffff;
      border-radius: 6px;
      padding: 12px;
      font: inherit;
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #000000;
      text-align: center;
      cursor: pointer;
      transition: background 0.2s;
    }
    .pick:active { background: #f0f0f0; }
    input[type=file] { display: none; }
    
    .go {
      width: 100%;
      margin-top: 20px;
      border: 2px solid #000000;
      border-radius: 6px;
      padding: 14px;
      font: inherit;
      font-weight: 900;
      font-size: 14px;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: #ffffff;
      background: #000000;
      cursor: pointer;
      transition: background 0.2s, color 0.2s;
    }
    .go:active { background: #333333; }
    .go[disabled] {
      background: #e0e0e0;
      border-color: #cccccc;
      color: #999999;
      cursor: not-allowed;
    }
    .quota {
      margin-top: 12px;
      text-align: center;
      font-size: 12px;
      font-weight: 600;
      color: #333333;
      background: #f0f0f0;
      border: 1px solid #dddddd;
      border-radius: 6px;
      padding: 10px;
    }
    
    .row {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 12px 0;
      border-bottom: 1px solid #eeeeee;
      font-size: 13px;
    }
    .row:last-child { border-bottom: 0; }
    .row .t { flex: 1; }
    .row .t small { display: block; color: #777777; font-size: 11px; margin-top: 2px; }
    .row .th {
      width: 40px;
      height: 40px;
      border-radius: 4px;
      background: #eeeeee center/cover no-repeat;
      flex: none;
      border: 1px solid #dddddd;
    }
    .pill {
      font-size: 10px;
      font-weight: 800;
      padding: 4px 8px;
      border-radius: 4px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      background: #000000;
      color: #ffffff;
    }
    .empty { color: #888888; font-size: 13px; text-align: center; padding: 16px 0; }
    
    #toast {
      position: fixed;
      left: 50%;
      bottom: 24px;
      transform: translate(-50%, 20px);
      background: #000000;
      color: #ffffff;
      padding: 12px 20px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.02em;
      max-width: 88vw;
      text-align: center;
      opacity: 0;
      transition: all 0.25s ease;
      pointer-events: none;
      z-index: 2000;
      box-shadow: 0 4px 16px rgba(0,0,0,0.2);
    }
    #toast.on { opacity: 1; transform: translate(-50%, 0); }
    #toast.bad { background: #000000; border: 1px solid #ff4444; color: #ff6666; }
  </style>
</head>
<body>

<header>
  <div class="brand">chucnyserver</div>
  <h1>Help Center</h1>
</header>

<div class="wrap">
  <div class="card">
    <h2>Submit Nomination</h2>
    <p class="sub">Position the map marker over the location, attach a photo, and submit directly to the server map.</p>

    <label>Type</label>
    <div class="kinds">
      <button id="k-stop" class="on" onclick="setKind('stop')">PokéStop</button>
      <button id="k-gym" onclick="setKind('gym')">Gym</button>
    </div>

    <label>Location</label>
    <div id="map"></div>
    <div class="coords" id="coords">Acquiring position&hellip;</div>

    <label>Photo</label>
    <div class="shot">
      <div class="prev" id="prev">No Image</div>
      <div class="pick" onclick="document.getElementById('file').click()">Select Photo</div>
      <input type="file" id="file" accept="image/*" onchange="pickPhoto(this)">
    </div>

    <label>Name</label>
    <input type="text" id="name" placeholder="e.g. Historic Fountain" maxlength="40">
    
    <label>Description</label>
    <textarea id="note" placeholder="Provide context about this location..." maxlength="200"></textarea>

    <label>Trainer Handle</label>
    <input type="text" id="who" placeholder="Trainer Name" autocapitalize="off" spellcheck="false">

    <button class="go" id="send" onclick="send()">Submit Nomination</button>
    <div class="quota" id="quota" style="display:none"></div>
  </div>

  <div class="card">
    <h2>Your Submissions</h2>
    <p class="sub">Recent nominations submitted under your handle.</p>
    <div id="list"><div class="empty">No submissions found.</div></div>
  </div>
</div>

<div id="toast"></div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
  const $ = id => document.getElementById(id);
  let kind = 'stop', pos = null, photo = '', map = null, marker = null;

  function setKind(k) {
    kind = k;
    $('k-stop').className = k === 'stop' ? 'on' : '';
    $('k-gym').className  = k === 'gym'  ? 'on' : '';
  }

  function toast(m, bad) {
    const t = $('toast');
    t.textContent = m;
    t.className = 'on' + (bad ? ' bad' : '');
    clearTimeout(t._t);
    t._t = setTimeout(() => { t.className = ''; }, 3000);
  }

  async function api(path, body) {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    });
    return r.json();
  }

  function showCoords() {
    $('coords').innerHTML = 'Pin at <b>' + pos.lat.toFixed(5) + ', ' + pos.lng.toFixed(5) + '</b> &mdash; drag map to adjust';
  }

  function initMap(lat, lng) {
    pos = { lat: lat, lng: lng };
    if (typeof L === 'undefined') {
      $('map').style.display = 'none';
      $('coords').innerHTML = 'Location set to <b>' + lat.toFixed(5) + ', ' + lng.toFixed(5) + '</b>';
      return;
    }
    map = L.map('map', { zoomControl: true }).setView([lat, lng], 18);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap'
    }).addTo(map);

    marker = L.marker([lat, lng], { draggable: true }).addTo(map);
    marker.on('dragend', () => {
      const p = marker.getLatLng();
      pos = { lat: p.lat, lng: p.lng };
      showCoords();
    });
    map.on('click', (e) => {
      marker.setLatLng(e.latlng);
      pos = { lat: e.latlng.lat, lng: e.latlng.lng };
      showCoords();
    });

    showCoords();
    setTimeout(() => { map.invalidateSize(); }, 200);
  }

  function pickPhoto(input) {
    const f = input.files && input.files[0];
    if (!f) return;
    const img = new Image(), rd = new FileReader();
    rd.onload = () => { img.src = rd.result; };
    img.onload = () => {
      const max = 640, sc = Math.min(1, max / Math.max(img.width, img.height));
      const c = document.createElement('canvas');
      c.width = Math.round(img.width * sc);
      c.height = Math.round(img.height * sc);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      photo = c.toDataURL('image/jpeg', 0.82);
      $('prev').style.backgroundImage = 'url(' + photo + ')';
      $('prev').textContent = '';
    };
    rd.readAsDataURL(f);
  }

  async function send() {
    if (!pos) return toast('Acquiring location details...', true);
    if (!$('who').value.trim()) return toast('Trainer handle required.', true);
    if (!photo) return toast('Photo attachment required.', true);

    $('send').disabled = true;
    const r = await api('/hc/nominate', {
      player: $('who').value.trim(),
      kind: kind,
      name: $('name').value,
      note: $('note').value,
      photo: photo,
      lat: pos.lat,
      lng: pos.lng
    });

    $('send').disabled = false;
    toast(r.message, !r.ok);

    if (r.ok) {
      $('name').value = '';
      $('note').value = '';
      photo = '';
      $('prev').style.backgroundImage = '';
      $('prev').textContent = 'No Image';
      refresh();
    }
    if (r.wait_ms) showQuota(r.wait_ms);
  }

  function showQuota(ms) {
    if (!ms) {
      $('quota').style.display = 'none';
      $('send').disabled = false;
      return;
    }
    const h = Math.floor(ms / 3600000);
    const m = Math.round((ms % 3600000) / 60000);
    $('quota').style.display = 'block';
    $('quota').textContent = 'Daily nomination limit reached. Next available in ' + (h ? h + 'h ' : '') + m + 'm.';
    $('send').disabled = true;
  }

  async function refresh() {
    const who = $('who').value.trim();
    if (!who) return;

    const r = await api('/hc/mine', { player: who });
    showQuota(r.wait_ms || 0);

    const box = $('list');
    if (!r.rows || !r.rows.length) {
      box.innerHTML = '<div class="empty">No submissions found.</div>';
      return;
    }

    box.innerHTML = '';
    r.rows.slice().reverse().forEach((n) => {
      const d = document.createElement('div');
      d.className = 'row';
      d.innerHTML =
        '<div class="th"' + (n.photo ? ' style="background-image:url(/hc/photo/' + encodeURIComponent(n.photo) + ')"' : '') + '></div>' +
        '<div class="t">' + n.name +
        '<small>' + (n.kind === 'gym' ? 'Gym' : 'PokéStop') + ' &middot; ' + n.lat.toFixed(4) + ', ' + n.lng.toFixed(4) + '</small></div>' +
        '<span class="pill">Active</span>';
      box.appendChild(d);
    });
  }

  $('who').addEventListener('change', refresh);

  (async function() {
    const r = await api('/hc/where', {});
    if (r.player && !$('who').value) $('who').value = r.player;
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (p) => { initMap(p.coords.latitude, p.coords.longitude); refresh(); },
        () => { initMap(r.lat || 0, r.lng || 0); refresh(); },
        { enableHighAccuracy: true, timeout: 8000 }
      );
    } else {
      initMap(r.lat || 0, r.lng || 0);
      refresh();
    }
  })();
</script>
</body>
</html>"""


# -----------------------------------------------------------------------------
# HTTP Router & Handler
# -----------------------------------------------------------------------------

def _json_response(obj: Any, code: int = 200) -> Tuple[int, Dict[str, str], bytes]:
    """Helper to format standard API JSON responses."""
    return (
        code,
        {"Content-Type": "application/json", "Cache-Control": "no-store"},
        json.dumps(obj).encode("utf-8")
    )


def handle(method: str, path: str, query: Any, headers: Any, body: bytes, log: Any) -> Tuple[int, Dict[str, str], bytes]:
    """Main request router for the help center sub-application."""
    if path in ("/", "/hc", "/hc/", "/hc/en-us", "/help"):
        return (
            200,
            {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
            PAGE.encode("utf-8")
        )

    try:
        data = json.loads(body.decode("utf-8")) if body else {}
    except ValueError:
        data = {}

    if path == "/hc/where":
        import rpc
        return _json_response({
            "lat": rpc._last_loc[0],
            "lng": rpc._last_loc[1],
            "player": rpc._last_user[0]
        })

    if path == "/hc/nominate":
        who = (data.get("player") or "").strip()
        if not who:
            return _json_response({"ok": False, "message": "Enter your trainer name."})
        
        wait = cooldown_left(who)
        if wait > 0:
            return _json_response({
                "ok": False,
                "wait_ms": wait,
                "message": "You've already added a place today."
            })

        try:
            lat = float(data.get("lat"))
            lng = float(data.get("lng"))
        except (TypeError, ValueError):
            return _json_response({"ok": False, "message": "No location specified."})

        if abs(lat) <= 1e-6 and abs(lng) <= 1e-6:
            return _json_response({"ok": False, "message": "No location specified."})

        row = add(
            who,
            data.get("kind"),
            data.get("name"),
            lat,
            lng,
            data.get("note"),
            data.get("photo")
        )

        log_photo = f" (photo {row['photo']})" if row["photo"] else " (no photo)"
        log(f"[help] {row['player']} added a {row['kind']}: {row['name']!r} at "
            f"{row['lat']:.5f},{row['lng']:.5f}{log_photo}")

        return _json_response({
            "ok": True,
            "wait_ms": cooldown_left(who),
            "message": "Added. Look for it on the map."
        })

    if path == "/hc/mine":
        who = data.get("player")
        return _json_response({
            "rows": mine(who),
            "wait_ms": cooldown_left(who)
        })

    if path.startswith("/hc/photo/"):
        raw_filename = path[len("/hc/photo/"):]
        name = os.path.basename(urllib.parse.unquote(raw_filename))
        filepath = os.path.join(_photo_dir(), name)

        if name and os.path.isfile(filepath):
            ext = os.path.splitext(name)[1].lower()
            content_type = "image/png" if ext == ".png" else "image/jpeg"
            with open(filepath, "rb") as fh:
                return (
                    200,
                    {
                        "Content-Type": content_type,
                        "Cache-Control": "public, max-age=3600"
                    },
                    fh.read()
                )
        return 404, {"Content-Type": "text/plain"}, b"no photo"

    return 404, {"Content-Type": "text/plain"}, b"no"
