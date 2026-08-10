"""
"World Manager" -- local web UI for the PoGO private server.

Runs on http://127.0.0.1:<port> (localhost only, never exposed to the phone or the
network). Lets you click a map to place PokeStops, Gyms and Pokemon spawns at real
coordinates, and tune the global spawn settings. Everything is written to
places.json / events.json, which the game server hot-reloads on the next map
refresh -- no restart needed.

The map tiles come from OpenStreetMap, so this page needs internet; the placement
controls and the coordinate list still work fine offline.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import events as EV
import places as PL

# Items you can hand yourself from the Shop panel (id -> label). These are the
# ones the 2016 client actually knows how to display in the bag.
# NOTE: 301 is the Lucky Egg and 501 is the Lure Module (Troy Disk). This list
# previously had 501 labelled "Lucky Egg" and 602 labelled "Lure Module" -- 602 is
# actually X Attack, so both of those handed out the wrong item.
GIVEABLE = [(1, "Poke Ball"), (2, "Great Ball"), (3, "Ultra Ball"),
            (101, "Potion"), (102, "Super Potion"), (103, "Hyper Potion"),
            (104, "Max Potion"), (201, "Revive"), (202, "Max Revive"),
            (701, "Razz Berry"), (401, "Incense"), (301, "Lucky Egg"),
            (501, "Lure Module"), (902, "Egg Incubator")]

# The shop, at the real 2016 PokeCoin prices. (sku, label, item_id, count, price)
# The in-game shop screen cannot work -- it prices everything through Google Play
# and our APK isn't a registered Play product -- so this is where you spend the
# coins your Gym defenders earn.
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
<title>PoGO World Manager</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
 *{box-sizing:border-box}
 body{margin:0;background:#22262b;color:#e9edf2;font-family:ui-monospace,Consolas,monospace}
 header{text-align:center;padding:18px 12px 10px}
 h1{margin:0;font-size:34px;letter-spacing:.06em;font-weight:800}
 .pill{display:inline-block;margin-top:10px;border:1px solid #3d4650;border-radius:6px;padding:7px 16px;color:#57d977;font-size:13px}
 .meta{margin-top:10px;font-size:12px;color:#9aa5b1;line-height:1.9}
 h2{text-align:center;font-size:20px;margin:16px 0 10px;font-weight:600}
 .bar{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;padding:0 12px 14px}
 .bar button,.bar select,.bar input{background:#2b3138;border:1px solid #3d4650;color:#e9edf2;
   border-radius:6px;padding:9px 14px;font:inherit;font-size:13px;cursor:pointer}
 .bar button.on{background:#2b6cf6;border-color:#2b6cf6;color:#fff}
 .bar button.danger{color:#ff9a9a}
 #map{height:52vh;min-height:320px;width:100%;background:#111}
 .hint{text-align:center;font-size:12px;color:#9aa5b1;padding:8px 12px}
 .list{max-width:900px;margin:0 auto 30px;padding:0 12px}
 .row{display:flex;align-items:center;gap:10px;background:#2b3138;border:1px solid #363d45;
   border-radius:6px;padding:8px 12px;margin-bottom:6px;font-size:13px}
 .row .t{flex:1;color:#c6d0da}
 .row .x{color:#ff9a9a;cursor:pointer;padding:2px 8px}
 .tag{border-radius:4px;padding:2px 7px;font-size:11px}
 .stop{background:#1d4e89}.gym{background:#8a2f3d}.mon{background:#1f6b45}
 .empty{color:#8892a0;text-align:center;padding:14px;font-size:13px}
</style></head><body>
<header>
  <h1>POGOSERVER</h1>
  <div class="pill" id="status">RUNNING</div>
  <div class="meta">
    PLACED OBJECTS: <b id="cnt">0</b><br>
    <span id="counts"></span><br>
    SPAWN MODE: <b id="mode">-</b>
  </div>
</header>

<div id="warn" style="display:none;max-width:760px;margin:0 auto 14px;padding:10px 14px;
  background:#3a2f14;border:1px solid #7a6320;border-radius:8px;color:#ffd98a;font-size:13px">
  <b>No Gyms in your world.</b> Random stops/gyms are OFF, so the only ones that exist are the
  ones you place. Choose <b>Gym</b> below and click the map (or use Build ring) &mdash; then you
  can tap it in game and station a Pokemon there.
</div>
<h2>World Manager</h2>
<div class="bar">
  <button id="b-stop" class="on" onclick="setMode('stop')">PokeStop</button>
  <button id="b-gym" onclick="setMode('gym')">Gym</button>
  <button id="b-mon" onclick="setMode('mon')">Pokemon</button>
  <select id="species"></select>
  <input id="pname" placeholder="Name (optional)" size="14">
  <input id="pimg" placeholder="Photo: file in photos/ or URL" size="20">
  <button onclick="togProc('forts')" id="b-pf">Random stops/gyms: OFF</button>
  <button onclick="togProc('spawns')" id="b-ps">Random Pokemon: ON</button>
  <button class="danger" onclick="clearAll()">Clear all</button>
</div>
<div id="map"></div>
<div class="hint">Click the map to place the selected object. Click a marker to remove it.
Changes apply live &mdash; walk around in game and they'll appear.</div>

<h2>Quick Build</h2>
<div class="bar">
  <span style="align-self:center;font-size:13px;color:#9aa5b1">Ring of stops around trainer:</span>
  <input id="ring-n" type="number" value="8" min="1" max="24" size="3" title="how many stops">
  <input id="ring-r" type="number" value="60" min="10" max="500" size="4" title="radius in metres">
  <button onclick="ring()">Build ring</button>
</div>

<h2>Shop</h2>
<div class="bar">
  <span style="align-self:center;font-size:13px;color:#9aa5b1">PokeCoins: <b id="coins" style="color:#ffd34d">0</b></span>
  <button onclick="buy('pokemon')" id="b-buypk">Pokemon storage</button>
  <button onclick="buy('items')" id="b-buyit">Item bag</button>
</div>
<div class="hint" id="shophint">Earn PokeCoins by leaving Pokemon to defend a Gym.
Upgrades apply in game straight away.</div>
<div class="bar" id="shopitems"></div>
<div class="hint" id="buyhint">The in-game shop screen prices everything through
Google Play, which a re-signed APK can't reach &mdash; so buy here instead. Items land
in your bag within a few seconds.</div>
<h2>Raid</h2>
<div class="bar">
  <button onclick="raidToggle()" id="b-raid">Raid: off</button>
  <select id="raid-mon"></select>
  <label style="align-self:center;font-size:12px;color:#9aa5b1">CP
    <input id="raid-cp" type="number" value="3000" min="10" max="9999" size="5"></label>
  <input id="raid-name" value="raid" size="8" title="trainer name shown at the gym">
  <button onclick="raidSave()">Apply</button>
</div>
<div class="hint" id="raidhint">Puts one boss in EVERY gym, replacing whatever is
defending (real defenders are sent home first, nothing is lost). Beat it and it drops
at your feet as a wild Pokemon you can catch — you have 10 minutes.</div>

<h2>Nominations</h2>
<div class="hint">Added by players from the in-game Help Center
(Settings &rarr; support). These go straight into the world &mdash; one per player
per day. Remove one here if it shouldn't be there.</div>
<div class="list" id="noms"><div class="empty">No nominations waiting.</div></div>

<h2>Give to a player</h2>
<div class="bar">
  <span style="align-self:center;font-size:13px;color:#9aa5b1">Trainer</span>
  <input id="giveuser" list="accounts" placeholder="username" size="14"
         title="Leave blank for the trainer currently playing">
  <datalist id="accounts"></datalist>
  <span class="hint" style="align-self:center">Blank = whoever is playing now</span>
</div>
<div class="bar">
  <select id="giveitem"></select>
  <input id="giveqty" type="number" value="20" min="1" max="999" size="4">
  <button onclick="give()">Add items</button>
</div>
<div class="bar">
  <select id="givecandy"></select>
  <input id="givecandyqty" type="number" value="25" min="1" max="999" size="4">
  <button onclick="giveCandy()">Add candy</button>
</div>
<div class="bar">
  <input id="givedust" type="number" value="1000" min="1" max="999999" size="7">
  <button onclick="giveDust()">Add stardust</button>
</div>
<div class="bar">
  <input id="newpw" placeholder="New password" size="14">
  <button onclick="resetPw()">Reset password</button>
</div>
<div class="hint" id="givehint">Candy goes to the whole evolution family, so Charmander
candy also powers up Charmeleon and Charizard. Everything shows up in game within a
few seconds.</div>

<h2>Events</h2>
<div class="bar" id="presets"></div>
<div class="bar">
  <input id="ev-name" placeholder="Event name" size="14">
  <label style="align-self:center;font-size:12px;color:#9aa5b1">Density
    <input id="ev-density" type="number" min="0" max="60" size="3"></label>
  <select id="ev-mode">
    <option value="all">All 151</option><option value="list">From list</option>
    <option value="single">One species</option>
  </select>
  <input id="ev-list" placeholder="1,4,7,25" size="12" title="species list">
  <label style="align-self:center;font-size:12px;color:#9aa5b1">CP
    <input id="ev-min" type="number" min="10" max="5000" size="4"> &ndash;
    <input id="ev-max" type="number" min="10" max="5000" size="4"></label>
  <button onclick="saveEv()">Apply event</button>
</div>
<div class="hint">Density = wild Pokemon around you (0&ndash;60). "One species" + a
Pokemon makes a themed event, e.g. a Pikachu festival.</div>

<div class="list" id="list"></div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
let mode='stop', map, layer, data={forts:[],spawns:[]};
const $=i=>document.getElementById(i);
const DEX=__DEX__;

function setMode(m){mode=m;['stop','gym','mon'].forEach(k=>$('b-'+k).className=(k===m?'on':''));}
function icon(color,txt){return L.divIcon({className:'',html:
 `<div style="background:${color};border:2px solid #fff;border-radius:50%;width:26px;height:26px;
   display:flex;align-items:center;justify-content:center;font:700 11px monospace;color:#fff;
   box-shadow:0 1px 4px rgba(0,0,0,.5)">${txt}</div>`, iconSize:[26,26], iconAnchor:[13,13]});}

let player={lat:0,lng:0};
async function ring(){
  if(!player.lat){alert('No trainer position yet - open the game first, or click the map to place manually.');return;}
  await post('/api/ring',{lat:player.lat,lng:player.lng,count:+$('ring-n').value,
    radius_m:+$('ring-r').value,gym:true});
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
    b.textContent = label + '  —  ' + price + 'c';
    b.disabled = coins < price;
    b.style.opacity = coins < price ? 0.45 : 1;
    b.onclick = ()=>buyItem(sku);
    box.appendChild(b);
  });
}
async function buyItem(sku){
  const r = await post('/api/buyitem', {sku: sku, player: $('giveuser').value});
  $('buyhint').textContent = (r.ok?'✓ ':'✗ ') + r.message;
  $('buyhint').style.color = r.ok ? '#7fd1a6' : '#ff9a9a';
  load();
}
function raidPaint(r){
  $('b-raid').textContent = 'Raid: ' + (r.on ? 'ON' : 'off');
  $('b-raid').style.background = r.on ? '#8a2b2b' : '';
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
    box.innerHTML = '<div class="empty">Nothing added yet.</div>'; return;
  }
  box.innerHTML = '';
  r.rows.forEach(function(n){
    const d = document.createElement('div'); d.className='row';
    d.innerHTML = '<span class="tag ' + (n.kind==='gym'?'gym':'stop') + '">'
      + (n.kind==='gym'?'GYM':'STOP') + '</span>'
      + '<span class="t"><b>' + n.name + '</b> &mdash; ' + n.lat.toFixed(5) + ', '
      + n.lng.toFixed(5) + '<br><small style="color:#8892a0">by ' + n.player
      + (n.note ? ' &middot; ' + n.note : '') + '</small></span>';
    const no = document.createElement('span');
    no.className='x'; no.textContent='remove';
    no.onclick = function(){ resolveNom(n.id,'rejected'); };
    d.appendChild(no); box.appendChild(d);
  });
}
async function resolveNom(id, status){
  const r = await post('/api/noms/resolve', {id: id, status: status});
  loadNoms(); load();
}
function giveResult(r){
  $('givehint').textContent = (r.ok?'\u2713 ':'\u2717 ') + r.message;
  $('givehint').style.color = r.ok ? '#7fd1a6' : '#ff9a9a';
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
async function resetPw(){
  const who = $('giveuser').value.trim();
  if(!who) return giveResult({ok:false, message:'Type which trainer first'});
  giveResult(await post('/api/setpw', {player: who, password: $('newpw').value}));
  $('newpw').value='';
}
async function giveDust(){
  giveResult(await post('/api/give',{player:$('giveuser').value,
    kind:'stardust', count:+$('givedust').value}));
}
async function buy(kind){
  const r=await post('/api/buy',{what:kind});
  $('shophint').textContent = (r.ok?'\u2713 ':'\u2717 ') + r.message;
  $('shophint').style.color = r.ok ? '#7fd1a6' : '#ff9a9a';
  load();
}

async function load(){
  const j=await (await fetch('/api/world')).json();
  data=j.places; player=j.player; $('cnt').textContent=data.forts.length+data.spawns.length;
  const ngym=data.forts.filter(f=>f.kind==='gym').length;
  const nstop=data.forts.length-ngym;
  $('warn').style.display=(ngym===0&&!data.procedural_forts)?'block':'none';
  $('counts').textContent=nstop+' PokeStops / '+ngym+' Gyms / '+data.spawns.length+' spawn points';
  const st=j.storage||{};
  $('coins').textContent=st.coins||0;
  paintShop(st.coins||0);
  $('b-buypk').textContent='Pokemon storage: '+(st.pokemon_used||0)+'/'+(st.max_pokemon||0)
    +'  (+'+(j.prices?j.prices.pokemon_step:0)+' for '+(j.prices?j.prices.pokemon_cost:0)+')';
  $('b-buyit').textContent='Item bag: '+(st.items_used||0)+'/'+(st.max_items||0)
    +'  (+'+(j.prices?j.prices.items_step:0)+' for '+(j.prices?j.prices.items_cost:0)+')';
  $('mode').textContent=j.config.event_name+' / density '+j.config.spawn_density;
  $('b-pf').textContent='Random stops/gyms: '+(data.procedural_forts?'ON':'OFF');
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
    if(j.player.lat) L.circleMarker([j.player.lat,j.player.lng],{radius:7,color:'#ffd34d',
      fillColor:'#ffd34d',fillOpacity:1}).addTo(map).bindTooltip('Trainer');
  }
  draw();
}
function draw(){
  layer.clearLayers();
  data.forts.forEach(f=>L.marker([f.lat,f.lng],{icon:icon(f.kind==='gym'?'#c0392b':'#2b6cf6',
    f.kind==='gym'?'G':'S')}).addTo(layer).bindTooltip(f.name).on('click',()=>del(f.id)));
  data.spawns.forEach(s=>L.marker([s.lat,s.lng],{icon:icon(s.pokemon_id?'#1f9d55':'#7a5cc4',s.pokemon_id?String(s.pokemon_id):'?')})
    .addTo(layer).bindTooltip(s.pokemon_id?(DEX[s.pokemon_id]||('#'+s.pokemon_id)):'Random').on('click',()=>del(s.id)));
  const rows=[...data.forts.map(f=>({id:f.id,cls:f.kind==='gym'?'gym':'stop',
      tag:f.kind==='gym'?'GYM':'STOP',
      t:`${f.name}${f.image?' [photo]':''} — ${f.lat.toFixed(5)}, ${f.lng.toFixed(5)}`})),
    ...data.spawns.map(s=>({id:s.id,cls:'mon',tag:s.pokemon_id?'MON':'RANDOM',
      t:`${s.pokemon_id?(DEX[s.pokemon_id]||('#'+s.pokemon_id)):'Random Pokemon'} — ${s.lat.toFixed(5)}, ${s.lng.toFixed(5)}`}))];
  $('list').innerHTML = rows.length ? rows.map(r=>
    `<div class="row"><span class="tag ${r.cls}">${r.tag}</span><span class="t">${r.t}</span>
     <span class="x" onclick="del('${r.id}')">remove</span></div>`).join('')
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
            import world, settings as CFG
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
                import world
                import contextlib as _ctx
                who = (d.get("player") or "").strip()
                kind = d.get("kind", "item")
                # Blank means "whoever is playing right now", which keeps the old
                # one-click behaviour. A name is validated against existing saves
                # so a typo can't quietly create an empty account.
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
                # Places are added straight away now, so "resolve" only ever
                # means taking one back out again.
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
                import world, contextlib as _ctx
                who = (d.get("player") or "").strip()
                entry = next((e for e in SHOP if e[0] == d.get("sku")), None)
                if not entry:
                    return self._json({"ok": False, "message": "unknown item"})
                _sku, label, iid, cnt, price = entry
                # acting_as is a context manager: a bad username raises on
                # __enter__, i.e. at the `with`, not where it's constructed.
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
                if not d:                      # plain read
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
                # furnish a whole neighbourhood in one click: a ring of PokeStops
                # (plus an optional Gym) around a centre point
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
