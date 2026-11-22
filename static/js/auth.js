async function handleAuth(e) {
  if (e) e.preventDefault();
  
  const usernameEl = document.querySelector('#au-name');
  const passwordEl = document.querySelector('#au-pass');
  if (!usernameEl || !passwordEl) return;
  
  const username = usernameEl.value.trim();
  const password = passwordEl.value;
  const isLogin = state.authTab === 'login';
  const btn = document.querySelector('#auth-submit');
  
  if (!username || !password) {
    toast('Please fill in both fields', 'error');
    return;
  }

  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Please wait…';

  try {
    const d = await api(isLogin ? '/api/login' : '/api/register', {
      method: 'POST',
      body: { username, password },
    });
    
    state.user = d.user;
    toast(isLogin ? 'Welcome back!' : 'Account created!');
    
    // Redirect to dashboard (or original destination)
    const redirect = sessionStorage.getItem('redirect') || 'dashboard';
    sessionStorage.removeItem('redirect');
    location.hash = '#' + redirect;
    
    // If hash didn't change, force a router refresh
    if (location.hash === '#' + redirect) {
      await router();
    }
    
  } catch (err) {
    toast(err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  // Bind to form submit
  const form = document.querySelector('#auth-form');
  if (form) form.addEventListener('submit', handleAuth);
  
  // Bind directly to button click (fixes Android Chrome issues)
  const btn = document.querySelector('#auth-submit');
  if (btn) btn.addEventListener('click', handleAuth);

  // Tab switching
  document.querySelectorAll('[data-tab]').forEach(el => {
    el.addEventListener('click', (e) => {
      const tab = e.currentTarget.dataset.tab;
      if (state.authTab === tab) return;
      state.authTab = tab;
      location.hash = '#' + tab;
    });
  });
});