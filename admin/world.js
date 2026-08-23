(() => {
  const Admin = window.Admin;
  const $ = Admin.$;
  let mode = 'stop';
  let map;
  let layer;
  let playerMarker;

  function icon(color, label) {
    return L.divIcon({
      className: '',
      html: `<div style="background:${color};border:2px solid #fff;border-radius:50%;width:26px;height:26px;display:flex;align-items:center;justify-content:center;font:700 11px sans-serif;color:#fff;box-shadow:0 2px 5px rgba(0,0,0,0.2)">${label}</div>`,
      iconSize: [26, 26],
      iconAnchor: [13, 13]
    });
  }

  function setMode(nextMode) {
    mode = nextMode;
    ['stop', 'gym', 'mon', 'teleport'].forEach(name => {
      $('b-' + name).classList.toggle('on', name === mode);
    });
  }

  async function ring() {
    const player = Admin.state.player;
    if (!player.lat) {
      alert('No trainer position available - open the game first or click the map.');
      return;
    }
    await Admin.post('/api/ring', {
      lat: player.lat,
      lng: player.lng,
      count: +$('ring-n').value,
      radius_m: +$('ring-r').value,
      gym: true
    });
    Admin.load();
  }

  async function importPois() {
    const player = Admin.state.player;
    const lat = parseFloat($('poi-lat').value || player.lat);
    const lng = parseFloat($('poi-lng').value || player.lng);
    const r_km = parseFloat($('poi-r').value || 3);
    const limit = parseInt($('poi-limit').value || 5000);
    if (!lat || !lng) {
      alert('Please enter latitude and longitude.');
      return;
    }
    $('poihint').textContent = 'Fetching high-density POIs from OpenStreetMap...';
    const result = await Admin.post('/api/fetch_pois', {
      lat,
      lng,
      radius_km: r_km,
      limit,
      gym_chance: parseFloat($('poi-gym-chance').value || 0) / 100
    });
    $('poihint').textContent = result.message || `Imported ${result.placed} Objects.`;
    Admin.load();
  }

  async function saveEvent() {
    await Admin.post('/api/save', {
      event_name: $('ev-name').value,
      spawn_density: +$('ev-density').value,
      species_mode: $('ev-mode').value,
      species_list: $('ev-list').value.split(',').map(value => parseInt(value.trim())).filter(value => value >= 1 && value <= 151),
      single_species: +$('species').value,
      min_cp: +$('ev-min').value,
      max_cp: +$('ev-max').value
    });
    Admin.load();
  }

  async function applyPreset(name) {
    await Admin.post('/api/preset', {name});
    Admin.load();
  }

  function renderNoms(result) {
    const box = $('noms');
    box.replaceChildren();
    if (!result.rows || !result.rows.length) {
      box.innerHTML = '<div class="empty">No nominations waiting.</div>';
      return;
    }
    result.rows.forEach(nomination => {
      const row = document.createElement('div');
      row.className = 'row';
      const details = document.createElement('div');
      const tag = document.createElement('span');
      tag.className = 'tag ' + (nomination.kind === 'gym' ? 'gym' : 'stop');
      tag.textContent = nomination.kind === 'gym' ? 'GYM' : 'STOP';
      const title = document.createElement('b');
      title.textContent = ` ${nomination.name} `;
      const byline = document.createElement('small');
      byline.style.color = 'var(--text-muted)';
      byline.textContent = `— by ${nomination.player}${nomination.note ? ` · ${nomination.note}` : ''}`;
      details.append(tag, title, byline);
      const remove = document.createElement('button');
      remove.className = 'x';
      remove.textContent = 'Remove';
      remove.addEventListener('click', () => resolveNom(nomination.id));
      row.append(details, remove);
      box.appendChild(row);
    });
  }

  async function loadNoms() {
    renderNoms(await Admin.post('/api/noms', {}));
  }

  async function resolveNom(id) {
    await Admin.post('/api/noms/resolve', {id, status: 'rejected'});
    loadNoms();
    Admin.load();
  }

  function draw() {
    layer.clearLayers();
    const data = Admin.state.data;
    data.forts.forEach(fort => {
      L.marker([fort.lat, fort.lng], {icon: icon(fort.kind === 'gym' ? '#ef4444' : '#2563eb', fort.kind === 'gym' ? 'G' : 'S')})
        .addTo(layer).bindTooltip(fort.name).on('click', () => removeObject(fort.id));
    });
    data.spawns.forEach(spawn => {
      L.marker([spawn.lat, spawn.lng], {icon: icon(spawn.pokemon_id ? '#10b981' : '#8b5cf6', spawn.pokemon_id ? String(spawn.pokemon_id) : '?')})
        .addTo(layer).bindTooltip(spawn.pokemon_id ? (Admin.DEX[spawn.pokemon_id] || ('#' + spawn.pokemon_id)) : 'Random').on('click', () => removeObject(spawn.id));
    });
    const rows = [
      ...data.forts.map(fort => ({id: fort.id, cls: fort.kind === 'gym' ? 'gym' : 'stop', tag: fort.kind === 'gym' ? 'GYM' : 'STOP', text: `${fort.name}${fort.image ? ' [photo]' : ''} — ${fort.lat.toFixed(5)}, ${fort.lng.toFixed(5)}`})),
      ...data.spawns.map(spawn => ({id: spawn.id, cls: 'mon', tag: spawn.pokemon_id ? 'MON' : 'RANDOM', text: `${spawn.pokemon_id ? (Admin.DEX[spawn.pokemon_id] || ('#' + spawn.pokemon_id)) : 'Random Pokemon'} — ${spawn.lat.toFixed(5)}, ${spawn.lng.toFixed(5)}`}))
    ];
    const list = $('list');
    list.replaceChildren();
    if (!rows.length) {
      list.innerHTML = '<div class="empty">Nothing placed yet — click the map above.</div>';
      return;
    }
    rows.forEach(rowData => {
      const row = document.createElement('div');
      row.className = 'row';
      const label = document.createElement('div');
      const tag = document.createElement('span');
      tag.className = 'tag ' + rowData.cls;
      tag.textContent = rowData.tag;
      const text = document.createElement('span');
      text.className = 't';
      text.textContent = ' ' + rowData.text;
      label.append(tag, text);
      const remove = document.createElement('button');
      remove.className = 'x';
      remove.textContent = 'Remove';
      remove.addEventListener('click', () => removeObject(rowData.id));
      row.append(label, remove);
      list.appendChild(row);
    });
  }

  async function place(lat, lng) {
    if (mode === 'teleport') {
      const player = $('giveuser').value.trim();
      if (!player) {
        Admin.feedback('worldhint', 'error', 'Select a trainer before teleporting');
        return;
      }
      Admin.feedback('worldhint', 'loading', 'Teleporting trainer…');
      try {
        const result = await Admin.post('/api/teleport', {player, lat, lng});
        if (!result.ok) {
          Admin.feedback('worldhint', 'error', result.message);
          return;
        }
        Admin.feedback('worldhint', 'success', `Teleported ${result.player} to ${lat.toFixed(5)}, ${lng.toFixed(5)}`);
        Admin.load();
      } catch {
        Admin.feedback('worldhint', 'error', 'Could not teleport trainer');
      }
      return;
    }
    const name = $('pname').value;
    if (mode === 'mon') await Admin.post('/api/spawn', {lat, lng, pokemon_id: +$('species').value, name});
    else await Admin.post('/api/fort', {lat, lng, kind: mode, name, image: $('pimg').value});
    Admin.load();
  }

  async function removeObject(id) {
    await Admin.post('/api/remove', {id});
    Admin.load();
  }

  async function clearAll() {
    if (confirm('Remove every placed object?')) {
      await Admin.post('/api/clear', {});
      Admin.load();
    }
  }

  async function toggleProcedural(what) {
    const data = Admin.state.data;
    await Admin.post('/api/procedural', {on: !(what === 'forts' ? data.procedural_forts : data.procedural_spawns), what});
    Admin.load();
  }

  function render(world) {
    const data = world.places;
    const gyms = data.forts.filter(fort => fort.kind === 'gym').length;
    const stops = data.forts.length - gyms;
    $('cnt').textContent = data.forts.length + data.spawns.length;
    $('counts').textContent = `${stops} Stops / ${gyms} Gyms / ${data.spawns.length} Spawns`;
    $('warn').style.display = gyms === 0 && !data.procedural_forts ? 'block' : 'none';
    $('b-pf').textContent = 'Random Stops: ' + (data.procedural_forts ? 'ON' : 'OFF');
    $('b-ps').textContent = 'Random Pokemon: ' + (data.procedural_spawns ? 'ON' : 'OFF');
    $('b-pf').classList.toggle('on', data.procedural_forts);
    $('b-ps').classList.toggle('on', data.procedural_spawns);
    const config = world.config;
    $('ev-name').value = config.event_name;
    $('ev-density').value = config.spawn_density;
    $('ev-mode').value = config.species_mode;
    $('ev-list').value = (config.species_list || []).join(',');
    $('ev-min').value = config.min_cp;
    $('ev-max').value = config.max_cp;
    if (!$('presets').dataset.done) {
      world.presets.forEach(name => {
        const button = document.createElement('button');
        button.textContent = name;
        button.addEventListener('click', () => applyPreset(name));
        $('presets').appendChild(button);
      });
      $('presets').dataset.done = '1';
    }
    if (!map) {
      const player = Admin.state.player;
      map = L.map('map').setView([player.lat || 39.19, player.lng || -96.58], player.lat ? 18 : 16);
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '&copy; OpenStreetMap'}).addTo(map);
      layer = L.layerGroup().addTo(map);
      map.on('click', event => place(event.latlng.lat, event.latlng.lng));
    }
    if (playerMarker) playerMarker.remove();
    const player = Admin.state.player;
    if (player.lat || player.lng) {
      playerMarker = L.circleMarker([player.lat, player.lng], {radius: 7, color: '#2563eb', fillColor: '#3b82f6', fillOpacity: 1})
        .addTo(map).bindTooltip('Trainer Position');
    }
    draw();
  }

  function init() {
    ['stop', 'gym', 'mon', 'teleport'].forEach(name => $('b-' + name).addEventListener('click', () => setMode(name)));
    $('b-pf').addEventListener('click', () => toggleProcedural('forts'));
    $('b-ps').addEventListener('click', () => toggleProcedural('spawns'));
    $('clear-all').addEventListener('click', clearAll);
    $('build-ring').addEventListener('click', ring);
    $('import-pois').addEventListener('click', importPois);
    $('save-event').addEventListener('click', saveEvent);
    setMode(mode);
  }

  Admin.world = {setMode, loadNoms, invalidateMap: () => map?.invalidateSize()};
  Admin.renderWorld = render;
  Admin.initWorld = init;
})();
