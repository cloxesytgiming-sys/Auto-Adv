async function loadAccounts() {
  const d = await api('/api/accounts');
  state.accounts = d.accounts;

  state.accounts.forEach((a) => {
    if (!state.drafts[a.id]) {
      state.drafts[a.id] = {
        channel_id: a.channel_id || '',
        interval: a.interval || 300,
        message: a.message || '',
        channel_name: '',
        channel_type: 'guild'
      };
      // Fetch channel info immediately if it exists
      if (a.channel_id) {
        fetchChannelInfo(a.id, a.channel_id);
      }
    }
  });

  renderAccountsList();
}

function renderAccountsList() {
  const container = document.querySelector('#accounts-list');
  if (!container) return;

  if (!state.accounts.length) {
    container.innerHTML = `
      <div class="empty">
        <div class="empty-icon"><svg><use href="#i-link"/></svg></div>
        <div>No accounts linked yet.</div>
        <button class="btn btn-primary empty-btn" onclick="openAddAccount()">
          <svg class="icon"><use href="#i-plus"/></svg>
          <span>Link Your First Account</span>
        </button>
      </div>`;
    return;
  }
  container.innerHTML = state.accounts.map(renderAccountCard).join('');
  
  // Ensure previews render correctly on load
  state.accounts.forEach(a => updatePreview(a.id));
}

function renderAccountCard(a) {
  const d = state.drafts[a.id] || {};
  const initial = (a.discord_username || '?')[0].toUpperCase();
  const lastSent = a.last_sent_at ? new Date(a.last_sent_at).toLocaleString() : 'never';

  // Construct real Discord Avatar URL
  const avatarUrl = a.discord_avatar
    ? `https://cdn.discordapp.com/avatars/${a.discord_user_id}/${a.discord_avatar}.png?size=128`
    : `https://cdn.discordapp.com/embed/avatars/${parseInt(a.discord_user_id) % 5}.png`;

  return `
    <div class="account-card" id="acc-${a.id}">
      <div class="acc-header">
        <div class="acc-user">
          <div class="acc-avatar" style="background-image: url('${avatarUrl}'); background-size: cover; color: transparent;">${initial}</div>
          <div>
            <div class="acc-name">${esc(a.discord_username || 'Unknown')}</div>
            <div class="acc-id">${esc(a.discord_user_id)}</div>
          </div>
        </div>
        <div class="acc-badges">
          ${a.is_owner ? '<span class="badge badge-owner">Owner</span>' : ''}
          <span class="badge ${a.is_running ? 'badge-running' : 'badge-stopped'}">
            ${a.is_running ? 'Running' : 'Stopped'}
          </span>
        </div>
      </div>

      <div class="acc-grid">
        <div>
          <label>Channel ID</label>
          <input value="${esc(d.channel_id || '')}" placeholder="1234567890"
            oninput="setDraft(${a.id},'channel_id',this.value); window.debouncedFetchChannel(${a.id})">
        </div>
        <div>
          <label>Interval (seconds)</label>
          <input type="number" min="5" value="${d.interval || 300}"
            oninput="setDraft(${a.id},'interval',this.value)">
        </div>
        <div class="full">
          <label>Message</label>
          <textarea oninput="setDraft(${a.id},'message',this.value);updatePreview(${a.id})">${esc(d.message || '')}</textarea>
        </div>
      </div>

      <label style="margin-top:10px">Live Preview</label>
      <div class="discord-preview" id="preview-${a.id}">
        <!-- Preview HTML is updated dynamically by updatePreview() -->
      </div>

      <div class="acc-meta">
        <span>Last sent: <span class="${a.last_sent_at ? 'ok' : ''}">${lastSent}</span></span>
        ${a.last_error ? `<span class="err">⚠ ${esc(a.last_error.slice(0, 150))}</span>` : ''}
      </div>

      <div class="acc-actions">
        <button class="btn btn-primary btn-sm" onclick="saveConfig(${a.id})">
          <svg class="icon"><use href="#i-save"/></svg><span>Save</span>
        </button>
        <button class="btn btn-ghost btn-sm" onclick="testSend(${a.id})">
          <svg class="icon"><use href="#i-beaker"/></svg><span>Test</span>
        </button>
        ${a.is_running
          ? `<button class="btn btn-danger btn-sm" onclick="toggleAccount(${a.id},'stop')">
              <svg class="icon"><use href="#i-stop"/></svg><span>Stop</span>
            </button>`
          : `<button class="btn btn-ghost btn-sm" onclick="toggleAccount(${a.id},'start')">
              <svg class="icon"><use href="#i-play"/></svg><span>Start</span>
            </button>`}
        <button class="btn btn-ghost btn-sm" onclick="removeAccount(${a.id})">
          <svg class="icon"><use href="#i-trash"/></svg><span>Unlink</span>
        </button>
      </div>
    </div>`;
}

// --- Data Fetching & Preview Logic ---
let fetchTimeouts = {};
window.debouncedFetchChannel = function(id) {
  clearTimeout(fetchTimeouts[id]);
  fetchTimeouts[id] = setTimeout(() => {
    const d = state.drafts[id];
    if (d && d.channel_id && d.channel_id.length > 15) {
      fetchChannelInfo(id, d.channel_id);
    }
  }, 800); // Wait 800ms after typing stops before fetching
};

async function fetchChannelInfo(accountId, channelId) {
  try {
    const res = await api(`/api/accounts/${accountId}/channel_info`, {
      method: 'POST',
      body: { channel_id: channelId }
    });
    if (res.error) throw new Error(res.error);
    
    state.drafts[accountId].channel_name = res.name;
    state.drafts[accountId].channel_type = res.type;
    state.drafts[accountId].channel_avatar = res.avatar;
    state.drafts[accountId].channel_user_id = res.user_id;
  } catch (e) {
    state.drafts[accountId].channel_name = 'Invalid / No Access';
    state.drafts[accountId].channel_type = 'error';
  }
  updatePreview(accountId);
}

window.updatePreview = function(id) {
  const d = state.drafts[id] || {};
  const a = state.accounts.find(x => x.id === id);
  const container = document.getElementById(`preview-${id}`);
  if (!a || !container) return;

  const previewMsg = esc(d.message || 'Your message here...');
  
  // Default: Bot's own user info
  const initial = (a.discord_username || '?')[0].toUpperCase();
  let dpName = a.discord_username || 'user';
  let dpAvatarUrl = a.discord_avatar 
      ? `https://cdn.discordapp.com/avatars/${a.discord_user_id}/${a.discord_avatar}.png?size=128`
      : `https://cdn.discordapp.com/embed/avatars/${parseInt(a.discord_user_id) % 5}.png`;
  
  let channelBarHtml = `<span>#</span><strong>${esc(d.channel_name || 'unknown-channel')}</strong>`;

  // If it's a DM, show the recipient's info
  if (d.channel_type === 'dm') {
    dpName = d.channel_name || 'User';
    dpAvatarUrl = d.channel_avatar 
      ? `https://cdn.discordapp.com/avatars/${d.channel_user_id}/${d.channel_avatar}.png?size=128`
      : `https://cdn.discordapp.com/embed/avatars/${parseInt(d.channel_user_id || 0) % 5}.png`;
    channelBarHtml = `<span>@</span><strong>${esc(dpName)}</strong>`;
  }

  container.innerHTML = `
    <div class="dp-channel-bar">
      ${channelBarHtml}
      <span style="margin-left:auto">📢 Ad</span>
    </div>
    <div class="dp-header">
      <div class="dp-avatar" style="background-image: url('${dpAvatarUrl}'); background-size: cover; color: transparent;">${dpName[0].toUpperCase()}</div>
      <div class="dp-body">
        <div class="dp-name">
          <span class="dp-username">${esc(dpName)}</span>
          ${d.channel_type !== 'dm' ? '<span class="dp-bot-tag">APP</span>' : ''}
          <span class="dp-time">Today at ${new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</span>
        </div>
        <div class="dp-message">${previewMsg}</div>
      </div>
    </div>
  `;
};

window.setDraft = function(id, field, value) {
  if (!state.drafts[id]) state.drafts[id] = {};
  state.drafts[id][field] = value;
};

// --- Actions ---
window.saveConfig = async function(id) {
  const d = state.drafts[id] || {};
  try {
    await api(`/api/accounts/${id}/config`, {
      method: 'PATCH',
      body: {
        channel_id: d.channel_id,
        interval: parseInt(d.interval) || 300,
        message: d.message,
      },
    });
    toast('Configuration saved');
    await loadAccounts();
  } catch (e) { toast(e.message, 'error'); }
};

window.toggleAccount = async function(id, action) {
  try {
    await api(`/api/accounts/${id}/${action}`, { method: 'POST' });
    toast(action === 'start' ? 'Advertiser started' : 'Advertiser stopped');
    await loadAccounts();
  } catch (e) { toast(e.message, 'error'); }
};

window.testSend = async function(id) {
  toast('Sending test message…');
  try {
    const d = await api(`/api/accounts/${id}/test`, { method: 'POST' });
    await loadAccounts();
    if (d.ok) {
      toast('✅ Message sent! Check Discord.');
    } else {
      openOutputModal('❌ Test Failed', d.output || d.error || 'Unknown error');
    }
  } catch (e) { toast(e.message, 'error'); }
};

window.removeAccount = async function(id) {
  if (!confirm('Unlink this account? Key slot will be returned.')) return;
  try {
    await api(`/api/accounts/${id}`, { method: 'DELETE' });
    delete state.drafts[id];
    toast('Account unlinked');
    await loadAccounts();
  } catch (e) { toast(e.message, 'error'); }
};

window.openAddAccount = function() {
  const m = document.querySelector('#modal-add-account');
  if (m) {
    m.removeAttribute('hidden'); 
    m.style.display = 'flex';
  }
  setTimeout(() => {
    const k = document.querySelector('#link-key');
    if (k) k.focus();
  }, 100);
};

window.submitLink = async function() {
  const k = document.querySelector('#link-key');
  const t = document.querySelector('#link-token');
  if (!k || !t) return;

  const key = k.value.trim();
  const token = t.value.trim();
  
  try {
    const d = await api('/api/accounts/link', {
      method: 'POST',
      body: { key, token },
    });
    if (d.promoted) {
      toast('👑 Owner account linked — admin granted!');
      state.user = (await api('/api/me')).user;
    } else {
      toast('Account linked!');
    }
    closeModal();
    await loadAccounts();
  } catch (e) { toast(e.message, 'error'); }
};