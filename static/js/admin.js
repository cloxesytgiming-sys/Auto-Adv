async function loadAdmin() {
  const [overview, keys, users] = await Promise.all([
    api('/api/admin/overview'),
    api('/api/keys'),
    api('/api/admin/users'),
  ]);
  state.adminOverview = overview;
  state.keys = keys.keys;
  state.adminUsers = users.users;

  $('#ao-users').textContent = overview.users;
  $('#ao-accounts').textContent = overview.accounts;
  $('#ao-running').textContent = overview.running;
  $('#ao-keys').textContent = overview.keys;
  $('#ao-active-keys').textContent = overview.active_keys;
  $('#ao-vouches').textContent = overview.vouches;

  renderKeysList();
  renderUsersTable();
}

function renderKeysList() {
  const container = $('#keys-list');
  if (!state.keys.length) {
    container.innerHTML = `
      <div class="empty">
        <div class="empty-icon"><svg><use href="#i-key"/></svg></div>
        <div>No keys yet</div>
      </div>`;
    return;
  }
  container.innerHTML = state.keys.map((k) => `
    <div class="key-row">
      <div style="flex:1;min-width:0">
        <div class="key-code">${k.key_string}</div>
        <div class="key-meta">
          <span class="used">${k.accounts_used}/${k.max_accounts}</span> used ·
          ${k.is_active
            ? '<span style="color:var(--green)">active</span>'
            : '<span style="color:var(--danger)">revoked</span>'}
        </div>
      </div>
      ${k.is_active
        ? `<button class="btn btn-danger btn-sm" onclick="revokeKey(${k.id})">
            <svg class="icon"><use href="#i-trash"/></svg><span>Revoke</span>
          </button>`
        : ''}
    </div>
  `).join('');
}

function renderUsersTable() {
  const tbody = $('#users-list');
  tbody.innerHTML = state.adminUsers.map((u) => `
    <tr>
      <td>${esc(u.username)}</td>
      <td>${u.is_admin ? '<span style="color:var(--magenta);font-weight:800">Yes</span>' : 'No'}</td>
      <td>${u.accounts}</td>
      <td>${new Date(u.created_at).toLocaleDateString()}</td>
      <td>
        <button class="btn btn-ghost btn-sm" onclick="toggleAdmin(${u.id})">
          ${u.is_admin ? 'Revoke Admin' : 'Make Admin'}
        </button>
      </td>
    </tr>
  `).join('');
}

async function generateKeys() {
  const count = parseInt($('#gen-count').value, 10) || 1;
  const max_accounts = parseInt($('#gen-max').value, 10) || 2;
  try {
    const d = await api('/api/keys/generate', {
      method: 'POST',
      body: { count, max_accounts },
    });
    toast(`${d.keys.length} key(s) generated`);
    await loadAdmin();
  } catch (e) { toast(e.message, 'error'); }
}

async function revokeKey(id) {
  if (!confirm('Revoke this key? Cannot be undone.')) return;
  try {
    await api(`/api/keys/${id}`, { method: 'DELETE' });
    toast('Key revoked');
    await loadAdmin();
  } catch (e) { toast(e.message, 'error'); }
}

async function toggleAdmin(id) {
  try {
    await api(`/api/admin/users/${id}/toggle-admin`, { method: 'POST' });
    await loadAdmin();
  } catch (e) { toast(e.message, 'error'); }
}