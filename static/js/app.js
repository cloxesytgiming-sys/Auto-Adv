const state = {
  user: null,
  accounts: [],
  keys: [],
  vouches: [],
  adminOverview: null,
  adminUsers: [],
  drafts: {},
  authTab: 'login',
};

const ROUTES = {
  login:     { auth: false },
  register:  { auth: false },
  dashboard: { auth: true },
  accounts:  { auth: true },
  vouches:   { auth: true },
  admin:     { auth: true, admin: true },
};

const $  = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({
  '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
}[c]));

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));

  if (res.status === 401) {
    state.user = null;
    if (location.hash !== '#login') location.hash = '#login';
    throw new Error(data.error || 'Session expired');
  }
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

window.toast = function(msg, type = 'success') {
  console.log(`[${type}]`, msg);
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  const root = $('#toast-root');
  if (root) root.appendChild(el);
  setTimeout(() => el.remove(), type === 'error' ? 7000 : 3500);
};

function showAuthView(tab) {
  state.authTab = tab;
  $('#shell').hidden = true;
  $('#auth-container').hidden = false;
  $('#auth-tab-login').classList.toggle('active', tab === 'login');
  $('#auth-tab-register').classList.toggle('active', tab === 'register');
  $('#auth-submit').textContent = tab === 'login' ? 'Sign In' : 'Create Account';
  document.title = tab === 'login' ? 'Sign In · Nexus' : 'Register · Nexus';
}

function showAppView(name) {
  $('#auth-container').hidden = true;
  $('#shell').hidden = false;

  $$('.view').forEach((v) => { v.hidden = true; });
  const el = document.getElementById('view-' + name);
  if (el) el.hidden = false;

  $$('.nav-item').forEach((n) => {
    n.classList.toggle('active', n.dataset.view === name);
  });

  if (state.user) {
    $('#user-name').textContent = state.user.username;
    $('#user-role').textContent = state.user.is_admin ? 'Administrator' : 'User';
    $('#user-avatar').textContent = (state.user.username[0] || '?').toUpperCase();
    const adminBtn = $('#nav-admin');
    if (adminBtn) adminBtn.hidden = !state.user.is_admin;
  }

  const titles = {
    dashboard: 'Dashboard', accounts: 'Accounts',
    vouches: 'Vouches', admin: 'Admin',
  };
  document.title = (titles[name] || 'Nexus') + ' · Nexus';
}

async function router() {
  // Handle weird query strings or empty hashes
  let rawHash = location.hash.replace(/^#\/?/, '').replace('!', '');
  let hash = rawHash || 'dashboard';
  
  if (!ROUTES[hash]) {
    hash = state.user ? 'dashboard' : 'login';
    location.hash = '#' + hash;
  }

  const route = ROUTES[hash];

  if (route.auth && !state.user) {
    try {
      const d = await api('/api/me');
      if (d.user) {
        state.user = d.user;
      } else {
        sessionStorage.setItem('redirect', hash);
        location.hash = '#login';
        return;
      }
    } catch {
      sessionStorage.setItem('redirect', hash);
      location.hash = '#login';
      return;
    }
  }

  if (route.admin && !state.user?.is_admin) {
    location.hash = '#dashboard';
    return;
  }

  if (!route.auth && state.user) {
    location.hash = '#dashboard';
    return;
  }

  if (!route.auth) {
    showAuthView(hash);
    return;
  }

  showAppView(hash);

  try {
    if (hash === 'dashboard')      await loadDashboard();
    else if (hash === 'accounts')  await loadAccounts();
    else if (hash === 'vouches')   await loadVouches();
    else if (hash === 'admin')     await loadAdmin();
  } catch (e) {
    toast(e.message, 'error');
  }
}

window.logout = async function() {
  try { await api('/api/logout', { method: 'POST' }); } catch {}
  state.user = null;
  state.accounts = [];
  state.keys = [];
  state.vouches = [];
  state.adminOverview = null;
  state.adminUsers = [];
  state.drafts = {};
  location.hash = '#login';
};