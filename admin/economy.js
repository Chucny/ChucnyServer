(() => {
  const Admin = window.Admin;
  const $ = Admin.$;

  function showGiveResult(result) {
    Admin.feedback('givehint', result.ok ? 'success' : 'error', result.message);
    Admin.load();
  }

  function paintShop(coins) {
    const box = $('shopitems');
    box.replaceChildren();
    Admin.SHOP.forEach(([sku, label, , , price]) => {
      const button = document.createElement('button');
      button.textContent = `${label} (${price}c)`;
      button.disabled = coins < price;
      button.style.opacity = coins < price ? 0.45 : 1;
      button.addEventListener('click', () => buyItem(sku));
      box.appendChild(button);
    });
  }

  async function buyItem(sku) {
    Admin.feedback('buyhint', 'loading', 'Purchasing item…');
    try {
      const result = await Admin.post('/api/buyitem', {sku, player: $('giveuser').value});
      Admin.feedback('buyhint', result.ok ? 'success' : 'error', result.message);
      Admin.load();
    } catch {
      Admin.feedback('buyhint', 'error', 'Could not purchase item');
    }
  }

  function paintRaid(raid) {
    $('b-raid').textContent = 'Raid: ' + (raid.on ? 'ON' : 'OFF');
    $('b-raid').classList.toggle('btn-danger', raid.on);
    if (raid.pokemon_id) $('raid-mon').value = raid.pokemon_id;
    if (raid.cp) $('raid-cp').value = raid.cp;
    if (raid.trainer) $('raid-name').value = raid.trainer;
  }

  async function toggleRaid() {
    Admin.feedback('raidhint', 'loading', 'Updating raid…');
    try {
      const result = await Admin.post('/api/raid', {
        on: !$('b-raid').textContent.includes('ON'),
        pokemon_id: +$('raid-mon').value,
        cp: +$('raid-cp').value,
        trainer: $('raid-name').value
      });
      paintRaid(result);
      Admin.feedback('raidhint', result.ok === false ? 'error' : 'success', result.message);
      Admin.load();
    } catch {
      Admin.feedback('raidhint', 'error', 'Could not update raid');
    }
  }

  async function saveRaid() {
    Admin.feedback('raidhint', 'loading', 'Applying raid settings…');
    try {
      const result = await Admin.post('/api/raid', {
        pokemon_id: +$('raid-mon').value,
        cp: +$('raid-cp').value,
        trainer: $('raid-name').value
      });
      paintRaid(result);
      Admin.feedback('raidhint', result.ok === false ? 'error' : 'success', result.message);
      Admin.load();
    } catch {
      Admin.feedback('raidhint', 'error', 'Could not apply raid settings');
    }
  }

  async function give(kind, fields) {
    Admin.feedback('givehint', 'loading', 'Granting reward…');
    try {
      showGiveResult(await Admin.post('/api/give', {player: $('giveuser').value, kind, ...fields}));
    } catch {
      Admin.feedback('givehint', 'error', 'Could not grant reward');
    }
  }

  async function resetPassword() {
    const player = $('giveuser').value.trim();
    if (!player) {
      showGiveResult({ok: false, message: 'Select a trainer first'});
      return;
    }
    showGiveResult(await Admin.post('/api/setpw', {player, password: $('newpw').value}));
    $('newpw').value = '';
  }

  async function buyStorage(what) {
    Admin.feedback('shophint', 'loading', 'Purchasing upgrade…');
    try {
      const result = await Admin.post('/api/buy', {what});
      Admin.feedback('shophint', result.ok ? 'success' : 'error', result.message);
      Admin.load();
    } catch {
      Admin.feedback('shophint', 'error', 'Could not purchase upgrade');
    }
  }

  function addOptions() {
    Admin.GIVEABLE.forEach(([id, label]) => {
      const option = document.createElement('option');
      option.value = id;
      option.textContent = label;
      $('giveitem').appendChild(option);
    });
    Admin.DEX.forEach((name, id) => {
      if (!id) return;
      const candy = document.createElement('option');
      candy.value = id;
      candy.textContent = name + ' candy';
      $('givecandy').appendChild(candy);
      const raid = document.createElement('option');
      raid.value = id;
      raid.textContent = `${id} ${name}`;
      $('raid-mon').appendChild(raid);
    });
    $('givecandy').value = 25;
    $('raid-mon').value = 150;
    const random = document.createElement('option');
    random.value = 0;
    random.textContent = 'Random Pokemon';
    $('species').appendChild(random);
    Admin.DEX.forEach((name, id) => {
      if (!id) return;
      const option = document.createElement('option');
      option.value = id;
      option.textContent = `${id} ${name}`;
      $('species').appendChild(option);
    });
    $('species').value = 0;
  }

  function render(world) {
    const storage = world.storage || {};
    const coins = storage.coins || 0;
    $('coins').textContent = coins;
    paintShop(coins);
    $('b-buypk').textContent = `Pokemon storage: ${storage.pokemon_used || 0}/${storage.max_pokemon || 0}`;
    $('b-buyit').textContent = `Item bag: ${storage.items_used || 0}/${storage.max_items || 0}`;
  }

  function init() {
    addOptions();
    $('b-raid').addEventListener('click', toggleRaid);
    $('save-raid').addEventListener('click', saveRaid);
    $('b-buypk').addEventListener('click', () => buyStorage('pokemon'));
    $('b-buyit').addEventListener('click', () => buyStorage('items'));
    $('give-items').addEventListener('click', () => give('item', {item_id: +$('giveitem').value, count: +$('giveqty').value}));
    $('give-candy').addEventListener('click', () => give('candy', {pokemon_id: +$('givecandy').value, count: +$('givecandyqty').value}));
    $('give-dust').addEventListener('click', () => give('stardust', {count: +$('givedust').value}));
    $('give-coins').addEventListener('click', () => give('coins', {count: +$('givecoins').value}));
    $('reset-password').addEventListener('click', resetPassword);
    Admin.post('/api/raid', {}).then(paintRaid);
  }

  Admin.renderEconomy = render;
  Admin.initEconomy = init;
})();
