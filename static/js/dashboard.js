async function loadDashboard() {
  const [accs, overview] = await Promise.all([
    api('/api/accounts'),
    state.user?.is_admin ? api('/api/admin/overview').catch(() => null) : Promise.resolve(null),
  ]);

  state.accounts = accs.accounts;
  state.adminOverview = overview;

  $('#dash-username').textContent = state.user.username;

  const running = state.accounts.filter((a) => a.is_running).length;
  $('#stat-accounts').textContent = state.accounts.length;
  $('#stat-running').textContent = running;

  // Admin-only stat cards
  const adminOnly = $$('.stat-admin-only');
  adminOnly.forEach((el) => { el.hidden = !state.user?.is_admin; });
  if (overview) {
    $('#stat-users').textContent = overview.users;
    $('#stat-keys').textContent = overview.active_keys;
  }
}