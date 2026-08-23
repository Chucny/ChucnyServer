let mode='stop', map, layer, playerMarker, data={forts:[],spawns:[]};
const $=i=>document.getElementById(i);
const DEX=__DEX__;

function setMode(m){mode=m;['stop','gym','mon','teleport'].forEach(k=>$('b-'+k).className=(k===m?'on':''));}
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
  const r_km = parseFloat($('poi-r').value || 3);
  const limit = parseInt($('poi-limit').value || 5000);
  const gym_chance = parseFloat($('poi-gym-chance').value || 0) / 100.0;
  if(!lat || !lng){alert('Please enter latitude and longitude.'); return;}
  $('poihint').textContent = 'Fetching high-density POIs from OpenStreetMap...';
  const r = await post('/api/fetch_pois', {lat: lat, lng: lng, radius_km: r_km, limit: limit, gym_chance: gym_chance});
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
  data=j.places;
  const selected=$('giveuser').value.trim();
  player=selected && j.teleports[selected]
    ? {lat:j.teleports[selected][0],lng:j.teleports[selected][1]} : j.player;
  $('cnt').textContent=data.forts.length+data.spawns.length;
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
    map=L.map('map').setView([player.lat||39.19,player.lng||-96.58], player.lat?18:16);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,
      attribution:'&copy; OpenStreetMap'}).addTo(map);
    layer=L.layerGroup().addTo(map);
    map.on('click',e=>place(e.latlng.lat,e.latlng.lng));
  }
  if(playerMarker) playerMarker.remove();
  if(player.lat||player.lng) playerMarker=L.circleMarker([player.lat,player.lng],{radius:7,color:'#2563eb',
    fillColor:'#3b82f6',fillOpacity:1}).addTo(map).bindTooltip('Trainer Position');
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
  if(mode==='teleport'){
    const player=$('giveuser').value.trim();
    if(!player){alert('Select a trainer before teleporting.');return;}
    const result=await post('/api/teleport',{player,lat,lng});
    if(!result.ok){alert(result.message);return;}
    $('givehint').textContent=`Teleported ${result.player} to ${lat.toFixed(5)}, ${lng.toFixed(5)}`;
    $('givehint').style.color='var(--success)';
    return load();
  }
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