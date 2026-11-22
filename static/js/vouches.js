async function loadVouches() {
  const d = await api('/api/vouches');
  state.vouches = d.vouches;
  renderVouchesList();
}

function renderVouchesList() {
  const container = $('#vouches-list');
  if (!state.vouches.length) {
    container.innerHTML = `
      <div class="empty">
        <div class="empty-icon"><svg><use href="#i-star"/></svg></div>
        <div>No vouches yet — be the first!</div>
      </div>`;
    return;
  }
  container.innerHTML = state.vouches.map((v) => `
    <div class="vouch">
      <div class="vouch-head">
        <div class="vouch-user">${esc(v.username)}</div>
        <div class="vouch-stars">${'★'.repeat(v.rating)}${'☆'.repeat(5 - v.rating)}</div>
      </div>
      <div class="vouch-body">${esc(v.content)}</div>
      <div class="vouch-time">${new Date(v.created_at).toLocaleString()}</div>
    </div>
  `).join('');
}

async function submitVouch() {
  const content = $('#vouch-content').value.trim();
  const rating = parseInt($('#vouch-rating').value, 10);
  if (content.length < 5) {
    toast('Vouch must be at least 5 characters', 'error');
    return;
  }
  try {
    await api('/api/vouches', { method: 'POST', body: { content, rating } });
    toast('Vouch posted!');
    $('#vouch-content').value = '';
    await loadVouches();
  } catch (e) { toast(e.message, 'error'); }
}