import os
import sys
import traceback
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

# --- Sanity check: make sure we have the real discord.py-self, not the stub ---
try:
    import discord
    _problems = []
    if not hasattr(discord, 'Client'):  _problems.append('Client')
    if not hasattr(discord, 'Intents'): _problems.append('Intents')
    if not hasattr(discord, 'Bot'):     _problems.append('Bot')
    if _problems:
        print('=' * 60, flush=True)
        print('[FATAL] Wrong "discord" package installed.', flush=True)
        print(f'[FATAL] Missing attributes: {", ".join(_problems)}', flush=True)
        print(f'[FATAL] discord.__file__ = {discord.__file__}', flush=True)
        print(f'[FATAL] discord.__version__ = {getattr(discord, "__version__", "N/A")}', flush=True)
        print('[FATAL] Fix:', flush=True)
        print('        pip uninstall -y discord discord.py discord.py-self', flush=True)
        print('        pip install -U discord.py-self', flush=True)
        print('=' * 60, flush=True)
        sys.exit(2)
except ImportError as e:
    print(f'[FATAL] Cannot import discord: {e}', flush=True)
    print('        pip install -U discord.py-self', flush=True)
    sys.exit(2)

from app import app, db, LinkedAccount, decrypt  # noqa: E402
from discord.ext import tasks  # noqa: E402

def log(*args):
    print(*args, flush=True)


def _load(account_id):
    with app.app_context():
        acc = LinkedAccount.query.get(account_id)
        if not acc:
            log(f'[{account_id}] Account not found'); return None
        try:
            token = decrypt(acc.discord_token)
        except Exception as e:
            log(f'[{account_id}] CANNOT DECRYPT TOKEN (SECRET_KEY changed?): {e}'); return None
        if not acc.channel_id or not acc.message:
            log(f'[{account_id}] MISSING config: channel={acc.channel_id!r} msg_len={len(acc.message or "")}')
            return None
        try:
            channel_id = int(acc.channel_id)
        except ValueError:
            log(f'[{account_id}] INVALID channel_id={acc.channel_id!r}'); return None
        return {
            'token': token,
            'channel_id': channel_id,
            'interval': max(5, int(acc.interval or 300)),
            'message': acc.message,
        }


def _record_success(account_id):
    with app.app_context():
        a = LinkedAccount.query.get(account_id)
        if a:
            a.last_sent_at = datetime.utcnow()
            a.last_error = None
            db.session.commit()


def _record_error(account_id, msg):
    with app.app_context():
        a = LinkedAccount.query.get(account_id)
        if a:
            a.last_error = str(msg)[:500]
            db.session.commit()


def _clear_running(account_id):
    with app.app_context():
        a = LinkedAccount.query.get(account_id)
        if a:
            a.is_running = False
            a.process_pid = None
            db.session.commit()


def main():
    if len(sys.argv) < 2:
        log('Usage: python runner.py <account_id>'); return
    account_id = int(sys.argv[1])
    cfg = _load(account_id)
    if not cfg:
        _clear_running(account_id); return

    log(f'[{account_id}] starting — channel={cfg["channel_id"]} interval={cfg["interval"]}s')

    client = discord.Client(intents=discord.Intents.default())

    async def resolve_channel():
        ch = client.get_channel(cfg['channel_id'])
        if ch is None:
            try:
                ch = await client.fetch_channel(cfg['channel_id'])
                log(f'[{account_id}] fetched channel via API (was not cached)')
            except Exception as e:
                log(f'[{account_id}] fetch_channel FAILED: {type(e).__name__}: {e}')
                _record_error(account_id, f'fetch_channel: {e}')
                return None
        return ch

    @tasks.loop(seconds=cfg['interval'])
    async def send_loop():
        ch = await resolve_channel()
        if ch is None:
            return
        try:
            await ch.send(cfg['message'])
            log(f'[{account_id}] SEND OK at {datetime.utcnow().isoformat()}')
            _record_success(account_id)
        except Exception as e:
            log(f'[{account_id}] send FAILED: {type(e).__name__}: {e}')
            _record_error(account_id, f'send: {e}')

    @client.event
    async def on_ready():
        log(f'[{account_id}] logged in as {client.user} (id={client.user.id})')
        log(f'[{account_id}] cached guilds={len(client.guilds)}')
        send_loop.start()

    try:
        client.run(cfg['token'])
    except discord.LoginFailure as e:
        log(f'[{account_id}] LOGIN FAILED (bad token): {e}')
        _record_error(account_id, f'LoginFailure: {e}')
    except Exception:
        log(f'[{account_id}] client crashed:')
        traceback.print_exc()
        _record_error(account_id, 'client crashed — see runner log')
    finally:
        _clear_running(account_id)


def main_once(account_id):
    cfg = _load(account_id)
    if not cfg:
        print('CONFIG INVALID', flush=True); return

    client = discord.Client(intents=discord.Intents.default())

    @client.event
    async def on_ready():
        print(f'logged in as {client.user} (id={client.user.id})', flush=True)
        try:
            ch = client.get_channel(cfg['channel_id'])
            if ch is None:
                ch = await client.fetch_channel(cfg['channel_id'])
                print('fetched channel via API', flush=True)
            await ch.send(cfg['message'])
            print('SEND OK', flush=True)
            _record_success(account_id)
        except Exception as e:
            print(f'SEND FAILED: {type(e).__name__}: {e}', flush=True)
            _record_error(account_id, f'test: {e}')
        finally:
            await client.close()

    try:
        client.run(cfg['token'])
    except discord.LoginFailure as e:
        print(f'LOGIN FAILED: {e}', flush=True)
        _record_error(account_id, f'LoginFailure: {e}')
    except Exception as e:
        print(f'CRASH: {type(e).__name__}: {e}', flush=True)
        traceback.print_exc()
        _record_error(account_id, f'test crash: {e}')


if __name__ == '__main__':
    main()