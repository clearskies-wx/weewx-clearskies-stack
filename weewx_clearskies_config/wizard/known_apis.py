"""Fingerprint pinning storage for known Clear Skies API endpoints (ADR-038).

Implements TOFU (Trust On First Use) pinning: the operator provides an
expected fingerprint out-of-band (displayed by the stack installer); the
wizard verifies the live server fingerprint matches, then stores it.  On
subsequent connections the stored fingerprint is compared to the live cert —
a mismatch is a hard error, not a warning.

Pinned fingerprints are stored in ``known_apis.json`` in the config directory:

    {"https://192.168.7.20:8765": "SHA-256:AB:CD:..."}
"""

from __future__ import annotations

import hmac
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

_log = logging.getLogger(__name__)

_KNOWN_APIS_FILENAME = "known_apis.json"


def load_known_apis(config_dir: Path) -> dict[str, str]:
    """Load the known_apis.json fingerprint store.

    Args:
        config_dir: Directory where known_apis.json lives.

    Returns:
        Dict mapping API URL strings to their pinned fingerprint strings.
        Returns an empty dict if the file does not exist or cannot be parsed.
    """
    path = config_dir / _KNOWN_APIS_FILENAME
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            _log.warning("known_apis.json has unexpected format; ignoring")
            return {}
        # Filter out non-string values defensively.
        return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("Could not load known_apis.json: %s", exc)
        return {}


def save_known_api(config_dir: Path, api_url: str, fingerprint: str) -> None:
    """Persist a fingerprint for an API URL.

    Reads the existing store, updates (or inserts) the entry for *api_url*,
    and writes back atomically via a temp file + rename.

    Args:
        config_dir: Directory where known_apis.json lives (created if absent).
        api_url: The API base URL, e.g. "https://192.168.7.20:8765".
        fingerprint: The fingerprint to store, e.g. "SHA-256:AB:CD:...".
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    known = load_known_apis(config_dir)
    known[api_url] = fingerprint

    path = config_dir / _KNOWN_APIS_FILENAME
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(known, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        _log.error("Could not write known_apis.json: %s", exc)
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        _log.warning("Could not set permissions on %s", path)
    _log.info("Pinned fingerprint for %s", api_url)


def get_known_fingerprint(config_dir: Path, api_url: str) -> str | None:
    """Return the stored fingerprint for an API URL, or None if not pinned.

    Args:
        config_dir: Directory where known_apis.json lives.
        api_url: The API base URL to look up.

    Returns:
        The stored fingerprint string, or None if the URL is not in the store.
    """
    return load_known_apis(config_dir).get(api_url)


def verify_or_pin_fingerprint(
    config_dir: Path,
    api_url: str,
    expected_fingerprint: str,
) -> tuple[bool, str | None]:
    """TOFU fingerprint verification with automatic pinning on first trust.

    Behaviour:

    - **First visit** (api_url not yet in known_apis.json):
      1. Fetch the server's live fingerprint.
      2. Compare with *expected_fingerprint* using constant-time comparison.
      3. On match: pin it (save to known_apis.json) and return ``(True, None)``.
      4. On mismatch: return ``(False, "Fingerprint mismatch: expected X, got Y")``.

    - **Reconnect** (api_url already in known_apis.json):
      1. Fetch the server's live fingerprint.
      2. Compare with the **stored** fingerprint (ignores *expected_fingerprint*).
      3. On match: return ``(True, None)``.
      4. On mismatch: return ``(False, "WARNING: API certificate has changed! ...")``.

    Args:
        config_dir: Directory where known_apis.json lives.
        api_url: The API base URL, e.g. "https://192.168.7.20:8765".
        expected_fingerprint: Operator-provided fingerprint (used only on first
            visit; ignored on reconnects where the stored value is authoritative).

    Returns:
        ``(True, None)`` on success, ``(False, error_message)`` on failure.
    """
    from weewx_clearskies_config.wizard.api_client import ApiClient

    host, port = _parse_host_port(api_url)
    if host is None or port is None:
        return False, f"Cannot parse host and port from API URL: {api_url!r}"

    _log.info("Fetching live TLS fingerprint from %s:%d", host, port)
    try:
        live_fingerprint = ApiClient.fetch_fingerprint(host, port)
    except OSError as exc:
        return False, f"Could not retrieve TLS fingerprint from {api_url}: {exc}"

    stored_fingerprint = get_known_fingerprint(config_dir, api_url)

    if stored_fingerprint is None:
        # First visit — compare against the operator-supplied expected value.
        if hmac.compare_digest(live_fingerprint, expected_fingerprint):
            try:
                save_known_api(config_dir, api_url, live_fingerprint)
            except OSError as exc:
                return False, f"Fingerprint matched but could not save to known_apis.json: {exc}"
            _log.info("First-visit TOFU: fingerprint verified and pinned for %s", api_url)
            return True, None
        else:
            return (
                False,
                (
                    f"Fingerprint mismatch: expected {expected_fingerprint!r}, "
                    f"got {live_fingerprint!r}. "
                    "Check that you have copied the fingerprint exactly as shown by the installer."
                ),
            )
    else:
        # Reconnect — compare against the pinned value, not the operator input.
        if hmac.compare_digest(live_fingerprint, stored_fingerprint):
            _log.info("Reconnect: fingerprint matches stored pin for %s", api_url)
            return True, None
        else:
            return (
                False,
                (
                    f"WARNING: API certificate has changed! "
                    f"Stored fingerprint: {stored_fingerprint!r}, "
                    f"live fingerprint: {live_fingerprint!r}. "
                    "This may indicate a certificate renewal (re-run the installer to update the pin) "
                    "or a man-in-the-middle attack. Do not proceed until you have verified the cause."
                ),
            )


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _parse_host_port(api_url: str) -> tuple[str | None, int | None]:
    """Extract the bare host and port from an API URL.

    Handles IPv6 bracket notation correctly (urllib.parse strips the brackets
    from netloc.hostname automatically).

    Args:
        api_url: A URL string such as "https://192.168.7.20:8765" or
            "https://[2001:db8::1]:8765".

    Returns:
        ``(host, port)`` where host is a bare hostname or IP address (no
        brackets), and port is an integer.  Returns ``(None, None)`` if the
        URL cannot be parsed or is missing a port.
    """
    try:
        parsed = urlparse(api_url)
        host = parsed.hostname  # strips brackets from IPv6 literals
        port = parsed.port
        if not host or port is None:
            return None, None
        return host, port
    except Exception:  # noqa: BLE001
        return None, None
