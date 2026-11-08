"""Keys and connection settings. Each one comes from, in order: what was typed
on the setup page this run, what was remembered in the computer's own password
store (Windows Credential Manager, macOS Keychain), or an environment
variable. A .env file at the repo root (git ignores it) is read into the
environment at startup, without overriding variables already set. Nothing is
written to a file in the project."""
import os
from pathlib import Path

_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.is_file():
    for _line in _env_file.read_text(encoding="utf-8-sig").splitlines():
        _name, _eq, _value = _line.strip().partition("=")
        if _eq and _name and not _name.startswith("#"):
            os.environ.setdefault(_name.strip(), _value.strip().strip('"').strip("'"))

try:
    import keyring
except ImportError:      # the server still runs; "remember" is just unavailable
    keyring = None

SERVICE = "porchlight"

FIELDS = {
    "GEMINI_API_KEY": {"secret": True},
    "GEMINI_MODEL": {"secret": False},
    "AESO_API_KEY": {"secret": True},
    "DATABASE_URL": {"secret": True},
    "AUTH0_DOMAIN": {"secret": False},
    "AUTH0_CLIENT_ID": {"secret": False},
    "AUTH0_AUDIENCE": {"secret": False},
    "PORCHLIGHT_DEVICE_KEY": {"secret": True},
    "PORCHLIGHT_LINK_SECRET": {"secret": True},
}

_typed = {}
_remembered = {}


def can_remember():
    if keyring is None:
        return False
    try:
        keyring.get_password(SERVICE, "probe")
        return True
    except Exception:
        return False


def load_remembered():
    if not can_remember():
        return
    for name in FIELDS:
        try:
            value = keyring.get_password(SERVICE, name)
        except Exception:
            value = None
        if value:
            _remembered[name] = value


def get(name, default=None):
    return _typed.get(name) or _remembered.get(name) or os.environ.get(name) or default


def source(name):
    if _typed.get(name):
        return "typed"
    if _remembered.get(name):
        return "remembered"
    if os.environ.get(name):
        return "environment"
    return None


def put(name, value, remember):
    """Empty value clears what was typed or remembered (an environment
    variable, if any, then shows through again)."""
    value = (value or "").strip()
    _typed.pop(name, None)
    if value:
        _typed[name] = value
    if remember and can_remember():
        try:
            if value:
                keyring.set_password(SERVICE, name, value)
                _remembered[name] = value
            else:
                keyring.delete_password(SERVICE, name)
                _remembered.pop(name, None)
        except Exception:
            pass


def describe(name):
    value = get(name)
    shown = None
    if value:
        shown = ("•••• " + value[-4:]) if FIELDS[name]["secret"] and len(value) > 8 else value
        if FIELDS[name]["secret"] and len(value) <= 8:
            shown = "set"
    return {"set": bool(value), "source": source(name), "shown": shown}
