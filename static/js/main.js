/* ---------- Modal helpers ---------- */
function closeModal() {
  const m1 = document.querySelector('#modal-add-account');
  const m2 = document.querySelector('#modal-output');
  
  if (m1) { m1.setAttribute('hidden', ''); m1.style.display = 'none'; }
  if (m2) { m2.setAttribute('hidden', ''); m2.style.display = 'none'; }
  
  const k = document.querySelector('#link-key');
  const t = document.querySelector('#link-token');
  if (k) k.value = '';
  if (t) t.value = '';
}

function openOutputModal(title, body) {
  const t = document.querySelector('#output-title');
  const b = document.querySelector('#output-body');
  const m = document.querySelector('#modal-output');
  
  if (t) t.textContent = title;
  if (b) b.textContent = body || '(empty)';
  if (m) { 
    m.removeAttribute('hidden'); 
    m.style.display = 'flex'; 
  }
}

// Close on background click / Escape
document.addEventListener('click', (e) => {
  if (e.target.classList.contains('modal-bg')) closeModal();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeModal();
});

/* ---------- Boot & Event Listeners ---------- */
async function boot() {
  document.querySelectorAll('.nav-item').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const view = e.currentTarget.dataset.view;
      if (view) location.hash = '#' + view;
    });
  });

  try {
    const d = await api('/api/me');
    state.user = d.user || null;
  } catch {
    state.user = null;
  }

  if (!location.hash || !ROUTES[location.hash.slice(1)]) {
    location.hash = state.user ? '#dashboard' : '#login';
  } else {
    await router();
  }

  window.addEventListener('hashchange', router);
}

document.addEventListener('DOMContentLoaded', boot);