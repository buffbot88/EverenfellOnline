"""Auth: PHP-compatible sign algorithm + salted passwords + sessions.

Sign (LoginHelper.checkSign/generateSign, mirrored by gamesession.php):
  sign = md5(userId + 'xianlingkey' + timestamp)
Passwords: PHP stored plaintext; we store PBKDF2 (local-only improvement).
Sessions live in SQLite so a server restart does not log everyone out
(the browser keeps its mko_session cookie but the session must still exist).
"""
import hashlib
import hmac
import os
import secrets
import threading
import time

SIGN_KEY = 'xianlingkey'


def generate_sign(user_id, timestamp):
    return hashlib.md5(f'{user_id}{SIGN_KEY}{timestamp}'.encode()).hexdigest()


def check_sign(user_id, timestamp, verify):
    if not user_id or not timestamp or not verify:
        return False
    return hmac.compare_digest(generate_sign(user_id, timestamp), verify)


def hash_password(password):
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100_000)
    return f'pbkdf2${salt.hex()}${dk.hex()}'


def verify_password(password, stored):
    try:
        _, salt_hex, dk_hex = stored.split('$')
        dk = hashlib.pbkdf2_hmac('sha256', password.encode(),
                                 bytes.fromhex(salt_hex), 100_000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


class Sessions:
    """SQLite-backed sessions; captcha codes stay in memory (ephemeral)."""

    def __init__(self, store=None):
        self.store = store
        self._captcha = {}
        self._mem = {}
        self._lock = threading.Lock()

    def create(self, uid):
        tok = secrets.token_hex(16)
        if self.store:
            self.store.create_session(tok, uid)
        else:
            with self._lock:
                self._mem[tok] = {'uid': uid, 't': int(time.time())}
        return tok

    def get(self, tok):
        if not tok:
            return None
        if self.store:
            rec = self.store.get_session(tok)
        else:
            with self._lock:
                rec = self._mem.get(tok)
        if not rec:
            return None
        rec = dict(rec)
        rec['captcha'] = self._captcha.get(tok, '')
        return rec

    def set_captcha(self, tok, code):
        with self._lock:
            self._captcha[tok] = code
