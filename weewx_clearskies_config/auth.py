import json
import logging
import os
import secrets
import time
from collections import defaultdict
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_log = logging.getLogger(__name__)

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


_BOOTSTRAP_TOKEN_KEY = "WEEWX_CLEARSKIES_BOOTSTRAP_TOKEN"


class BootstrapManager:
    def __init__(self, secrets_path: Path | None = None) -> None:
        self._token: str | None = None
        self._secrets_path = secrets_path
        if secrets_path is not None:
            self._token = self._load_or_generate(secrets_path)

    def _load_or_generate(self, secrets_path: Path) -> str:
        """Return the persisted bootstrap token, or generate and persist a new one."""
        existing: dict[str, str] = {}
        if secrets_path.exists():
            for line in secrets_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                existing[key.strip()] = value.strip()
        if _BOOTSTRAP_TOKEN_KEY in existing:
            return existing[_BOOTSTRAP_TOKEN_KEY]
        token = secrets.token_hex(32)
        existing[_BOOTSTRAP_TOKEN_KEY] = token
        self._write(secrets_path, existing)
        return token

    @staticmethod
    def _write(secrets_path: Path, data: dict[str, str]) -> None:
        secrets_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"{k}={v}\n" for k, v in data.items()]
        secrets_path.write_text("".join(lines), encoding="utf-8")
        try:
            secrets_path.chmod(0o600)
        except NotImplementedError:
            pass  # Windows does not support POSIX chmod

    def generate(self) -> str:
        self._token = secrets.token_hex(32)
        return self._token

    def check(self, token: str) -> bool:
        if self._token is None:
            return False
        return secrets.compare_digest(token, self._token)

    def validate(self, token: str) -> bool:
        if not self.check(token):
            return False
        self._token = None
        if self._secrets_path is not None and self._secrets_path.exists():
            existing: dict[str, str] = {}
            for line in self._secrets_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                existing[key.strip()] = value.strip()
            existing.pop(_BOOTSTRAP_TOKEN_KEY, None)
            self._write(self._secrets_path, existing)
        return True


class SessionManager:
    def __init__(
        self,
        tls_enabled: bool = False,
        sessions_file: Path | None = None,
        max_session_age: int = 604800,
    ) -> None:
        self._sessions: dict[str, dict] = {}
        self.tls_enabled = tls_enabled
        self._max_age = max_session_age
        self._sessions_file = sessions_file or (_config_dir() / "sessions.json")
        self._load()

    def create(self, username: str) -> str:
        session_id = secrets.token_urlsafe(32)
        self._sessions[session_id] = {"username": username, "created_at": time.time()}
        self._persist()
        return session_id

    def get_username(self, session_id: str) -> str | None:
        entry = self._sessions.get(session_id)
        if entry is None:
            return None
        if time.time() - entry["created_at"] > self._max_age:
            del self._sessions[session_id]
            self._persist()
            return None
        return entry["username"]

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._persist()

    def _persist(self) -> None:
        try:
            self._sessions_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._sessions_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._sessions), encoding="utf-8")
            os.replace(tmp, self._sessions_file)
        except OSError as exc:
            _log.warning("Could not persist sessions file: %s", exc)

    def _load(self) -> None:
        if not self._sessions_file.exists():
            return
        try:
            raw = json.loads(self._sessions_file.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("expected a JSON object")
            now = time.time()
            self._sessions = {
                sid: entry
                for sid, entry in raw.items()
                if isinstance(entry, dict)
                and "username" in entry
                and "created_at" in entry
                and isinstance(entry["created_at"], (int, float))
                and now - entry["created_at"] <= self._max_age
            }
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _log.warning("Could not load sessions file (starting fresh): %s", exc)
            self._sessions = {}

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


# Module-level cache for read_secrets(): (mtime, parsed_dict)
# Avoids re-reading and re-parsing the file on every request when it hasn't
# changed.  The cache is invalidated whenever the file's mtime changes.
_secrets_cache: tuple[float, dict[str, str]] | None = None


def read_secrets() -> dict[str, str]:
    global _secrets_cache  # noqa: PLW0603
    secrets_path = _config_dir() / "secrets.env"
    if not secrets_path.exists():
        return {}
    try:
        current_mtime = secrets_path.stat().st_mtime
    except OSError:
        return {}
    if _secrets_cache is not None and _secrets_cache[0] == current_mtime:
        return dict(_secrets_cache[1])
    result: dict[str, str] = {}
    for line in secrets_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    _secrets_cache = (current_mtime, result)
    return dict(result)


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
