"""Tests for the admin "Imagery" provider section (Phase LM / LM-3).

General-purpose orthophoto imagery provider for the marine heatmap
background (API-MANUAL §12a) — configured through the SAME generic
config-section editor mechanism already shipped for radar/aqi/forecast/
alerts/earthquakes (admin/routes.py _SECTION_META / _SECTION_ALLOWED_KEYS /
update_managed_region), via a dedicated imagery_section.html template
(NOT provider_section.html — imagery's api_key is a plain api.conf value,
not a secrets.env credential, and NAIP/ESRI have no connectivity test).

KATs covered (plan §LM-3, verbatim):
  (a) select NAIP -> apply -> api.conf [imagery] carries provider=naip
  (b) select ESRI -> apply -> provider=esri
  (c) round-trip: save -> reload -> values preserved
  (d) substitute (lead-accepted, tightened): the imagery POST handler only
      ever touches the [imagery] section and enforces its own key allowlist
      -- no other section (in particular no marine/model config) is ever
      written by this handler.
Plus: Auto is the default, and api_key stores without being required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from weewx_clearskies_config.config.reader import get_section

_MANAGED_HEADER = "# Managed by weewx-clearskies-config on 2026-01-01.\n"
_REGION_BEGIN = "# MANAGED REGION BEGIN\n"
_REGION_END = "# MANAGED REGION END\n"
_FREE_FORM_NOTE = "# Free-form region below — the configuration UI does not touch this.\n"


def _write_api_conf(config_dir: Path, extra_managed: str = "") -> Path:
    """Write a minimal api.conf with MANAGED REGION markers into *config_dir*.

    *extra_managed* is raw ConfigObj-format text inserted inside the managed
    region (used to seed a pre-existing [marine] section for the
    no-cross-section-write KAT).
    """
    conf = config_dir / "api.conf"
    content = (
        _MANAGED_HEADER
        + _REGION_BEGIN
        + "[server]\nbind_host = 127.0.0.1\nbind_port = 8765\n\n"
        + extra_managed
        + _REGION_END
        + _FREE_FORM_NOTE
    )
    conf.write_text(content, encoding="utf-8")
    return conf


@pytest.fixture()
def authed_client_with_conf(authed_client, config_dir: Path):
    """The shared conftest authed_client, with a bare api.conf pre-seeded."""
    _write_api_conf(config_dir)
    return authed_client


# ---------------------------------------------------------------------------
# GET — default (no [imagery] section yet) shows Auto
# ---------------------------------------------------------------------------


def test_imagery_get_defaults_to_auto_when_unconfigured(authed_client_with_conf):
    resp = authed_client_with_conf.get("/admin/config/api/imagery")
    assert resp.status_code == 200
    assert 'value="auto"' in resp.text
    assert "selected" in resp.text  # the auto <option> carries the selected attribute
    assert "Auto" in resp.text or "auto" in resp.text


# ---------------------------------------------------------------------------
# KAT (a) / (b): provider selection round-trips into api.conf [imagery]
# ---------------------------------------------------------------------------


def test_imagery_post_naip_writes_provider_to_api_conf(authed_client_with_conf, config_dir: Path):
    resp = authed_client_with_conf.post(
        "/admin/config/api/imagery", data={"provider": "naip", "api_key": ""}
    )
    assert resp.status_code == 200

    values = get_section("api", "imagery", config_dir)
    assert values.get("provider") == "naip"


def test_imagery_post_esri_writes_provider_to_api_conf(authed_client_with_conf, config_dir: Path):
    resp = authed_client_with_conf.post(
        "/admin/config/api/imagery", data={"provider": "esri", "api_key": ""}
    )
    assert resp.status_code == 200

    values = get_section("api", "imagery", config_dir)
    assert values.get("provider") == "esri"


def test_imagery_post_auto_writes_provider_to_api_conf(authed_client_with_conf, config_dir: Path):
    resp = authed_client_with_conf.post(
        "/admin/config/api/imagery", data={"provider": "auto", "api_key": ""}
    )
    assert resp.status_code == 200

    values = get_section("api", "imagery", config_dir)
    assert values.get("provider") == "auto"


# ---------------------------------------------------------------------------
# KAT (c): round-trip — save -> reload -> values preserved (provider + api_key)
# ---------------------------------------------------------------------------


def test_imagery_round_trip_save_reload_preserves_provider_and_api_key(
    authed_client_with_conf, config_dir: Path
):
    post_resp = authed_client_with_conf.post(
        "/admin/config/api/imagery",
        data={"provider": "naip", "api_key": "future-proof-key"},
    )
    assert post_resp.status_code == 200

    # Reload via GET — the form must reflect exactly what was saved.
    get_resp = authed_client_with_conf.get("/admin/config/api/imagery")
    assert get_resp.status_code == 200
    assert 'value="future-proof-key"' in get_resp.text

    values = get_section("api", "imagery", config_dir)
    assert values.get("provider") == "naip"
    assert values.get("api_key") == "future-proof-key"


def test_imagery_api_key_not_required_for_save(authed_client_with_conf, config_dir: Path):
    """api_key must never block saving a provider selection — it is optional
    future-proofing (API-MANUAL §12a; NAIP/ESRI do not use it in v1)."""
    resp = authed_client_with_conf.post(
        "/admin/config/api/imagery", data={"provider": "esri"}
    )
    assert resp.status_code == 200

    values = get_section("api", "imagery", config_dir)
    assert values.get("provider") == "esri"
    assert values.get("api_key", "") == ""


# ---------------------------------------------------------------------------
# KAT (d) substitute: the handler enforces its own key allowlist and never
# writes any section other than [imagery] — in particular, a pre-existing
# [marine] section (which is what feeds SWAN) is untouched byte-for-byte.
# ---------------------------------------------------------------------------


def test_imagery_post_never_writes_marine_section(config_dir: Path, authed_client):
    """Seed a [marine] section, save imagery config, assert marine bytes unchanged.

    This is the structural substitute for the plan's "zero diff in any SWAN
    input file" KAT: this repo has no SWAN artifacts to diff (nothing under
    tests/ references SWAN), so the actual boundary this KAT guards is that
    the imagery admin handler never touches any section but its own.
    """
    marine_block = (
        "[marine]\n"
        "[[locations]]\n"
        "[[[hb]]]\n"
        "name = Huntington Beach\n"
        "lat = 33.6553\n"
        "lon = -118.0067\n"
        "\n"
    )
    _write_api_conf(config_dir, extra_managed=marine_block)
    before = (config_dir / "api.conf").read_text(encoding="utf-8")
    marine_section_before = get_section("api", "marine", config_dir)
    assert marine_section_before.get("name") is None  # nested — top-level get_section shape check only

    resp = authed_client.post(
        "/admin/config/api/imagery", data={"provider": "naip", "api_key": "x"}
    )
    assert resp.status_code == 200

    after = (config_dir / "api.conf").read_text(encoding="utf-8")
    # [marine] block content must survive byte-for-byte (only [imagery] was added).
    assert marine_block.strip() in after
    # The [server] section written by _write_api_conf must also survive untouched.
    assert "bind_host = 127.0.0.1" in after
    assert "bind_port = 8765" in after
    # Sanity: the file did change (imagery section was in fact added).
    assert before != after
    assert "[imagery]" in after


def test_imagery_post_drops_unexpected_keys(authed_client_with_conf, config_dir: Path):
    """A submission carrying a key outside the {provider, api_key} allowlist
    (e.g. an attempt to smuggle in tile_cache_ttl_seconds, or any other
    section's field) must be silently dropped, never written."""
    resp = authed_client_with_conf.post(
        "/admin/config/api/imagery",
        data={
            "provider": "naip",
            "api_key": "",
            "tile_cache_ttl_seconds": "1",
            "structures": "malicious",
        },
    )
    assert resp.status_code == 200

    conf_text = (config_dir / "api.conf").read_text(encoding="utf-8")
    assert "tile_cache_ttl_seconds" not in conf_text
    assert "structures" not in conf_text


def test_imagery_section_in_allowed_keys_is_exactly_provider_and_api_key():
    """Direct assertion on the allowlist itself — the actual boundary the
    tightened KAT (d) guards."""
    from weewx_clearskies_config.admin.routes import _SECTION_ALLOWED_KEYS

    assert _SECTION_ALLOWED_KEYS[("api", "imagery")] == frozenset({"provider", "api_key"})
