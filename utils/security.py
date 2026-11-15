import time
import json
import hashlib
import secrets
import threading
import bleach
from config import LOGIN_RE

# ============= ПАРОЛИ =============
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"pbkdf2_sha256${salt}${dk.hex()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt, hash_hex = stored.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
        return secrets.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False

# ============= РУЧНАЯ ВАЛИДАЦИЯ =============
def validate_login_data(body):
    if not isinstance(body, dict):
        return None, "invalid_json"
    login = body.get("login")
    password = body.get("password")
    if not isinstance(login, str) or not isinstance(password, str):
        return None, "invalid_data"
    login = login.strip().lower()
    if not LOGIN_RE.match(login):
        return None, "invalid_login_format"
    if not password:
        return None, "password_required"
    return {"login": login, "password": password}, None

# ============= RATE LIMITING =============
_login_attempts = {}
_login_lock = threading.Lock()

def _check_rate_limit(ip):
    now = time.time()
    with _login_lock:
        if ip not in _login_attempts:
            _login_attempts[ip] = []
        _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < 60]
        if len(_login_attempts[ip]) >= 5:
            return False
        _login_attempts[ip].append(now)
        return True

def _reset_rate_limit(ip):
    with _login_lock:
        _login_attempts.pop(ip, None)

# ============= XSS ЗАЩИТА =============
ALLOWED_TAGS = ['p', 'br', 'strong', 'b', 'i', 'em', 'u', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'blockquote', 'a', 'span', 'div', 'img']
ALLOWED_ATTRS = {
    'a': ['href', 'target', 'rel'],
    'td': ['colspan', 'rowspan'],
    'th': ['colspan', 'rowspan'],
    'img': ['src', 'alt', 'width', 'height'],
    '*': ['class']
}

def sanitize_html(html_str):
    if not html_str:
        return ""
    return bleach.clean(html_str, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)

# ============= JSON СЕРИАЛИЗАТОР =============
from datetime import datetime, date
from decimal import Decimal

def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

def _json_dumps(data):
    return json.dumps(data, ensure_ascii=False, default=_json_default)
