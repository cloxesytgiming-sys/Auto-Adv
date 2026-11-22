import os
import sys
import json
import time
import hmac
import base64
import hashlib
import secrets
import sqlite3
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, jsonify, render_template, request, session


# ---------------- .env loader (stdlib only) ----------------
def load_env(path):
    if not os.path.exists(path):
        return
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
                v = v[1:-1]
            os.environ.setdefault(k.strip(), v)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_env(os.path.join(BASE_DIR, '.env'))

SECRET_KEY = os.getenv('SECRET_KEY') or 'dev-secret-change-me'
OWNER_IDS = {x.strip() for x in os.getenv('OWNER_IDS', '').split(',') if x.strip()}
DB_PATH = os.getenv('DB_PATH') or os.path.join(BASE_DIR, 'dashboard.db')
PORT = int(os.getenv('PORT', 5000))


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------------- Token encryption (stdlib only) ----------------
def _key_bytes():
    return hashlib.sha256(SECRET_KEY.encode()).digest()


def _keystream(nonce, length):
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(_key_bytes(), nonce + counter.to_bytes(8, 'big'),
                         hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def encrypt(plaintext):
    nonce = secrets.token_bytes(16)
    pt = plaintext.encode()
    ct = bytes(a ^ b for a, b in zip(pt, _keystream(nonce, len(pt))))
    tag = hmac.new(_key_bytes(), nonce + ct, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(nonce + tag + ct).decode()


def decrypt(ciphertext):
    blob = base64.urlsafe_b64decode(ciphertext.encode())
    nonce, tag, ct = blob[:16], blob[16:32], blob[32:]
    expected = hmac.new(_key_bytes(), nonce + ct, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(tag, expected):
        raise ValueError('integrity check failed — SECRET_KEY changed?')
    ks = _keystream(nonce, len(ct))
    return bytes(a ^ b for a, b in zip(ct, ks)).decode()


# ---------------- Passwords (stdlib only) ----------------
def hash_password(password):
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100_000)
    return f'pbkdf2_sha256$100000${salt}${h.hex()}'


def verify_password(password, stored):
    try:
        algo, iters, salt, hash_hex = stored.split('$')
        if algo != 'pbkdf2_sha256':
            return False
        h = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(h.hex(), hash_hex)
    except Exception:
        return False


# ---------------- Database (stdlib sqlite3) ----------------
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    try:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_string TEXT UNIQUE NOT NULL,
                created_by INTEGER,
                max_accounts INTEGER DEFAULT 2,
                accounts_used INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                key_id INTEGER,
                discord_token TEXT NOT NULL,
                discord_user_id TEXT NOT NULL,
                discord_username TEXT,
                discord_avatar TEXT,
                is_owner INTEGER DEFAULT 0,
                channel_id TEXT,
                interval INTEGER DEFAULT 300,
                message TEXT,
                is_running INTEGER DEFAULT 0,
                last_sent_at TEXT,
                last_error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS vouches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT NOT NULL,
                content TEXT NOT NULL,
                rating INTEGER DEFAULT 5,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        try:
            conn.execute('PRAGMA journal_mode=WAL')
        except Exception:
            pass
        conn.commit()
    finally:
        conn.close()


# ---------------- Discord API (stdlib urllib) ----------------
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


def _discord_request(method, path, token, body=None):
    url = f'https://discord.com/api/v10{path}'
    headers = {
        'Authorization': token,
        'Content-Type': 'application/json',
        'User-Agent': UA,
        'Accept': '*/*',
    }
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode('utf-8', errors='replace')
            try:
                return resp.status, json.loads(text) if text else {}
            except json.JSONDecodeError:
                return resp.status, text
    except urllib.error.HTTPError as e:
        text = e.read().decode('utf-8', errors='replace')
        return e.code, text
    except urllib.error.URLError as e:
        return 0, f'Network error: {e.reason}'
    except Exception as e:
        return 0, f'{type(e).__name__}: {e}'


def discord_get_user(token):
    status, data = _discord_request('GET', '/users/@me', token)
    if status == 200 and isinstance(data, dict):
        return data
    print(f'[DISCORD] /users/@me status={status} body={str(data)[:200]}')
    return None


def discord_send_message(token, channel_id, content):
    status, data = _discord_request(
        'POST', f'/channels/{channel_id}/messages', token,
        body={'content': content},
    )
    if status in (200, 201):
        return True, 'OK'
    if status == 401:
        return False, 'Unauthorized — token is invalid or expired'
    if status == 403:
        return False, 'Forbidden — no permission to post in this channel'
    if status == 404:
        return False, 'Not Found — channel ID is wrong or account is not in that server'
    if status == 429:
        return False, f'Rate limited: {data}'
    return False, f'HTTP {status}: {str(data)[:300]}'


# ---------------- Advertiser threads ----------------
class Advertiser:
    def __init__(self, account_id, token, channel_id, interval, message):
        self.account_id = account_id
        self.token = token
        self.channel_id = str(channel_id)
        self.interval = max(5, int(interval))
        self.message = message
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _record(self, ok, detail):
        try:
            conn = get_db()
            try:
                if ok:
                    conn.execute(
                        'UPDATE accounts SET last_sent_at = ?, last_error = NULL WHERE id = ?',
                        (now_iso(), self.account_id)
                    )
                else:
                    conn.execute(
                        'UPDATE accounts SET last_error = ? WHERE id = ?',
                        (str(detail)[:500], self.account_id)
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f'[ADV {self.account_id}] DB record failed: {e}')

    def _run(self):
        while not self._stop.is_set():
            ok, detail = discord_send_message(self.token, self.channel_id, self.message)
            self._record(ok, detail)
            self._stop.wait(self.interval)


_advertisers = {}
_advertisers_lock = threading.Lock()


def start_advertiser(account_row):
    aid = account_row['id']
    with _advertisers_lock:
        old = _advertisers.pop(aid, None)
        if old:
            old.stop()
        token = decrypt(account_row['discord_token'])
        adv = Advertiser(
            account_id=aid,
            token=token,
            channel_id=account_row['channel_id'],
            interval=account_row['interval'],
            message=account_row['message'],
        )
        adv.start()
        _advertisers[aid] = adv


def stop_advertiser(account_id):
    with _advertisers_lock:
        adv = _advertisers.pop(account_id, None)
    if adv:
        adv.stop()


# ---------------- Flask ----------------
app = Flask(__name__)
app.secret_key = SECRET_KEY


def current_user():
    uid = session.get('uid')
    if not uid:
        return None
    conn = get_db()
    try:
        return conn.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
    finally:
        conn.close()


def login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not current_user():
            return jsonify(error='Not logged in'), 401
        return f(*a, **kw)
    return w


def admin_required(f):
    @wraps(f)
    def w(*a, **kw):
        u = current_user()
        if not u:
            return jsonify(error='Not logged in'), 401
        if not u['is_admin']:
            return jsonify(error='Admin only'), 403
        return f(*a, **kw)
    return w


def account_json(row):
    return {
        'id': row['id'],
        'discord_user_id': row['discord_user_id'],
        'discord_username': row['discord_username'],
        'discord_avatar': row['discord_avatar'],
        'is_owner': bool(row['is_owner']),
        'channel_id': row['channel_id'],
        'interval': row['interval'],
        'message': row['message'],
        'is_running': bool(row['is_running']),
        'last_sent_at': row['last_sent_at'],
        'last_error': row['last_error'],
        'created_at': row['created_at'],
    }


def key_json(row):
    return {
        'id': row['id'],
        'key_string': row['key_string'],
        'max_accounts': row['max_accounts'],
        'accounts_used': row['accounts_used'],
        'is_active': bool(row['is_active']),
        'created_at': row['created_at'],
    }


# ---- auth ----
@app.route('/')
def index():
    return render_template('index.html')


@app.post('/api/register')
def register():
    d = request.get_json() or {}
    username = (d.get('username') or '').strip()
    password = d.get('password') or ''
    if len(username) < 3 or len(password) < 6:
        return jsonify(error='Username 3+ chars, password 6+ chars'), 400
    conn = get_db()
    try:
        if conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone():
            return jsonify(error='Username already taken'), 400
        cur = conn.execute(
            'INSERT INTO users (username, password_hash) VALUES (?, ?)',
            (username, hash_password(password))
        )
        conn.commit()
        uid = cur.lastrowid
        session['uid'] = uid
        return jsonify(ok=True, user={'id': uid, 'username': username, 'is_admin': False})
    finally:
        conn.close()


@app.post('/api/login')
def login():
    d = request.get_json() or {}
    username = (d.get('username') or '').strip()
    password = d.get('password') or ''
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if not row or not verify_password(password, row['password_hash']):
            return jsonify(error='Invalid username or password'), 401
        session['uid'] = row['id']
        return jsonify(ok=True, user={
            'id': row['id'], 'username': row['username'], 'is_admin': bool(row['is_admin'])
        })
    finally:
        conn.close()


@app.post('/api/logout')
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get('/api/me')
def me():
    u = current_user()
    if not u:
        return jsonify(user=None)
    return jsonify(user={'id': u['id'], 'username': u['username'],
                         'is_admin': bool(u['is_admin'])})


# ---- accounts ----
@app.get('/api/accounts')
@login_required
def list_accounts():
    u = current_user()
    conn = get_db()
    try:
        rows = conn.execute(
            'SELECT * FROM accounts WHERE user_id = ? ORDER BY id DESC', (u['id'],)
        ).fetchall()
        return jsonify(accounts=[account_json(r) for r in rows])
    finally:
        conn.close()


@app.post('/api/accounts/link')
@login_required
def link_account():
    u = current_user()
    d = request.get_json() or {}
    token = (d.get('token') or '').strip()
    key_str = (d.get('key') or '').strip()

    if not token:
        return jsonify(error='Token required'), 400
    if token.lower().startswith('bot '):
        return jsonify(error='Remove the "Bot " prefix — use the raw user token'), 400

    info = discord_get_user(token)
    if not info:
        return jsonify(error='Invalid Discord token'), 400

    discord_id = str(info['id'])
    is_owner = discord_id in OWNER_IDS

    conn = get_db()
    try:
        if conn.execute('SELECT id FROM accounts WHERE discord_user_id = ?',
                        (discord_id,)).fetchone():
            return jsonify(error='This Discord account is already linked'), 400

        key = None
        if not is_owner:
            if not key_str:
                return jsonify(error='Access key required'), 400
            key = conn.execute('SELECT * FROM keys WHERE key_string = ?',
                               (key_str,)).fetchone()
            if not key or not key['is_active']:
                return jsonify(error='Invalid or revoked key'), 400
            if key['accounts_used'] >= key['max_accounts']:
                return jsonify(error='Key usage limit reached'), 400

        cur = conn.execute('''
            INSERT INTO accounts (user_id, key_id, discord_token, discord_user_id,
                discord_username, discord_avatar, is_owner, message, interval)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            u['id'],
            key['id'] if key else None,
            encrypt(token),
            discord_id,
            info.get('username'),
            info.get('avatar'),
            1 if is_owner else 0,
            "🚀 Check out this amazing offer! Limited time only.",
            300,
        ))
        if key:
            conn.execute('UPDATE keys SET accounts_used = accounts_used + 1 WHERE id = ?',
                         (key['id'],))
        if is_owner and not u['is_admin']:
            conn.execute('UPDATE users SET is_admin = 1 WHERE id = ?', (u['id'],))
        conn.commit()
        row = conn.execute('SELECT * FROM accounts WHERE id = ?', (cur.lastrowid,)).fetchone()
        return jsonify(ok=True, account=account_json(row), promoted=is_owner)
    finally:
        conn.close()


@app.delete('/api/accounts/<int:aid>')
@login_required
def unlink_account(aid):
    u = current_user()
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM accounts WHERE id = ?', (aid,)).fetchone()
        if not row:
            return jsonify(error='Not found'), 404
        if row['user_id'] != u['id'] and not u['is_admin']:
            return jsonify(error='Forbidden'), 403
        stop_advertiser(aid)
        if row['key_id']:
            conn.execute('UPDATE keys SET accounts_used = MAX(0, accounts_used - 1) WHERE id = ?',
                         (row['key_id'],))
        conn.execute('DELETE FROM accounts WHERE id = ?', (aid,))
        conn.commit()
        return jsonify(ok=True)
    finally:
        conn.close()


@app.patch('/api/accounts/<int:aid>/config')
@login_required
def update_config(aid):
    u = current_user()
    d = request.get_json() or {}
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM accounts WHERE id = ?', (aid,)).fetchone()
        if not row:
            return jsonify(error='Not found'), 404
        if row['user_id'] != u['id'] and not u['is_admin']:
            return jsonify(error='Forbidden'), 403

        channel_id = str(d.get('channel_id', row['channel_id'] or '')).strip()
        try:
            interval = max(5, int(d.get('interval') or row['interval'] or 300))
        except (ValueError, TypeError):
            return jsonify(error='Invalid interval'), 400
        message = d.get('message', row['message'])

        conn.execute(
            'UPDATE accounts SET channel_id = ?, interval = ?, message = ? WHERE id = ?',
            (channel_id, interval, message, aid)
        )
        conn.commit()
        row = conn.execute('SELECT * FROM accounts WHERE id = ?', (aid,)).fetchone()

        # Restart thread with new config if it was running
        if row['is_running']:
            try:
                start_advertiser(row)
            except Exception as e:
                conn.execute('UPDATE accounts SET is_running = 0, last_error = ? WHERE id = ?',
                             (f'restart failed: {e}', aid))
                conn.commit()

        return jsonify(ok=True, account=account_json(row))
    finally:
        conn.close()


@app.post('/api/accounts/<int:aid>/start')
@login_required
def start_account(aid):
    u = current_user()
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM accounts WHERE id = ?', (aid,)).fetchone()
        if not row:
            return jsonify(error='Not found'), 404
        if row['user_id'] != u['id'] and not u['is_admin']:
            return jsonify(error='Forbidden'), 403
        if row['is_running']:
            return jsonify(error='Already running'), 400
        if not row['channel_id'] or not row['message']:
            return jsonify(error='Set channel ID and message first'), 400

        try:
            start_advertiser(row)
        except Exception as e:
            conn.execute('UPDATE accounts SET last_error = ? WHERE id = ?',
                         (str(e)[:500], aid))
            conn.commit()
            return jsonify(error=str(e)), 500

        conn.execute('UPDATE accounts SET is_running = 1, last_error = NULL WHERE id = ?',
                     (aid,))
        conn.commit()
        return jsonify(ok=True)
    finally:
        conn.close()


@app.post('/api/accounts/<int:aid>/stop')
@login_required
def stop_account(aid):
    u = current_user()
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM accounts WHERE id = ?', (aid,)).fetchone()
        if not row:
            return jsonify(error='Not found'), 404
        if row['user_id'] != u['id'] and not u['is_admin']:
            return jsonify(error='Forbidden'), 403
        stop_advertiser(aid)
        conn.execute('UPDATE accounts SET is_running = 0 WHERE id = ?', (aid,))
        conn.commit()
        return jsonify(ok=True)
    finally:
        conn.close()


@app.post('/api/accounts/<int:aid>/test')
@login_required
def test_send(aid):
    u = current_user()
    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM accounts WHERE id = ?', (aid,)).fetchone()
        if not row:
            return jsonify(error='Not found'), 404
        if row['user_id'] != u['id'] and not u['is_admin']:
            return jsonify(error='Forbidden'), 403
        if not row['channel_id'] or not row['message']:
            return jsonify(error='Set channel ID and message first'), 400
        try:
            token = decrypt(row['discord_token'])
        except Exception as e:
            return jsonify(ok=False, error=str(e), output=f'DECRYPT FAILED: {e}')

        ok, msg = discord_send_message(token, row['channel_id'], row['message'])
        if ok:
            conn.execute('UPDATE accounts SET last_sent_at = ?, last_error = NULL WHERE id = ?',
                         (now_iso(), aid))
        else:
            conn.execute('UPDATE accounts SET last_error = ? WHERE id = ?',
                         (msg[:500], aid))
        conn.commit()
        return jsonify(ok=ok, output=('SEND OK' if ok else msg))
    finally:
        conn.close()

# --- NEW ENDPOINT FOR CHANNEL / DM INFO ---
@app.post('/api/accounts/<int:aid>/channel_info')
@login_required
def channel_info(aid):
    u = current_user()
    d = request.get_json() or {}
    channel_id = d.get('channel_id')

    if not channel_id or not str(channel_id).isdigit():
        return jsonify(error='Invalid channel ID'), 400

    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM accounts WHERE id = ?', (aid,)).fetchone()
        if not row: return jsonify(error='Account not found'), 404
        if row['user_id'] != u['id'] and not u['is_admin']:
            return jsonify(error='Forbidden'), 403
        token = decrypt(row['discord_token'])
    finally:
        conn.close()

    # Fetch channel from Discord API
    status, data = _discord_request('GET', f'/channels/{channel_id}', token)
    
    if status != 200 or not isinstance(data, dict):
        return jsonify(error='Channel not found or no access'), 404

    if data.get('type') == 1: # It's a DM
        recipients = data.get('recipients', [])
        if recipients:
            r = recipients[0]
            return jsonify(
                type='dm',
                name=r.get('global_name') or r.get('username'),
                avatar=r.get('avatar'),
                user_id=r.get('id')
            )
        return jsonify(error='DM recipient not found'), 404
    else:
        # It's a Guild Channel
        return jsonify(
            type='guild',
            name=data.get('name', 'unknown-channel')
        )


# ---- keys ----
@app.get('/api/keys')
@admin_required
def list_keys():
    conn = get_db()
    try:
        rows = conn.execute('SELECT * FROM keys ORDER BY id DESC').fetchall()
        return jsonify(keys=[key_json(r) for r in rows])
    finally:
        conn.close()


@app.post('/api/keys/generate')
@admin_required
def gen_key():
    u = current_user()
    d = request.get_json() or {}
    try:
        count = max(1, min(50, int(d.get('count') or 1)))
    except (ValueError, TypeError):
        count = 1
    try:
        max_acc = max(1, min(10, int(d.get('max_accounts') or 2)))
    except (ValueError, TypeError):
        max_acc = 2
    conn = get_db()
    try:
        ids = []
        for _ in range(count):
            ks = 'NX-' + secrets.token_hex(8).upper()
            cur = conn.execute(
                'INSERT INTO keys (key_string, created_by, max_accounts) VALUES (?, ?, ?)',
                (ks, u['id'], max_acc)
            )
            ids.append(cur.lastrowid)
        conn.commit()
        placeholders = ','.join('?' * len(ids))
        rows = conn.execute(f'SELECT * FROM keys WHERE id IN ({placeholders})', ids).fetchall()
        return jsonify(keys=[key_json(r) for r in rows])
    finally:
        conn.close()


@app.delete('/api/keys/<int:kid>')
@admin_required
def revoke_key(kid):
    conn = get_db()
    try:
        conn.execute('UPDATE keys SET is_active = 0 WHERE id = ?', (kid,))
        conn.commit()
        return jsonify(ok=True)
    finally:
        conn.close()


# ---- vouches ----
@app.get('/api/vouches')
def list_vouches():
    conn = get_db()
    try:
        rows = conn.execute('SELECT * FROM vouches ORDER BY id DESC LIMIT 100').fetchall()
        return jsonify(vouches=[{
            'id': r['id'], 'username': r['username'], 'content': r['content'],
            'rating': r['rating'], 'created_at': r['created_at'],
        } for r in rows])
    finally:
        conn.close()


@app.post('/api/vouches')
@login_required
def add_vouch():
    u = current_user()
    d = request.get_json() or {}
    content = (d.get('content') or '').strip()
    if len(content) < 5:
        return jsonify(error='Vouch too short (5+ chars)'), 400
    try:
        rating = max(1, min(5, int(d.get('rating') or 5)))
    except (ValueError, TypeError):
        rating = 5
    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO vouches (user_id, username, content, rating) VALUES (?, ?, ?, ?)',
            (u['id'], u['username'], content, rating)
        )
        conn.commit()
        return jsonify(ok=True)
    finally:
        conn.close()


# ---- admin ----
@app.get('/api/admin/overview')
@admin_required
def admin_overview():
    conn = get_db()
    try:
        return jsonify(
            users=conn.execute('SELECT COUNT(*) FROM users').fetchone()[0],
            accounts=conn.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],
            running=conn.execute('SELECT COUNT(*) FROM accounts WHERE is_running = 1').fetchone()[0],
            keys=conn.execute('SELECT COUNT(*) FROM keys').fetchone()[0],
            active_keys=conn.execute('SELECT COUNT(*) FROM keys WHERE is_active = 1').fetchone()[0],
            vouches=conn.execute('SELECT COUNT(*) FROM vouches').fetchone()[0],
        )
    finally:
        conn.close()


@app.get('/api/admin/users')
@admin_required
def admin_users():
    conn = get_db()
    try:
        rows = conn.execute('''
            SELECT u.*, (SELECT COUNT(*) FROM accounts WHERE user_id = u.id) as cnt
            FROM users u ORDER BY u.id DESC
        ''').fetchall()
        return jsonify(users=[{
            'id': r['id'], 'username': r['username'], 'is_admin': bool(r['is_admin']),
            'accounts': r['cnt'], 'created_at': r['created_at'],
        } for r in rows])
    finally:
        conn.close()


@app.post('/api/admin/users/<int:uid>/toggle-admin')
@admin_required
def toggle_admin(uid):
    conn = get_db()
    try:
        conn.execute('UPDATE users SET is_admin = NOT is_admin WHERE id = ?', (uid,))
        conn.commit()
        row = conn.execute('SELECT is_admin FROM users WHERE id = ?', (uid,)).fetchone()
        return jsonify(ok=True, is_admin=bool(row['is_admin']))
    finally:
        conn.close()


# ---------------- Startup ----------------
def startup():
    init_db()
    # Threads died with the previous process — reset running flags
    conn = get_db()
    try:
        conn.execute('UPDATE accounts SET is_running = 0 WHERE is_running = 1')
        conn.commit()
    finally:
        conn.close()
    if SECRET_KEY == 'dev-secret-change-me':
        print('⚠️  WARNING: SECRET_KEY not set in .env — sessions will reset each run.')
    print(f'Server:   http://localhost:{PORT}')
    print(f'Database: {DB_PATH}')
    print(f'Owners:   {OWNER_IDS or "(none)"}')


if __name__ == '__main__':
    startup()
    app.run(host='0.0.0.0', port=PORT, debug=False,
            use_reloader=False, threaded=True)