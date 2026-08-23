(() => {
  const Admin = window.Admin;
  const $ = Admin.$;

  function render(world) {
    const data = world.places;
    const gyms = data.forts.filter(fort => fort.kind === 'gym').length;
    const stops = data.forts.length - gyms;
    $('status').textContent = 'RUNNING';
    $('dash-stops').textContent = stops;
    $('dash-gyms').textContent = gyms;
    $('dash-spawns').textContent = data.spawns.length;
    const player = Admin.state.player;
    $('dash-player-position').textContent = player.lat || player.lng
      ? `${player.lat.toFixed(5)}, ${player.lng.toFixed(5)}`
      : 'Waiting for trainer location';
  }

  async function loadAccounts() {
    const result = await Admin.post('/api/accounts', {});
    const accounts = $('accounts');
    accounts.replaceChildren();
    (result.accounts || []).forEach(name => {
      const option = document.createElement('option');
      option.value = name;
      accounts.appendChild(option);
    });
  }

  function init() {
    document.querySelectorAll('[data-tab]').forEach(button => {
      button.addEventListener('click', () => Admin.setTab(button.dataset.tab));
    });
    $('giveuser').addEventListener('change', () => Admin.load());
    $('dash-open-map').addEventListener('click', () => Admin.setTab('world'));
    $('dash-teleport').addEventListener('click', () => {
      Admin.setTab('world');
      Admin.world.setMode('teleport');
    });
    loadAccounts();
  }

  Admin.renderDashboard = render;
  Admin.initDashboard = init;
})();
