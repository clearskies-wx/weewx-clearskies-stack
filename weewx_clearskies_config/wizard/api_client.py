"""TLS-pinned API client for wizard-to-API communication (ADR-038).

The wizard communicates with the Clear Skies API during initial setup using a
TOFU (Trust On First Use) fingerprint-pinning scheme rather than standard CA
verification.  The API serves a self-signed certificate; the operator provides
the expected fingerprint out-of-band (displayed by the stack installer), and
the wizard verifies it before establishing a session.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import socket
import ssl
from typing import Any
from urllib.parse import urlparse

import httpx

_log = logging.getLogger(__name__)

# Default timeout for most API calls (seconds).
_DEFAULT_TIMEOUT = 10.0
# Extended timeout for db-test — the remote DB probe may be slow.
_DB_TEST_TIMEOUT = 30.0


class ApiClientError(Exception):
    """Raised when an API call fails with a non-2xx response.

    Attributes:
        status_code: The HTTP status code returned by the API.
        detail: The error message extracted from the response body.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error {status_code}: {detail}")


class ApiClient:
    """Handles TLS-pinned communication with the Clear Skies API during setup.

    All requests use httpx with verify=False because the API presents a
    self-signed certificate.  Fingerprint verification is performed at a higher
    level via known_apis.py before a session is established; subsequent calls
    rely on the already-verified session_id rather than re-checking the cert on
    every request.

    Two authentication modes are supported:

    - **First-run mode** (``session_id`` set): the wizard exchanged a one-time
      trust token for a setup session ID during step 1.  Requests carry
      ``Authorization: Bearer <session_id>``.

    - **Re-run mode** (``proxy_secret`` set): setup is already complete.  The
      API accepts ``X-Clearskies-Proxy-Auth: <proxy_secret>`` on its setup
      endpoints so the wizard can read current configuration without needing a
      new trust token.  Only one of the two should be provided; if both are
      given, ``session_id`` takes precedence.
    """

    def __init__(
        self,
        api_url: str,
        session_id: str | None = None,
        proxy_secret: str | None = None,
    ) -> None:
        """
        Args:
            api_url: Base URL of the Clear Skies API, e.g. "https://192.168.7.20:8765".
            session_id: An already-established session ID, if one exists from a
                prior handshake.  Pass None before calling handshake().
            proxy_secret: The shared proxy secret from secrets.env, used for
                re-run mode when setup is already complete.  Ignored when
                session_id is also provided.
        """
        self._api_url = api_url.rstrip("/")
        self._session_id = session_id
        self._proxy_secret = proxy_secret

    # ------------------------------------------------------------------
    # Fingerprint acquisition
    # ------------------------------------------------------------------

    @staticmethod
    def fetch_fingerprint(host: str, port: int) -> str:
        """Connect to the API's TLS port and return its certificate fingerprint.

        Uses socket.getaddrinfo() to support both IPv4 and IPv6 hosts.
        Does NOT verify the certificate — the whole point is to capture the
        raw fingerprint for out-of-band verification.

        Args:
            host: Hostname or IP address (bare, without brackets for IPv6).
            port: TLS port number.

        Returns:
            Fingerprint string in "SHA-256:AB:CD:EF:..." format (uppercase,
            colon-separated byte pairs).

        Raises:
            OSError: If the connection or certificate retrieval fails.
        """
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        # Resolve to all address families so IPv6 hosts work (getaddrinfo
        # also handles bare IPv6 literals without brackets).
        try:
            addr_infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise OSError(f"Could not resolve '{host}:{port}': {exc}") from exc

        last_exc: OSError | None = None
        for family, sock_type, proto, _canon, sockaddr in addr_infos:
            try:
                with socket.socket(family, sock_type, proto) as raw_sock:
                    raw_sock.settimeout(10)
                    raw_sock.connect(sockaddr)
                    with ctx.wrap_socket(raw_sock, server_hostname=host) as tls_sock:
                        der: bytes = tls_sock.getpeercert(binary_form=True)  # type: ignore[assignment]
                digest = hashlib.sha256(der).digest()
                fingerprint = "SHA-256:" + ":".join(f"{b:02X}" for b in digest)
                _log.info(
                    "Fetched TLS fingerprint from %s:%d (family %s)",
                    host,
                    port,
                    family.name,
                )
                return fingerprint
            except OSError as exc:
                last_exc = exc
                continue

        raise OSError(
            f"Could not connect to '{host}:{port}' to retrieve TLS fingerprint"
        ) from last_exc

    # ------------------------------------------------------------------
    # Session establishment
    # ------------------------------------------------------------------

    def handshake(self, token: str) -> str:
        """Exchange a trust token for a setup session ID.

        POST /setup/handshake with the one-time trust token issued by the API
        installer.  On success, stores the returned session_id for subsequent
        calls.

        Args:
            token: The one-time trust token (obtained out-of-band from the
                API stack installer).

        Returns:
            The new session_id string.

        Raises:
            ApiClientError: If the API returns a non-2xx response.
        """
        _log.info("Performing setup handshake with API at %s", self._api_url)
        response = self._request(
            "POST",
            "/setup/handshake",
            json={"token": token},
            timeout=_DEFAULT_TIMEOUT,
            # No Authorization header yet — this is the bootstrap call.
            include_auth=False,
        )
        data: dict[str, Any] = response.json()
        session_id: str = data["session_id"]
        self._session_id = session_id
        _log.info("Handshake succeeded; session established")
        return session_id

    # ------------------------------------------------------------------
    # Setup API calls (all require an active session)
    # ------------------------------------------------------------------

    def get_db_defaults(self) -> dict[str, Any]:
        """GET /setup/db-defaults — DB connection defaults from weewx.conf.

        Returns:
            Dict with keys such as "host", "port", "user", "db_name".
        """
        _log.info("Fetching DB defaults from API")
        response = self._request("GET", "/setup/db-defaults", timeout=_DEFAULT_TIMEOUT)
        result: dict[str, Any] = response.json()
        return result

    def test_db(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        name: str,
    ) -> dict[str, Any]:
        """POST /setup/db-test — test a DB connection via the API.

        The API performs the actual connection attempt (it has DB access; the
        wizard does not).  Uses an extended timeout because the probe may be
        slow on a distant or unresponsive DB host.

        Args:
            host: Database hostname or IP.
            port: Database port.
            user: Database username.
            password: Database password.
            name: Database name.

        Returns:
            Dict with keys:
                "success" (bool), "version" (str | None), "error" (str | None).
        """
        _log.info("Requesting DB test for %s@%s:%d/%s via API", user, host, port, name)
        response = self._request(
            "POST",
            "/setup/db-test",
            json={
                "host": host,
                "port": port,
                "user": user,
                "password": password,
                "name": name,
            },
            timeout=_DB_TEST_TIMEOUT,
        )
        result: dict[str, Any] = response.json()
        return result

    def get_schema(self) -> dict[str, Any]:
        """GET /setup/schema — column schema from the connected DB.

        Returns:
            Dict describing the weewx archive schema (column names, types,
            canonical mappings).
        """
        _log.info("Fetching schema from API")
        response = self._request("GET", "/setup/schema", timeout=_DEFAULT_TIMEOUT)
        result: dict[str, Any] = response.json()
        return result

    def get_station(self) -> dict[str, Any]:
        """GET /setup/station — station identity from weewx.conf.

        Returns:
            Dict with keys such as "station_name", "latitude", "longitude",
            "altitude_meters", "timezone".
        """
        _log.info("Fetching station identity from API")
        response = self._request("GET", "/setup/station", timeout=_DEFAULT_TIMEOUT)
        result: dict[str, Any] = response.json()
        return result

    def apply(self, config: dict[str, Any]) -> dict[str, Any]:
        """POST /setup/apply — send the final wizard config to the API.

        Args:
            config: The complete wizard configuration dict to apply.

        Returns:
            API response dict (typically confirms success or lists written files).
        """
        _log.info("Sending apply config to API")
        response = self._request(
            "POST",
            "/setup/apply",
            json=config,
            timeout=_DEFAULT_TIMEOUT,
        )
        result: dict[str, Any] = response.json()
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        include_auth: bool = True,
    ) -> httpx.Response:
        """Execute a single HTTP request against the API.

        Args:
            method: HTTP method ("GET", "POST", etc.).
            path: URL path relative to api_url (must start with "/").
            json: Optional JSON body for POST requests.
            timeout: Request timeout in seconds.
            include_auth: If True (default), include the Authorization header.
                Set to False for the handshake call which has no session yet.

        Returns:
            The httpx.Response on success (2xx).

        Raises:
            ApiClientError: On non-2xx responses.
            httpx.RequestError: On network-level failures (propagated to caller).
        """
        url = self._api_url + path
        headers: dict[str, str] = {"Content-Type": "application/json"} if json is not None else {}

        if include_auth:
            if self._session_id is not None:
                # First-run mode: Bearer token from handshake.
                # Deliberately not logging the session_id value.
                headers["Authorization"] = f"Bearer {self._session_id}"
            elif self._proxy_secret is not None:
                # Re-run mode: shared proxy secret accepted by setup endpoints
                # once setup is already complete (ADR-038).
                headers["X-Clearskies-Proxy-Auth"] = self._proxy_secret
            else:
                raise ApiClientError(401, "No session established — call handshake() first")

        with httpx.Client(verify=False, timeout=timeout) as client:  # noqa: S501
            response = client.request(method, url, headers=headers, json=json)

        if response.is_success:
            return response

        # Extract a human-readable detail from the response body.
        detail = _extract_error_detail(response)
        _log.warning(
            "API call %s %s returned %d: %s",
            method,
            path,
            response.status_code,
            detail,
        )
        raise ApiClientError(response.status_code, detail)


def _extract_error_detail(response: httpx.Response) -> str:
    """Return a human-readable error string from a non-2xx response.

    Tries to parse RFC 9457 problem+json ("detail" key), then falls back to
    the raw response text.
    """
    try:
        body = response.json()
        if isinstance(body, dict):
            return str(body.get("detail") or body.get("message") or body.get("error") or response.text)
    except Exception:  # noqa: BLE001
        pass
    return response.text or f"HTTP {response.status_code}"
