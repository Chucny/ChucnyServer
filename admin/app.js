(() => {
  const $ = id => document.getElementById(id);
  const Admin = window.Admin = {
    $,
    DEX: __DEX__,
    GIVEABLE: __GIVEABLE__,
    SHOP: __SHOP__,
    state: {data: {forts: [], spawns: []}, player: {lat: 0, lng: 0}, world: null},
    feedback(id, state, message) {
      const element = $(id);
      element.textContent = message;
      element.classList.add('feedback');
      element.dataset.state = state;
    },
    async post(url, body) {
      return (await fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body || {})
      })).json();
    },
    setTab(name) {
      document.querySelectorAll('[data-tab]').forEach(button => {
        button.classList.toggle('active', button.dataset.tab === name);
        button.setAttribute('aria-selected', String(button.dataset.tab === name));
      });
      document.querySelectorAll('[data-panel]').forEach(panel => {
        panel.hidden = panel.dataset.panel !== name;
      });
      if (name === 'world') requestAnimationFrame(() => Admin.world?.invalidateMap());
    },
    async load() {
      const world = await (await fetch('/api/world')).json();
      Admin.state.world = world;
      Admin.state.data = world.places;
      const selected = $('giveuser').value.trim();
      Admin.state.player = selected && world.teleports[selected]
        ? {lat: world.teleports[selected][0], lng: world.teleports[selected][1]}
        : world.player;
      Admin.renderDashboard?.(world);
      Admin.renderWorld?.(world);
      Admin.renderEconomy?.(world);
    }
  };

  document.addEventListener('DOMContentLoaded', () => {
    Admin.initDashboard();
    Admin.initWorld();
    Admin.initEconomy();
    Admin.load();
    Admin.world.loadNoms();
    setInterval(() => Admin.load(), 15000);
    setInterval(() => Admin.world.loadNoms(), 20000);
  });
})();
