import os
import secrets
import time
from collections import defaultdict
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()

COOKIE_NAME = "clearskies_session"

# Rate-limit: block IP after this many failures within the window
_RATE_LIMIT_MAX_FAILURES = 5
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_THROTTLE_SECONDS = 60


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hash_str: str) -> bool:
    try:
        return _hasher.verify(hash_str, password)
    except VerifyMismatchError:
        return False


class BootstrapManager:
    def __init__(self) -> None:
        self._token: str | None = None

    def generate(self) -> str:
        self._token = secrets.token_hex(32)
        return self._token

    def validate(self, token: str) -> bool:
        if self._token is None:
            return False
        # constant-time compare to prevent timing attacks
        result = secrets.compare_digest(token, self._token)
        if result:
            self._token = None
        return result


class SessionManager:
    def __init__(self, tls_enabled: bool = False) -> None:
        self._sessions: dict[str, str] = {}
        self.tls_enabled = tls_enabled

    def create(self, username: str) -> str:
        session_id = secrets.token_urlsafe(32)
        self._sessions[session_id] = username
        return session_id

    def get_username(self, session_id: str) -> str | None:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    @property
    def cookie_kwargs(self) -> dict[str, object]:
        return {
            "key": COOKIE_NAME,
            "httponly": True,
            "samesite": "strict",
            "secure": self.tls_enabled,
            "path": "/",
        }


class RateLimiter:
    def __init__(self) -> None:
        # ip -> list of failure timestamps
        self._failures: dict[str, list[float]] = defaultdict(list)
        # ip -> throttle-until timestamp
        self._throttled: dict[str, float] = {}

    def _prune(self, ip: str) -> None:
        now = time.monotonic()
        cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
        self._failures[ip] = [t for t in self._failures[ip] if t > cutoff]

    def is_throttled(self, ip: str) -> bool:
        now = time.monotonic()
        throttle_until = self._throttled.get(ip, 0.0)
        return now < throttle_until

    def record_failure(self, ip: str) -> None:
        now = time.monotonic()
        self._prune(ip)
        self._failures[ip].append(now)
        if len(self._failures[ip]) >= _RATE_LIMIT_MAX_FAILURES:
            self._throttled[ip] = now + _RATE_LIMIT_THROTTLE_SECONDS
            self._failures[ip].clear()

    def record_success(self, ip: str) -> None:
        self._failures.pop(ip, None)
        self._throttled.pop(ip, None)


def _config_dir() -> Path:
    env_dir = os.environ.get("WEEWX_CLEARSKIES_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    system_dir = Path("/etc/weewx-clearskies")
    if system_dir.exists():
        return system_dir
    return Path.home() / ".config" / "weewx-clearskies"


def read_secrets() -> dict[str, str]:
    secrets_path = _config_dir() / "secrets.env"
    if not secrets_path.exists():
        return {}
    result: dict[str, str] = {}
    for line in secrets_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def write_secrets(data: dict[str, str]) -> None:
    config_dir = _config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    secrets_path = config_dir / "secrets.env"
    lines = [f"{k}={v}\n" for k, v in data.items()]
    secrets_path.write_text("".join(lines))
    try:
        secrets_path.chmod(0o600)
    except NotImplementedError:
        # Windows does not support POSIX chmod
        pass
