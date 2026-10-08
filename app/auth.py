r"""auth.py - username/password accounts + signed session cookies, for the HOSTED deployment only.

A single officer running the app on their own machine needs no login at all - see HOSTED in server.py
(true only when the platform sets $PORT, e.g. Render). Stdlib only, no dependencies.

Storage: data\auth.sqlite - deliberately separate from lawbase.sqlite (the judgment/statute database),
so pulling a data update (app\update.py) never touches accounts. On a host with no persistent disk this
file - and every account in it - is wiped on restart; see HOSTING.md.
"""
import base64, hashlib, hmac, json, os, secrets, sqlite3, time
from contextlib import contextmanager

ROUNDS = 200_000


@contextmanager
def connection(root):
    c = connect(root)
    try:
        with c:
            yield c
    finally:
        c.close()


def db_path(root):
    return os.path.join(root, "data", "auth.sqlite")


def connect(root):
    path = db_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, salt TEXT, hash TEXT, "
              "is_admin INTEGER, created TEXT)")
    if "session_epoch" not in {r[1] for r in c.execute("PRAGMA table_info(users)")}:
        c.execute("ALTER TABLE users ADD COLUMN session_epoch TEXT NOT NULL DEFAULT ''")
        c.commit()
    return c


def _hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt, hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ROUNDS).hex()


def create_user(root, username, password, is_admin=False):
    username = username.strip().lower()
    if not username or not password:
        raise ValueError("username and password are required")
    salt, h = _hash(password)
    with connection(root) as c:
        try:
            c.execute("INSERT INTO users VALUES (?,?,?,?,?,?)",
                      (username, salt, h, int(bool(is_admin)), time.strftime("%Y-%m-%d"), secrets.token_hex(16)))
        except sqlite3.IntegrityError:
            raise ValueError("That username already exists; use password reset to change its password") from None


def set_password(root, username, password):
    if not password:
        raise ValueError("password is required")
    salt, h = _hash(password)
    with connection(root) as c:
        cur = c.execute("UPDATE users SET salt=?, hash=?, session_epoch=? WHERE username=?", (salt, h, secrets.token_hex(16), username.strip().lower()))
        if cur.rowcount == 0:
            raise ValueError("no such user")


def delete_user(root, username):
    with connection(root) as c:
        c.execute("DELETE FROM users WHERE username=?", (username.strip().lower(),))


def list_users(root):
    with connection(root) as c:
        return [dict(username=u, is_admin=bool(a), created=cr)
                for u, a, cr in c.execute("SELECT username, is_admin, created FROM users ORDER BY username")]


def count_users(root):
    with connection(root) as c:
        return c.execute("SELECT count(*) FROM users").fetchone()[0]


def verify_login(root, username, password):
    with connection(root) as c:
        row = c.execute("SELECT salt, hash, is_admin FROM users WHERE username=?",
                        (username.strip().lower(),)).fetchone()
    if not row:
        return None
    salt, h, is_admin = row
    _, check = _hash(password, salt)
    if not hmac.compare_digest(check, h):
        return None
    return {"username": username.strip().lower(), "is_admin": bool(is_admin)}


# ------------------------------------------------------------------ sessions (HMAC-signed cookie, no server state)
def _secret(root):
    env = os.environ.get("LAWBASE_SECRET")
    if env:
        return env.encode()
    # No LAWBASE_SECRET set: persist a generated one so sessions survive a process restart (not a redeploy
    # without a persistent disk - see HOSTING.md). Setting LAWBASE_SECRET explicitly is strongly preferred.
    path = os.path.join(root, "data", "secret.key")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    key = secrets.token_bytes(32)
    with open(path, "wb") as f:
        f.write(key)
    return key


def make_session(root, user, ttl_days=14):
    with connection(root) as c:
        row = c.execute("SELECT session_epoch FROM users WHERE username=?", (user["username"],)).fetchone()
    if not row:
        raise ValueError("no such user")
    payload = json.dumps({"u": user["username"], "a": user["is_admin"], "v": row[0], "exp": time.time() + ttl_days * 86400}).encode()
    sig = hmac.new(_secret(root), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload).decode() + "." + base64.urlsafe_b64encode(sig).decode()


def verify_session(root, token):
    try:
        p64, s64 = token.split(".")
        payload = base64.urlsafe_b64decode(p64 + "=" * (-len(p64) % 4))
        sig = base64.urlsafe_b64decode(s64 + "=" * (-len(s64) % 4))
        if not hmac.compare_digest(sig, hmac.new(_secret(root), payload, hashlib.sha256).digest()):
            return None
        data = json.loads(payload)
        if data["exp"] <= time.time():
            return None
        with connection(root) as c:
            row = c.execute("SELECT is_admin,session_epoch FROM users WHERE username=?", (data["u"],)).fetchone()
        if not row or data.get("v", "") != row[1]:
            return None
        return {"username": data["u"], "is_admin": bool(row[0])}
    except Exception:
        return None
