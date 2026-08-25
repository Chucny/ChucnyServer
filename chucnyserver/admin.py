"""
"World Manager" -- local web UI for the PoGO private server.

Runs on http://127.0.0.1:<port> (localhost only). Allows setting PokeStops,
Gyms, and Pokemon spawns at real coordinates and adjusting global spawn settings.
Writes to places.json / events.json for server hot-reloading.
"""

import json
import threading
import urllib.parse
import urllib.request
import hashlib
import random
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import events as EV
import places as PL

# Items available in the Shop panel (id -> label)
GIVEABLE = [
    (1, "Poke Ball"), (2, "Great Ball"), (3, "Ultra Ball"),
    (101, "Potion"), (102, "Super Potion"), (103, "Hyper Potion"),
    (104, "Max Potion"), (201, "Revive"), (202, "Max Revive"),
    (701, "Razz Berry"), (401, "Incense"), (301, "Lucky Egg"),
    (501, "Lure Module"), (902, "Egg Incubator")
]

# Shop inventory with 2016 prices (sku, label, item_id, count, price)
SHOP = [
    ("pokeball.20",   "20 x Poke Ball",     1,  20,  100),
    ("pokeball.100",  "100 x Poke Ball",    1, 100,  460),
    ("pokeball.200",  "200 x Poke Ball",    1, 200,  800),
    ("greatball.20",  "20 x Great Ball",    2,  20,  200),
    ("ultraball.10",  "10 x Ultra Ball",    3,  10,  300),
    ("potion.20",     "20 x Potion",      101,  20,  200),
    ("revive.10",     "10 x Revive",      201,  10,  200),
    ("razz.20",       "20 x Razz Berry",  701,  20,  150),
    ("incense.1",     "1 x Incense",      401,   1,   80),
    ("incense.8",     "8 x Incense",      401,   8,  500),
    ("luckyegg.1",    "1 x Lucky Egg",    301,   1,   80),
    ("luckyegg.8",    "8 x Lucky Egg",    301,   8,  500),
    ("lure.1",        "1 x Lure Module",  501,   1,  100),
    ("lure.8",        "8 x Lure Module",  501,   8,  680),
    ("incubator.1",   "1 x Egg Incubator", 902,  1,  150),
]

# Kanto species names for the picker (index 0 unused)
DEX = [""] + """Bulbasaur Ivysaur Venusaur Charmander Charmeleon Charizard Squirtle Wartortle
Blastoise Caterpie Metapod Butterfree Weedle Kakuna Beedrill Pidgey Pidgeotto Pidgeot Rattata
Raticate Spearow Fearow Ekans Arbok Pikachu Raichu Sandshrew Sandslash NidoranF Nidorina
Nidoqueen NidoranM Nidorino Nidoking Clefairy Clefable Vulpix Ninetales Jigglypuff Wigglytuff
Zubat Golbat Oddish Gloom Vileplume Paras Parasect Venonat Venomoth Diglett Dugtrio Meowth
Persian Psyduck Golduck Mankey Primeape Growlithe Arcanine Poliwag Poliwhirl Poliwrath Abra
Kadabra Alakazam Machop Machoke Machamp Bellsprout Weepinbell Victreebel Tentacool Tentacruel
Geodude Graveler Golem Ponyta Rapidash Slowpoke Slowbro Magnemite Magneton Farfetchd Doduo
Dodrio Seel Dewgong Grimer Muk Shellder Cloyster Gastly Haunter Gengar Onix Drowzee Hypno
Krabby Kingler Voltorb Electrode Exeggcute Exeggutor Cubone Marowak Hitmonlee Hitmonchan
Lickitung Koffing Weezing Rhyhorn Rhydon Chansey Tangela Kangaskhan Horsea Seadra Goldeen
Seaking Staryu Starmie MrMime Scyther Jynx Electabuzz Magmar Pinsir Tauros Magikarp Gyarados
Lapras Ditto Eevee Vaporeon Jolteon Flareon Porygon Omanyte Omastar Kabuto Kabutops Aerodactyl
Snorlax Articuno Zapdos Moltres Dratini Dragonair Dragonite Mewtwo Mew""".split()

PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ChucnyServer World Manager</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
 :root {
   --bg: #f4f6f9;
   --card: #ffffff;
   --text: #1e293b;
   --text-muted: #64748b;
   --border: #e2e8f0;
   --primary: #2563eb;
   --primary-hover: #1d4ed8;
   --danger: #ef4444;
   --danger-hover: #dc2626;
   --success: #10b981;
   --warning: #f59e0b;
   --radius: 12px;
   --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
 }

 * { box-sizing: border-box; }
 body {
   margin: 0;
   background: var(--bg);
   color: var(--text);
   font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
   line-height: 1.5;
   padding-bottom: 40px;
 }

 header {
   background: var(--card);
   border-bottom: 1px solid var(--border);
   padding: 20px 24px;
   display: flex;
   justify-content: space-between;
   align-items: center;
   box-shadow: var(--shadow);
 }

 .brand-title {
   margin: 0;
   font-size: 24px;
   font-weight: 700;
   background: linear-gradient(135deg, #2563eb, #3b82f6);
   -webkit-background-clip: text;
   -webkit-text-fill-color: transparent;
 }

 .status-badge {
   display: inline-flex;
   align-items: center;
   gap: 6px;
   background: #ecfdf5;
   color: #047857;
   font-weight: 600;
   border-radius: 20px;
   padding: 4px 12px;
   font-size: 12px;
   border: 1px solid #a7f3d0;
 }

 .status-dot {
   width: 8px;
   height: 8px;
   background: var(--success);
   border-radius: 50%;
   display: inline-block;
 }

 .container {
   max-width: 1200px;
   margin: 24px auto;
   padding: 0 16px;
   display: grid;
   grid-template-columns: 1fr;
   gap: 20px;
 }

 .card {
   background: var(--card);
   border: 1px solid var(--border);
   border-radius: var(--radius);
   padding: 20px;
   box-shadow: var(--shadow);
 }

 .card-title {
   font-size: 18px;
   font-weight: 600;
   margin: 0 0 16px 0;
   color: var(--text);
   display: flex;
   align-items: center;
   justify-content: space-between;
 }

 .grid-2 {
   display: grid;
   grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
   gap: 20px;
 }

 .controls-row {
   display: flex;
   gap: 10px;
   flex-wrap: wrap;
   align-items: center;
 }

 button, select, input {
   background: var(--card);
   border: 1px solid var(--border);
   color: var(--text);
   border-radius: 8px;
   padding: 8px 14px;
   font: inherit;
   font-size: 14px;
   outline: none;
   transition: all 0.15s ease-in-out;
 }

 button {
   font-weight: 500;
   cursor: pointer;
 }

 button:hover {
   border-color: #cbd5e1;
   background: #f8fafc;
 }

 button.btn-primary {
   background: var(--primary);
   color: white;
   border-color: var(--primary);
 }

 button.btn-primary:hover {
   background: var(--primary-hover);
   border-color: var(--primary-hover);
 }

 button.btn-danger {
   background: #fef2f2;
   color: var(--danger);
   border-color: #fecaca;
 }

 button.btn-danger:hover {
   background: var(--danger);
   color: white;
 }

 button.on {
   background: #eff6ff;
   color: var(--primary);
   border-color: #bfdbfe;
   font-weight: 600;
 }

 input[type="text"], input[type="number"], select {
   background: #f8fafc;
 }

 input[type="text"]:focus, input[type="number"]:focus, select:focus {
   border-color: var(--primary);
   background: #fff;
 }

 #map {
   height: 480px;
   width: 100%;
   border-radius: var(--radius);
   border: 1px solid var(--border);
   box-shadow: var(--shadow);
 }

 .hint {
   font-size: 13px;
   color: var(--text-muted);
   margin-top: 8px;
 }

 .list {
   max-height: 250px;
   overflow-y: auto;
   display: flex;
   flex-direction: column;
   gap: 8px;
 }

 .row {
   display: flex;
   align-items: center;
   justify-content: space-between;
   background: #f8fafc;
   border: 1px solid var(--border);
   border-radius: 8px;
   padding: 10px 14px;
   font-size: 13px;
 }

 .row .t { color: var(--text); font-weight: 500; }
 .row .x { color: var(--danger); cursor: pointer; font-weight: 600; padding: 2px 6px; }
 .row .x:hover { text-decoration: underline; }

 .tag {
   border-radius: 6px;
   padding: 3px 8px;
   font-size: 11px;
   font-weight: 600;
   text-transform: uppercase;
   letter-spacing: 0.05em;
 }
 .stop { background: #e0f2fe; color: #0369a1; }
 .gym { background: #ffe4e6; color: #be123c; }
 .mon { background: #dcfce7; color: #15803d; }

 .empty {
   color: var(--text-muted);
   text-align: center;
   padding: 20px;
   font-size: 14px;
 }

 .alert-warning {
   background: #fffbeb;
   border: 1px solid #fde68a;
   color: #b45309;
   border-radius: var(--radius);
   padding: 14px 18px;
   font-size: 14px;
   margin-bottom: 20px;
 }

 .stats-bar {
   display: flex;
   gap: 24px;
   font-size: 14px;
   color: var(--text-muted);
 }

 .stats-bar strong {
   color: var(--text);
 }
</style></head><body>

<header>
  <div>
    <h1 class="brand-title">ChucnyServer</h1>
    <div class="hint" style="margin:2px 0 0">World &amp; Event Management Portal</div>
  </div>
  <div style="text-align: right;">
    <div class="status-badge"><span class="status-dot"></span> <span id="status">RUNNING</span></div>
  </div>
</header>

<div class="container">

  <div id="warn" class="alert-warning" style="display:none;">
    <strong>No Gyms in your world.</strong> Random stops/gyms are OFF. Select <strong>Gym</strong> below and click on the map to add one.
  </div>

  <div class="card">
    <div class="card-title">
      <span>Interactive World Map</span>
      <div class="stats-bar">
        <span>Placed Objects: <strong id="cnt">0</strong></span>
        <span>Details: <strong id="counts">0 stops</strong></span>
      </div>
    </div>

    <div class="controls-row" style="margin-bottom: 14px;">
      <button id="b-stop" class="on" onclick="setMode('stop')">PokeStop</button>
      <button id="b-gym" onclick="setMode('gym')">Gym</button>
      <button id="b-mon" onclick="setMode('mon')">Pokemon</button>
      <select id="species"></select>
      <input id="pname" placeholder="Name (optional)" size="14">
      <input id="pimg" placeholder="Photo path/URL" size="18">
      <button onclick="togProc('forts')" id="b-pf">Random Stops: OFF</button>
      <button onclick="togProc('spawns')" id="b-ps">Random Pokemon: ON</button>
      <button class="btn-danger" onclick="clearAll()">Clear All</button>
    </div>

    <div id="map"></div>
    <div class="hint">Click anywhere on the map to place the selected element. Click existing markers to remove them.</div>
  </div>

  <div class="grid-2">

    <div class="card">
      <div class="card-title">Quick Build Ring</div>
      <div class="controls-row">
        <input id="ring-n" type="number" value="8" min="1" max="24" style="width: 70px" title="Stops count">
        <input id="ring-r" type="number" value="60" min="10" max="500" style="width: 80px" title="Radius meters">
        <button class="btn-primary" onclick="ring()">Build Ring Around Trainer</button>
      </div>
      <div class="hint">Creates a neat circle of stops (and a gym) at your trainer's position.</div>
    </div>

    <div class="card">
  <div class="card-title">Import High-Density POIs</div>
  <div class="controls-row">
    <input id="poi-lat" type="number" step="any" placeholder="Lat (e.g. 44.556)" style="width: 100px">
    <input id="poi-lng" type="number" step="any" placeholder="Lng (e.g. -49.007)" style="width: 100px">
    <input id="poi-r" type="number" value="3" min="0.1" max="50" step="0.1" style="width: 60px" title="Radius km">
    <span style="font-size:13px; color:var(--text-muted)">km</span>
    <input id="poi-limit" type="number" value="5000" min="100" max="10000" style="width: 75px" title="Max POIs Limit">
    <span style="font-size:13px; color:var(--text-muted)">Limit</span>
    <input id="poi-gym-chance" type="number" value="15" min="0" max="100" style="width: 60px" title="Gym Chance (%)">
    <span style="font-size:13px; color:var(--text-muted)">% Gyms</span>
    <input id="poi-min-dist" type="number" value="2" min="0" max="50" step="1" style="width: 70px" title="Minimum Distance Between POIs (meters)">
    <span style="font-size:13px; color:var(--text-muted)">Min Dist (m)</span>
    <button class="btn-primary" onclick="importPois()">Import</button>
  </div>
  <div class="hint" id="poihint">Imports nodes, ways, and relations from OSM including parks, art, and transit stops.</div>
</div>

  </div>

  <div class="grid-2">

    <div class="card">
      <div class="card-title">Raid Boss Management</div>
      <div class="controls-row" style="margin-bottom: 8px;">
        <button onclick="raidToggle()" id="b-raid">Raid: OFF</button>
        <select id="raid-mon"></select>
        <input id="raid-cp" type="number" value="3000" min="10" max="9999" style="width: 80px" placeholder="CP">
        <input id="raid-name" value="raid" size="8" title="Trainer name">
        <button class="btn-primary" onclick="raidSave()">Apply</button>
      </div>
      <div class="hint" id="raidhint">Spawns a raid boss defending every gym across the server.</div>
    </div>

    <div class="card">
      <div class="card-title">Shop &amp; Storage Upgrades</div>
      <div class="controls-row" style="margin-bottom: 12px;">
        <span>PokeCoins: <strong id="coins" style="color:var(--warning)">0</strong></span>
        <button onclick="buy('pokemon')" id="b-buypk">Pokemon Storage</button>
        <button onclick="buy('items')" id="b-buyit">Item Bag</button>
      </div>
      <div class="controls-row" id="shopitems" style="margin-bottom: 8px;"></div>
      <div class="hint" id="shophint">Buy items using PokeCoins earned by defending Gyms.</div>
      <div class="hint" id="buyhint"></div>
    </div>

  </div>

  <div class="grid-2">

    <div class="card">
      <div class="card-title">Player Rewards &amp; Password Reset</div>
      <div class="controls-row" style="margin-bottom: 8px;">
        <input id="giveuser" list="accounts" placeholder="Trainer Username (Blank = Active)" style="flex:1;">
        <datalist id="accounts"></datalist>
      </div>
      <div class="controls-row" style="margin-bottom: 8px;">
        <select id="giveitem" style="flex:1;"></select>
        <input id="giveqty" type="number" value="20" min="1" max="999" style="width: 70px;">
        <button class="btn-primary" onclick="give()">Give Items</button>
      </div>
      <div class="controls-row" style="margin-bottom: 8px;">
        <select id="givecandy" style="flex:1;"></select>
        <input id="givecandyqty" type="number" value="25" min="1" max="999" style="width: 70px;">
        <button class="btn-primary" onclick="giveCandy()">Give Candy</button>
      </div>
      <div class="controls-row" style="margin-bottom: 8px;">
        <input id="givedust" type="number" value="1000" min="1" max="999999" style="width: 80px;" title="Stardust">
        <button class="btn-primary" onclick="giveDust()">Give Stardust</button>
        <input id="givecoins" type="number" value="100" min="1" max="999999" style="width: 80px;" title="PokeCoins">
        <button class="btn-primary" onclick="giveCoins()">Give Coins</button>
      </div>
      <div class="controls-row" style="margin-bottom: 8px;">
        <input id="newpw" placeholder="New Password" style="width: 130px;">
        <button onclick="resetPw()">Reset PW</button>
      </div>
      <div class="hint" id="givehint"></div>
    </div>

    <div class="card">
      <div class="card-title">Event &amp; Global Spawn Controls</div>
      <div class="controls-row" id="presets" style="margin-bottom: 12px;"></div>
      <div class="controls-row">
        <input id="ev-name" placeholder="Event Name" size="12">
        <label style="font-size:13px; color:var(--text-muted)">Density: <input id="ev-density" type="number" min="0" max="60" style="width: 60px"></label>
        <select id="ev-mode">
          <option value="all">All 151</option>
          <option value="list">From List</option>
          <option value="single">Single Species</option>
        </select>
        <input id="ev-list" placeholder="1,4,7,25" size="10">
        <label style="font-size:13px; color:var(--text-muted)">CP Range: 
          <input id="ev-min" type="number" min="10" max="5000" style="width: 70px"> - 
          <input id="ev-max" type="number" min="10" max="5000" style="width: 70px">
        </label>
        <button class="btn-primary" onclick="saveEv()">Apply Event Config</button>
      </div>
    </div>

  </div>

  <div class="grid-2">
    <div class="card">
      <div class="card-title">Player Nominations</div>
      <div class="list" id="noms"><div class="empty">No nominations waiting.</div></div>
    </div>

    <div class="card">
      <div class="card-title">Placed Objects List</div>
      <div class="list" id="list"></div>
    </div>
  </div>

</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
let mode='stop', map, layer, data={forts:[],spawns:[]};
const $=i=>document.getElementById(i);
const DEX=__DEX__;

function setMode(m){mode=m;['stop','gym','mon'].forEach(k=>$('b-'+k).className=(k===m?'on':''));}
function icon(color,txt){return L.divIcon({className:'',html:
 `<div style="background:${color};border:2px solid #fff;border-radius:50%;width:26px;height:26px;
   display:flex;align-items:center;justify-content:center;font:700 11px sans-serif;color:#fff;
   box-shadow:0 2px 5px rgba(0,0,0,0.2)">${txt}</div>`, iconSize:[26,26], iconAnchor:[13,13]});}

let player={lat:0,lng:0};
async function ring(){
  if(!player.lat){alert('No trainer position available - open the game first or click the map.');return;}
  await post('/api/ring',{lat:player.lat,lng:player.lng,count:+$('ring-n').value,
    radius_m:+$('ring-r').value,gym:true});
  load();
}



async function importPois(){
  const lat = parseFloat($('poi-lat').value || player.lat);
  const lng = parseFloat($('poi-lng').value || player.lng);
  const r_km = parseFloat($('poi-r').value || 1.5);
  const limit = parseInt($('poi-limit').value || 5000);
  const gym_chance = parseFloat($('poi-gym-chance').value || 15) / 100.0;
  const min_dist_m = parseFloat($('poi-min-dist').value || 1.5);

  if(!lat || !lng){
    alert('Please enter latitude and longitude.');
    return;
  }
  $('poihint').textContent = 'Fetching high-density POIs from OpenStreetMap...';
  const r = await post('/api/fetch_pois', {
    lat: lat,
    lng: lng,
    radius_km: r_km,
    limit: limit,
    gym_chance: gym_chance,
    min_dist_m: min_dist_m
  });
  $('poihint').textContent = r.message || ('Imported ' + r.placed + ' Objects.');
  load();
}


async function saveEv(){
  await post('/api/save',{event_name:$('ev-name').value,spawn_density:+$('ev-density').value,
    species_mode:$('ev-mode').value,
    species_list:$('ev-list').value.split(',').map(x=>parseInt(x.trim())).filter(x=>x>=1&&x<=151),
    single_species:+$('species').value,min_cp:+$('ev-min').value,max_cp:+$('ev-max').value});
  load();
}
async function preset(n){await post('/api/preset',{name:n});load();}
function paintShop(coins){
  const box=$('shopitems'); box.innerHTML='';
  (SHOP).forEach(([sku,label,iid,cnt,price])=>{
    const b=document.createElement('button');
    b.textContent = label + ' (' + price + 'c)';
    b.disabled = coins < price;
    b.style.opacity = coins < price ? 0.45 : 1;
    b.onclick = ()=>buyItem(sku);
    box.appendChild(b);
  });
}
async function buyItem(sku){
  const r = await post('/api/buyitem', {sku: sku, player: $('giveuser').value});
  $('buyhint').textContent = (r.ok?'✓ ':'✗ ') + r.message;
  $('buyhint').style.color = r.ok ? 'var(--success)' : 'var(--danger)';
  load();
}
function raidPaint(r){
  $('b-raid').textContent = 'Raid: ' + (r.on ? 'ON' : 'OFF');
  $('b-raid').className = r.on ? 'btn-danger' : '';
  if(r.pokemon_id) $('raid-mon').value = r.pokemon_id;
  if(r.cp) $('raid-cp').value = r.cp;
  if(r.trainer) $('raid-name').value = r.trainer;
}
async function raidToggle(){
  const r = await post('/api/raid', {on: $('b-raid').textContent.indexOf('ON') < 0,
    pokemon_id:+$('raid-mon').value, cp:+$('raid-cp').value, trainer:$('raid-name').value});
  raidPaint(r); $('raidhint').textContent = r.message; load();
}
async function raidSave(){
  const r = await post('/api/raid', {pokemon_id:+$('raid-mon').value,
    cp:+$('raid-cp').value, trainer:$('raid-name').value});
  raidPaint(r); $('raidhint').textContent = r.message; load();
}
async function loadNoms(){
  const r = await post('/api/noms', {});
  const box = $('noms');
  if (!r.rows || !r.rows.length){
    box.innerHTML = '<div class="empty">No nominations waiting.</div>'; return;
  }
  box.innerHTML = '';
  r.rows.forEach(function(n){
    const d = document.createElement('div'); d.className='row';
    d.innerHTML = '<div><span class="tag ' + (n.kind==='gym'?'gym':'stop') + '">'
      + (n.kind==='gym'?'GYM':'STOP') + '</span> '
      + '<b>' + n.name + '</b> &mdash; <small style="color:var(--text-muted)">by ' + n.player
      + (n.note ? ' &middot; ' + n.note : '') + '</small></div>';
    const no = document.createElement('span');
    no.className='x'; no.textContent='Remove';
    no.onclick = function(){ resolveNom(n.id,'rejected'); };
    d.appendChild(no); box.appendChild(d);
  });
}
async function resolveNom(id, status){
  await post('/api/noms/resolve', {id: id, status: status});
  loadNoms(); load();
}
function giveResult(r){
  $('givehint').textContent = (r.ok?'✓ ':'✗ ') + r.message;
  $('givehint').style.color = r.ok ? 'var(--success)' : 'var(--danger)';
  load();
}
async function give(){
  giveResult(await post('/api/give',{player:$('giveuser').value,
    kind:'item', item_id:+$('giveitem').value, count:+$('giveqty').value}));
}
async function giveCandy(){
  giveResult(await post('/api/give',{player:$('giveuser').value,
    kind:'candy', pokemon_id:+$('givecandy').value, count:+$('givecandyqty').value}));
}
async function giveDust(){
  giveResult(await post('/api/give',{player:$('giveuser').value,
    kind:'stardust', count:+$('givedust').value}));
}
async function giveCoins(){
  giveResult(await post('/api/give',{player:$('giveuser').value,
    kind:'coins', count:+$('givecoins').value}));
}
async function resetPw(){
  const who = $('giveuser').value.trim();
  if(!who) return giveResult({ok:false, message:'Select a trainer first'});
  giveResult(await post('/api/setpw', {player: who, password: $('newpw').value}));
  $('newpw').value='';
}
async function buy(kind){
  const r=await post('/api/buy',{what:kind});
  $('shophint').textContent = (r.ok?'✓ ':'✗ ') + r.message;
  $('shophint').style.color = r.ok ? 'var(--success)' : 'var(--danger)';
  load();
}

async function load(){
  const j=await (await fetch('/api/world')).json();
  data=j.places; player=j.player; $('cnt').textContent=data.forts.length+data.spawns.length;
  const ngym=data.forts.filter(f=>f.kind==='gym').length;
  const nstop=data.forts.length-ngym;
  $('warn').style.display=(ngym===0&&!data.procedural_forts)?'block':'none';
  $('counts').textContent=nstop+' Stops / '+ngym+' Gyms / '+data.spawns.length+' Spawns';
  const st=j.storage||{};
  $('coins').textContent=st.coins||0;
  paintShop(st.coins||0);
  $('b-buypk').textContent='Pokemon storage: '+(st.pokemon_used||0)+'/'+(st.max_pokemon||0);
  $('b-buyit').textContent='Item bag: '+(st.items_used||0)+'/'+(st.max_items||0);
  $('b-pf').textContent='Random Stops: '+(data.procedural_forts?'ON':'OFF');
  $('b-ps').textContent='Random Pokemon: '+(data.procedural_spawns?'ON':'OFF');
  $('b-pf').className=data.procedural_forts?'on':'';
  $('b-ps').className=data.procedural_spawns?'on':'';
  const c=j.config;
  $('ev-name').value=c.event_name; $('ev-density').value=c.spawn_density;
  $('ev-mode').value=c.species_mode; $('ev-list').value=(c.species_list||[]).join(',');
  $('ev-min').value=c.min_cp; $('ev-max').value=c.max_cp;
  if(!$('presets').dataset.done){
    (j.presets||[]).forEach(n=>{const b=document.createElement('button');
      b.textContent=n;b.onclick=()=>preset(n);$('presets').appendChild(b);});
    $('presets').dataset.done='1';
  }
  if(!map){
    map=L.map('map').setView([j.player.lat||39.19,j.player.lng||-96.58], j.player.lat?18:16);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,
      attribution:'&copy; OpenStreetMap'}).addTo(map);
    layer=L.layerGroup().addTo(map);
    map.on('click',e=>place(e.latlng.lat,e.latlng.lng));
    if(j.player.lat) L.circleMarker([j.player.lat,j.player.lng],{radius:7,color:'#2563eb',
      fillColor:'#3b82f6',fillOpacity:1}).addTo(map).bindTooltip('Trainer Position');
  }
  draw();
}
function draw(){
  layer.clearLayers();
  data.forts.forEach(f=>L.marker([f.lat,f.lng],{icon:icon(f.kind==='gym'?'#ef4444':'#2563eb',
    f.kind==='gym'?'G':'S')}).addTo(layer).bindTooltip(f.name).on('click',()=>del(f.id)));
  data.spawns.forEach(s=>L.marker([s.lat,s.lng],{icon:icon(s.pokemon_id?'#10b981':'#8b5cf6',s.pokemon_id?String(s.pokemon_id):'?')})
    .addTo(layer).bindTooltip(s.pokemon_id?(DEX[s.pokemon_id]||('#'+s.pokemon_id)):'Random').on('click',()=>del(s.id)));
  const rows=[...data.forts.map(f=>({id:f.id,cls:f.kind==='gym'?'gym':'stop',
      tag:f.kind==='gym'?'GYM':'STOP',
      t:`${f.name}${f.image?' [photo]':''} — ${f.lat.toFixed(5)}, ${f.lng.toFixed(5)}`})),
    ...data.spawns.map(s=>({id:s.id,cls:'mon',tag:s.pokemon_id?'MON':'RANDOM',
      t:`${s.pokemon_id?(DEX[s.pokemon_id]||('#'+s.pokemon_id)):'Random Pokemon'} — ${s.lat.toFixed(5)}, ${s.lng.toFixed(5)}`}))];
  $('list').innerHTML = rows.length ? rows.map(r=>
    `<div class="row"><div><span class="tag ${r.cls}">${r.tag}</span> <span class="t">${r.t}</span></div>
     <span class="x" onclick="del('${r.id}')">Remove</span></div>`).join('')
    : '<div class="empty">Nothing placed yet — click the map above.</div>';
}
async function post(u,b){return (await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify(b||{})})).json();}
async function place(lat,lng){
  const name=$('pname').value;
  if(mode==='mon') await post('/api/spawn',{lat,lng,pokemon_id:+$('species').value,name});
  else await post('/api/fort',{lat,lng,kind:mode,name,image:$('pimg').value});
  load();
}
async function del(id){await post('/api/remove',{id});load();}
async function clearAll(){if(confirm('Remove every placed object?')){await post('/api/clear',{});load();}}
async function togProc(what){
  const cur = what==='forts' ? data.procedural_forts : data.procedural_spawns;
  await post('/api/procedural',{on:!cur, what}); load();
}
const SHOP = __SHOP__;
(__GIVEABLE__).forEach(([id,label])=>{const o=document.createElement('option');
  o.value=id;o.textContent=label;$('giveitem').appendChild(o);});
DEX.forEach((n,i)=>{if(i){const o=document.createElement('option');o.value=i;
  o.textContent=n+' candy';$('givecandy').appendChild(o);}});
$('givecandy').value=25;
DEX.forEach((n,i)=>{if(i){const o=document.createElement('option');o.value=i;
  o.textContent=i+' '+n;$('raid-mon').appendChild(o);}});
$('raid-mon').value=150;
post('/api/raid',{}).then(raidPaint);
post('/api/accounts',{}).then(r=>{(r.accounts||[]).forEach(n=>{
  const o=document.createElement('option');o.value=n;$('accounts').appendChild(o);});});
{const o=document.createElement('option');o.value=0;
 o.textContent='Random Pokemon';$('species').appendChild(o);}
DEX.forEach((n,i)=>{if(i){const o=document.createElement('option');o.value=i;
  o.textContent=i+' '+n;$('species').appendChild(o);}});
$('species').value=0;
load(); loadNoms(); setInterval(load, 15000); setInterval(loadNoms, 20000);
</script></body></html>"""


def fetch_overpass_pois(lat: float, lng: float, radius_m: float = 3000.0, limit: int = 10000, gym_chance: float = 0.0, min_dist_m: float = 50.0) -> int:
    """Broadly queries OpenStreetMap via Overpass API for nodes, ways, and relations,
    extracting features (parks, art, transport, amenities) and photos.
    """
    import math

    def haversine_distance(lat1, lon1, lat2, lon2):
        """Calculate the great-circle distance between two points on the Earth."""
        R = 6371000  # Radius of Earth in meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    # Existing POI locations tracking
    existing_locations = [(f.get("lat"), f.get("lng")) for f in PL.get()["forts"]]
    
    query = f"""
    [out:json][timeout:90];
    (
      // 1. Core Points of Interest (Expanded)
      nwr(around:{radius_m},{lat},{lng})["amenity"];
      nwr(around:{radius_m},{lat},{lng})["leisure"];
      nwr(around:{radius_m},{lat},{lng})["tourism"];
      nwr(around:{radius_m},{lat},{lng})["historic"];
      nwr(around:{radius_m},{lat},{lng})["shop"];
      nwr(around:{radius_m},{lat},{lng})["man_made"];
      nwr(around:{radius_m},{lat},{lng})["craft"];

      // 2. Micro-Features & Street Furniture (Massive Density Boost)
      nwr(around:{radius_m},{lat},{lng})["amenity"="bench"];
      nwr(around:{radius_m},{lat},{lng})["amenity"="shelter"];
      nwr(around:{radius_m},{lat},{lng})["amenity"="post_box"];
      nwr(around:{radius_m},{lat},{lng})["amenity"="bicycle_parking"];
      nwr(around:{radius_m},{lat},{lng})["leisure"="picnic_table"];
      nwr(around:{radius_m},{lat},{lng})["tourism"="picnic_site"];
      nwr(around:{radius_m},{lat},{lng})["tourism"="viewpoint"];

      // 3. Specific Landmarks, Gates, and Elements
      nwr(around:{radius_m},{lat},{lng})["barrier"="gate"];
      nwr(around:{radius_m},{lat},{lng})["barrier"="city_wall"];
      nwr(around:{radius_m},{lat},{lng})["natural"="tree"]["memorial"="yes"]; // Historic trees
      nwr(around:{radius_m},{lat},{lng})["natural"="stone"]; // Large prominent boulders
      nwr(around:{radius_m},{lat},{lng})["waterway"="waterfall"];

      // 4. Transportation Nodes
      nwr(around:{radius_m},{lat},{lng})["highway"="bus_stop"];
      nwr(around:{radius_m},{lat},{lng})["highway"="platform"];
      nwr(around:{radius_m},{lat},{lng})["railway"="station"];
      nwr(around:{radius_m},{lat},{lng})["railway"="tram_stop"];
    );
    out center {limit};"""

    url = "https://overpass-api.de/api/interpreter"
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "PoGOServer/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=35) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return 0

    placed = 0
    for elem in payload.get("elements", []):
        tags = elem.get("tags", {})

        # Nodes have lat/lon; ways and relations return center coords via 'out center'
        n_lat = elem.get("lat") or elem.get("center", {}).get("lat")
        n_lng = elem.get("lon") or elem.get("center", {}).get("lon")

        if n_lat is None or n_lng is None:
            continue

        # Check minimum distance condition
        if any(haversine_distance(n_lat, n_lng, elat, elng) < min_dist_m for elat, elng in existing_locations):
            continue

        # Extract name or synthesize a recognizable tag description if no name is specified
        name = tags.get("name")
        if not name:
            name_parts = [
                tags.get("amenity"), tags.get("leisure"), tags.get("tourism"),
                tags.get("historic"), tags.get("shop"), tags.get("man_made"),
                tags.get("highway")
            ]
            valid_parts = [p.replace("_", " ").title() for p in name_parts if p]
            name = valid_parts[0] if valid_parts else "Way Point"

        # Resolve image URL via direct tag or Wikimedia Commons hash resolver
        image = tags.get("image", "")
        if not image and "wikimedia_commons" in tags:
            commons_file = tags["wikimedia_commons"].replace("File:", "").strip()
            filename = commons_file.replace(" ", "_")
            # MD5 hash is required to fetch raw images direct from Wikipedia's upload server structure
            md5_hash = hashlib.md5(filename.encode('utf-8')).hexdigest()
            image = f"https://upload.wikimedia.org/wikipedia/commons/{md5_hash[0]}/{md5_hash[0:2]}/{urllib.parse.quote(filename)}"

        # Enforce dynamic gym probability based on admin UI input
        kind = "gym" if (gym_chance > 0 and random.random() < gym_chance) else "stop"
        
        PL.add_fort(n_lat, n_lng, kind, name, image)
        placed += 1
        existing_locations.append((n_lat, n_lng))

    return placed


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, "application/json", json.dumps(obj))

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":
            return self._send(200, "text/html; charset=utf-8",
                              PAGE.replace("__DEX__", json.dumps(DEX))
                                  .replace("__GIVEABLE__", json.dumps(GIVEABLE))
                                  .replace("__SHOP__", json.dumps(SHOP)))
        if p == "/api/world":
            try:
                import rpc
                lat, lng = rpc._last_loc[0], rpc._last_loc[1]
            except Exception:
                lat, lng = 0.0, 0.0
            import settings as CFG, world
            return self._json({"places": PL.get(), "config": EV.get(),
                               "presets": list(EV.PRESETS),
                               "storage": world.storage(),
                               "prices": {
                                   "pokemon_step": CFG.get("storage", "pokemon_upgrade_step"),
                                   "pokemon_cost": CFG.get("storage", "pokemon_upgrade_cost"),
                                   "items_step": CFG.get("storage", "items_upgrade_step"),
                                   "items_cost": CFG.get("storage", "items_upgrade_cost")},
                               "player": {"lat": lat, "lng": lng}})
        self._send(404, "text/plain", "not found")

    def do_POST(self):
        p = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            d = {}
        try:
            if p == "/api/fetch_pois":
                lat = float(d.get("lat", 0.0))
                lng = float(d.get("lng", 0.0))
                radius_m = float(d.get("radius_m", 0.0))
                limit = int(d.get("limit", 5000))
                gym_chance = float(d.get("gym_chance", 0.0))
                if "radius_km" in d:
                    radius_m = float(d["radius_km"]) * 1000.0
                if radius_m <= 0:
                    radius_m = 3000.0
                count = fetch_overpass_pois(lat, lng, radius_m, limit, gym_chance)
                return self._json({"placed": count, "message": f"Successfully imported {count} Objects."})
            if p == "/api/fort":
                return self._json(PL.add_fort(d.get("lat"), d.get("lng"),
                                              d.get("kind", "stop"), d.get("name", ""),
                                              d.get("image", "")))
            if p == "/api/spawn":
                return self._json(PL.add_spawn(d.get("lat"), d.get("lng"),
                                               d.get("pokemon_id", 1), d.get("name", "")))
            if p == "/api/remove":
                return self._json({"removed": PL.remove(d.get("id", ""))})
            if p == "/api/clear":
                return self._json(PL.clear(d.get("what", "all")))
            if p == "/api/give":
                import contextlib as _ctx, world
                who = (d.get("player") or "").strip()
                kind = d.get("kind", "item")
                try:
                    ctx = world.acting_as(who) if who else _ctx.nullcontext()
                except KeyError:
                    return self._json({"ok": False,
                                       "message": f"no account called {who!r}"})
                try:
                    with ctx:
                        target = who or world.current().username
                        if kind == "stardust":
                            cnt = max(1, min(999999, int(d.get("count", 1))))
                            total = world.add_stardust(cnt)
                            msg = f"gave {target} {cnt} stardust (now {total})"
                        elif kind == "coins":
                            cnt = max(1, min(999999, int(d.get("count", 1))))
                            try:
                                total = world.add_coins(cnt)
                            except AttributeError:
                                # Fallback logic handling if standard add_coins is missing
                                world.spend_coins(-cnt)
                                total = world.COINS
                            msg = f"gave {target} {cnt} PokeCoins (now {total})"
                        elif kind == "candy":
                            import protocol as P
                            pid = int(d.get("pokemon_id", 0))
                            cnt = max(1, min(999, int(d.get("count", 1))))
                            if not 1 <= pid <= 151:
                                return self._json({"ok": False,
                                                   "message": "unknown Pokemon"})
                            fam = P.pokemon_family(pid)
                            total = world.add_candy(fam, cnt)
                            label = DEX[pid] if pid < len(DEX) else str(pid)
                            fam_label = DEX[fam] if fam < len(DEX) else str(fam)
                            msg = (f"gave {target} {cnt} {fam_label} candy "
                                   f"(now {total})")
                            if fam != pid:
                                msg += f" — {label}'s family"
                        else:
                            iid = int(d.get("item_id", 0))
                            cnt = max(1, min(999, int(d.get("count", 1))))
                            names = dict(GIVEABLE)
                            if iid not in names:
                                return self._json({"ok": False,
                                                   "message": "unknown item"})
                            total = world.add_item(iid, cnt)
                            msg = (f"gave {target} {cnt} x {names[iid]} "
                                   f"(now {total})")
                except KeyError:
                    return self._json({"ok": False,
                                       "message": f"no account called {who!r}"})
                return self._json({"ok": True, "message": msg})
            if p == "/api/noms":
                import helpcenter
                return self._json({"rows": helpcenter.recent()})
            if p == "/api/noms/resolve":
                import helpcenter
                row = helpcenter.resolve(d.get("id", ""), d.get("status", "rejected"))
                if not row:
                    return self._json({"ok": False, "message": "unknown nomination"})
                for f in list(PL.get()["forts"]):
                    if (abs(f["lat"] - row["lat"]) < 1e-6
                            and abs(f["lng"] - row["lng"]) < 1e-6):
                        PL.remove(f["id"])
                return self._json({"ok": True,
                                   "message": f"removed {row['name']!r}"})
            if p == "/api/setpw":
                import world
                who = (d.get("player") or "").strip()
                pw = d.get("password") or ""
                if not pw:
                    return self._json({"ok": False, "message": "pick a password"})
                if world.set_password(who, pw):
                    return self._json({"ok": True,
                                       "message": f"{who}'s password has been reset"})
                return self._json({"ok": False,
                                   "message": f"no account called {who!r}"})
            if p == "/api/buyitem":
                import contextlib as _ctx, world
                who = (d.get("player") or "").strip()
                entry = next((e for e in SHOP if e[0] == d.get("sku")), None)
                if not entry:
                    return self._json({"ok": False, "message": "unknown item"})
                _sku, label, iid, cnt, price = entry
                try:
                    ctx = world.acting_as(who) if who else _ctx.nullcontext()
                    ctx.__enter__()
                except KeyError:
                    return self._json({"ok": False,
                                       "message": f"no account called {who!r}"})
                try:
                    target = who or world.current().username
                    if world.room_in_bag() < cnt:
                        return self._json({"ok": False,
                                           "message": f"{target}'s bag has no room "
                                                      f"for {cnt} more items"})
                    if not world.spend_coins(price):
                        return self._json({"ok": False,
                                           "message": f"need {price} PokeCoins, "
                                                      f"{target} has {world.COINS}"})
                    total = world.add_item(iid, cnt)
                    return self._json({"ok": True,
                                       "message": f"bought {label} for {price}c "
                                                  f"-- {target} now has {total}",
                                       "coins": world.COINS})
                finally:
                    ctx.__exit__(None, None, None)
            if p == "/api/raid":
                import world
                if not d:
                    return self._json(world.raid())
                cfg, sent = world.set_raid(d.get("on"), d.get("pokemon_id"),
                                           d.get("cp"), d.get("trainer"))
                who = DEX[cfg["pokemon_id"]] if cfg["pokemon_id"] < len(DEX) else "?"
                msg = (f"Raid ON — {who} CP{cfg['cp']} is now defending every gym"
                       + (f"; {sent} defender(s) sent home" if sent else "")
                       if cfg["on"] else
                       "Raid off — gyms are back to normal and empty")
                return self._json(dict(cfg, message=msg))
            if p == "/api/accounts":
                import world
                return self._json({"accounts": world.account_names()})
            if p == "/api/buy":
                import world
                ok, message, new = world.buy_storage(
                    "pokemon" if d.get("what") == "pokemon" else "items")
                return self._json({"ok": ok, "message": message, "new": new})
            if p == "/api/procedural":
                return self._json(PL.set_procedural(d.get("on", True), d.get("what", "both")))
            if p == "/api/save":
                return self._json(EV.save(d))
            if p == "/api/preset":
                m = EV.apply_preset(d.get("name", ""))
                return self._json(m if m else {"error": "unknown preset"},
                                  200 if m else 400)
            if p == "/api/ring":
                import math
                lat = float(d.get("lat", 0.0)); lng = float(d.get("lng", 0.0))
                n = max(1, min(24, int(d.get("count", 8))))
                r_m = max(10.0, min(500.0, float(d.get("radius_m", 60))))
                gym = bool(d.get("gym", True))
                made = []
                for i in range(n):
                    a = 2 * math.pi * i / n
                    dlat = (r_m * math.cos(a)) / 111320.0
                    dlng = (r_m * math.sin(a)) / (111320.0 * max(0.2, math.cos(math.radians(lat))))
                    made.append(PL.add_fort(lat + dlat, lng + dlng, "stop", f"Ring Stop {i+1}"))
                if gym:
                    made.append(PL.add_fort(lat, lng, "gym", "Home Gym"))
                return self._json({"placed": len(made)})
        except Exception as e:
            return self._json({"error": str(e)}, 400)
        self._send(404, "text/plain", "not found")


def serve(port=8080, host="127.0.0.1"):
    ThreadingHTTPServer((host, port), _Handler).serve_forever()


def start(port=8080, host="127.0.0.1"):
    t = threading.Thread(target=serve, kwargs={"port": port, "host": host}, daemon=True)
    t.start()
    return t
