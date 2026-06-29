"""
Field declarations for all Clear Skies config sections.

This module executes registration at import time.  Simply importing
`weewx_clearskies_config.registry` (via __init__.py) is sufficient to
populate the registry singleton.

Canonical values (locked per OPERATIONS-MANUAL.md §4.1):
  - Earthquake defaults: radius=250, min_magnitude=2.0, default_days=30
  - Theme modes: "auto-sunrise-sunset" (full name; not "auto-sunrise")
  - TLS modes: self-signed, acme_http01, acme_dns01, manual, behind_proxy
"""

from .fields import ConfigField, FieldOption, ValidationRule, Condition
from .registry import registry
from .sections import SectionDef

# ---------------------------------------------------------------------------
# 1. Earthquake Settings
# ---------------------------------------------------------------------------

registry.register_section(
    SectionDef(
        section_id="earthquakes",
        display_name="Earthquake Settings",
        domain_group="dashboard",
        config_source="stack.conf",
        custom_template="",
        custom_handler="",
    ),
    (
        ConfigField(
            field_id="earthquakes.radius_km",
            field_type="number",
            label="Radius (km)",
            help_text="Search radius for earthquake data",
            default="250",
            validation=(
                ValidationRule("min", 1),
                ValidationRule("max", 20000),
            ),
            config_target="stack.conf:earthquakes",
            config_key="radius_km",
        ),
        ConfigField(
            field_id="earthquakes.min_magnitude",
            field_type="number",
            label="Minimum Magnitude",
            default="2.0",
            validation=(
                ValidationRule("min", 0),
                ValidationRule("max", 10),
                ValidationRule("step", 0.1),
            ),
            config_target="stack.conf:earthquakes",
            config_key="min_magnitude",
        ),
        ConfigField(
            field_id="earthquakes.default_days",
            field_type="select",
            label="Default Time Range",
            default="30",
            options=(
                FieldOption(value="1", label="1 day"),
                FieldOption(value="7", label="7 days"),
                FieldOption(value="14", label="14 days"),
                FieldOption(value="30", label="30 days"),
            ),
            config_target="stack.conf:earthquakes",
            config_key="default_days",
        ),
    ),
)

# ---------------------------------------------------------------------------
# 2. Social Links
# ---------------------------------------------------------------------------

registry.register_section(
    SectionDef(
        section_id="social",
        display_name="Social Links",
        domain_group="appearance",
        config_source="branding.json",
    ),
    (
        ConfigField(
            field_id="social.facebook_url",
            field_type="url",
            label="Facebook URL",
            config_target="branding.json:social",
            config_key="facebook_url",
        ),
        ConfigField(
            field_id="social.twitter_url",
            field_type="url",
            label="Twitter / X URL",
            config_target="branding.json:social",
            config_key="twitter_url",
        ),
        ConfigField(
            field_id="social.instagram_url",
            field_type="url",
            label="Instagram URL",
            config_target="branding.json:social",
            config_key="instagram_url",
        ),
        ConfigField(
            field_id="social.youtube_url",
            field_type="url",
            label="YouTube URL",
            config_target="branding.json:social",
            config_key="youtube_url",
        ),
    ),
)

# ---------------------------------------------------------------------------
# 3. Analytics & Privacy
# ---------------------------------------------------------------------------

registry.register_section(
    SectionDef(
        section_id="analytics",
        display_name="Analytics & Privacy",
        domain_group="appearance",
        config_source="branding.json",
    ),
    (
        ConfigField(
            field_id="analytics.google_analytics_id",
            field_type="text",
            label="Google Analytics ID",
            placeholder="G-XXXXXXXXXX",
            validation=(
                ValidationRule("pattern", r"G-[A-Za-z0-9]+"),
            ),
            config_target="branding.json",
            config_key="google_analytics_id",
        ),
        ConfigField(
            field_id="analytics.privacy_regions",
            field_type="select",
            label="Privacy Regions",
            default="global",
            options=(
                FieldOption(value="global", label="Global"),
                FieldOption(value="eu_gdpr", label="EU (GDPR)"),
                FieldOption(value="us_ccpa", label="US (CCPA)"),
                FieldOption(value="both", label="Both (EU + US)"),
            ),
            config_target="branding.json",
            config_key="privacy_regions",
        ),
    ),
)

# ---------------------------------------------------------------------------
# 4. Webcam
# ---------------------------------------------------------------------------

registry.register_section(
    SectionDef(
        section_id="webcam",
        display_name="Webcam",
        domain_group="dashboard",
        config_source="stack.conf",
    ),
    (
        ConfigField(
            field_id="webcam.webcam_enabled",
            field_type="boolean",
            label="Enable Webcam",
            default=False,
            config_target="stack.conf:webcam",
            config_key="enabled",
        ),
        ConfigField(
            field_id="webcam.image_url",
            field_type="url",
            label="Still Image URL",
            default="/webcam/weather_cam.jpg",
            config_target="stack.conf:webcam",
            config_key="image_url",
        ),
        ConfigField(
            field_id="webcam.video_url",
            field_type="url",
            label="Timelapse Video URL",
            default="/webcam/weewx_timelapse.mp4",
            config_target="stack.conf:webcam",
            config_key="video_url",
        ),
        ConfigField(
            field_id="webcam.refresh_interval",
            field_type="number",
            label="Refresh Interval (seconds)",
            default="60",
            validation=(
                ValidationRule("min", 10),
                ValidationRule("max", 3600),
            ),
            config_target="stack.conf:webcam",
            config_key="refresh_interval",
        ),
    ),
)

# ---------------------------------------------------------------------------
# 5. Branding
# ---------------------------------------------------------------------------

registry.register_section(
    SectionDef(
        section_id="branding",
        display_name="Branding",
        domain_group="appearance",
        config_source="branding.json",
    ),
    (
        ConfigField(
            field_id="branding.site_title",
            field_type="text",
            label="Site Title",
            validation=(ValidationRule("max_length", 100),),
            config_target="branding.json",
            config_key="site_title",
        ),
        ConfigField(
            field_id="branding.copyright_entity",
            field_type="text",
            label="Copyright Entity",
            validation=(ValidationRule("max_length", 100),),
            config_target="branding.json",
            config_key="copyright_entity",
        ),
        ConfigField(
            field_id="branding.accent",
            field_type="radio_swatch",
            label="Accent Color",
            default="blue",
            options=(
                FieldOption(value="blue", label="Blue"),
                FieldOption(value="teal", label="Teal"),
                FieldOption(value="indigo", label="Indigo"),
                FieldOption(value="purple", label="Purple"),
                FieldOption(value="green", label="Green"),
                FieldOption(value="amber", label="Amber"),
            ),
            config_target="branding.json",
            config_key="accent",
        ),
        ConfigField(
            field_id="branding.default_theme_mode",
            field_type="radio",
            label="Default Theme Mode",
            default="auto-os",
            options=(
                FieldOption(value="light", label="Light"),
                FieldOption(value="dark", label="Dark"),
                FieldOption(value="auto-os", label="Auto (OS)"),
                FieldOption(
                    value="auto-sunrise-sunset",
                    label="Auto (sunrise/sunset)",
                ),
            ),
            config_target="branding.json",
            config_key="default_theme_mode",
        ),
        ConfigField(
            field_id="branding.favicon_url",
            field_type="url",
            label="Favicon URL",
            config_target="branding.json",
            config_key="favicon_url",
        ),
        ConfigField(
            field_id="branding.custom_css_url",
            field_type="url",
            label="Custom CSS URL",
            config_target="branding.json",
            config_key="custom_css_url",
        ),
        ConfigField(
            field_id="branding.logo_light_url",
            field_type="file_or_url",
            label="Logo (Light Mode)",
            config_target="branding.json",
            config_key="logo_light_url",
        ),
        ConfigField(
            field_id="branding.logo_dark_url",
            field_type="file_or_url",
            label="Logo (Dark Mode)",
            config_target="branding.json",
            config_key="logo_dark_url",
        ),
        ConfigField(
            field_id="branding.logo_alt",
            field_type="text",
            label="Logo Alt Text",
            validation=(ValidationRule("max_length", 200),),
            config_target="branding.json",
            config_key="logo_alt",
        ),
    ),
)

# ---------------------------------------------------------------------------
# 6. Pages Visibility
# ---------------------------------------------------------------------------
# "now" is always visible and cannot be hidden — excluded from options.

registry.register_section(
    SectionDef(
        section_id="pages",
        display_name="Pages Visibility",
        domain_group="dashboard",
        config_source="pages.json",
    ),
    (
        ConfigField(
            field_id="pages.hidden_pages",
            field_type="checkbox_group",
            label="Hidden Pages",
            help_text='Select pages to hide from navigation. "Now" is always visible.',
            options=(
                FieldOption(value="forecast", label="Forecast"),
                FieldOption(value="charts", label="Charts"),
                FieldOption(value="almanac", label="Almanac"),
                FieldOption(value="earthquakes", label="Earthquakes"),
                FieldOption(value="records", label="Records"),
                FieldOption(value="reports", label="Reports"),
                FieldOption(value="about", label="About"),
                FieldOption(value="legal", label="Legal"),
            ),
            config_target="pages.json",
            config_key="hidden_pages",
            admin_landing_display=True,
        ),
    ),
)

# ---------------------------------------------------------------------------
# 7. TLS
# ---------------------------------------------------------------------------

_TLS_MODE_FIELD_ID = "tls.mode"

registry.register_section(
    SectionDef(
        section_id="tls",
        display_name="TLS",
        domain_group="advanced",
        config_source="stack.conf",
    ),
    (
        ConfigField(
            field_id=_TLS_MODE_FIELD_ID,
            field_type="radio",
            label="TLS Mode",
            options=(
                FieldOption(
                    value="self-signed",
                    label="Self-signed (development)",
                ),
                FieldOption(
                    value="acme_http01",
                    label="ACME HTTP-01 (Let's Encrypt, HTTP)",
                ),
                FieldOption(
                    value="acme_dns01",
                    label="ACME DNS-01 (Let's Encrypt, DNS)",
                ),
                FieldOption(
                    value="manual",
                    label="Manual (supply cert + key paths)",
                ),
                FieldOption(
                    value="behind_proxy",
                    label="Behind Proxy (TLS terminated upstream)",
                ),
            ),
            config_target="stack.conf:tls",
            config_key="mode",
        ),
        # Show for either ACME mode (OR logic: two Condition objects)
        ConfigField(
            field_id="tls.domain",
            field_type="text",
            label="Domain",
            conditions=(
                Condition(field_id=_TLS_MODE_FIELD_ID, operator="eq", value="acme_http01"),
                Condition(field_id=_TLS_MODE_FIELD_ID, operator="eq", value="acme_dns01"),
            ),
            config_target="stack.conf:tls",
            config_key="domain",
        ),
        ConfigField(
            field_id="tls.acme_email",
            field_type="text",
            label="ACME Email",
            conditions=(
                Condition(field_id=_TLS_MODE_FIELD_ID, operator="eq", value="acme_http01"),
                Condition(field_id=_TLS_MODE_FIELD_ID, operator="eq", value="acme_dns01"),
            ),
            config_target="stack.conf:tls",
            config_key="acme_email",
        ),
        ConfigField(
            field_id="tls.dns_provider",
            field_type="select",
            label="DNS Provider",
            options=(
                FieldOption(value="cloudflare", label="Cloudflare"),
                FieldOption(value="route53", label="AWS Route 53"),
                FieldOption(value="google_cloud", label="Google Cloud DNS"),
                FieldOption(value="digitalocean", label="DigitalOcean"),
                FieldOption(value="namecheap", label="Namecheap"),
            ),
            conditions=(
                Condition(field_id=_TLS_MODE_FIELD_ID, operator="eq", value="acme_dns01"),
            ),
            config_target="stack.conf:tls",
            config_key="dns_provider",
        ),
        ConfigField(
            field_id="tls.dns_api_token",
            field_type="password",
            label="DNS API Token",
            is_secret=True,
            secret_env_key="WEEWX_CLEARSKIES_TLS_DNS_API_TOKEN",
            conditions=(
                Condition(field_id=_TLS_MODE_FIELD_ID, operator="eq", value="acme_dns01"),
            ),
            config_target="stack.conf:tls",
            config_key="dns_api_token",
        ),
        ConfigField(
            field_id="tls.cert_path",
            field_type="text",
            label="Certificate Path",
            conditions=(
                Condition(field_id=_TLS_MODE_FIELD_ID, operator="eq", value="manual"),
            ),
            config_target="stack.conf:tls",
            config_key="cert_path",
        ),
        ConfigField(
            field_id="tls.key_path",
            field_type="text",
            label="Key Path",
            conditions=(
                Condition(field_id=_TLS_MODE_FIELD_ID, operator="eq", value="manual"),
            ),
            config_target="stack.conf:tls",
            config_key="key_path",
        ),
    ),
)

# ---------------------------------------------------------------------------
# 8. Sky Classification
# ---------------------------------------------------------------------------

registry.register_section(
    SectionDef(
        section_id="sky_classification",
        display_name="Sky Classification",
        domain_group="advanced",
        config_source="api.conf",
        custom_template="sky_classification.html",
    ),
    (
        ConfigField(
            field_id="sky_classification.scatter_few_max",
            field_type="number",
            label="Few Max (Km)",
            default="0.97",
            validation=(
                ValidationRule("min", 0),
                ValidationRule("max", 1),
                ValidationRule("step", 0.01),
            ),
            config_target="api.conf:sky_classification",
            config_key="scatter_few_max",
        ),
        ConfigField(
            field_id="sky_classification.scatter_sct_max",
            field_type="number",
            label="Scattered Max (Km)",
            default="0.85",
            validation=(
                ValidationRule("min", 0),
                ValidationRule("max", 1),
                ValidationRule("step", 0.01),
            ),
            config_target="api.conf:sky_classification",
            config_key="scatter_sct_max",
        ),
        ConfigField(
            field_id="sky_classification.scatter_bkn_max",
            field_type="number",
            label="Broken Max (Km)",
            default="0.52",
            validation=(
                ValidationRule("min", 0),
                ValidationRule("max", 1),
                ValidationRule("step", 0.01),
            ),
            config_target="api.conf:sky_classification",
            config_key="scatter_bkn_max",
        ),
        ConfigField(
            field_id="sky_classification.overcast_km_threshold",
            field_type="number",
            label="Overcast Km Threshold",
            default="0.15",
            validation=(
                ValidationRule("min", 0),
                ValidationRule("max", 1),
                ValidationRule("step", 0.01),
            ),
            config_target="api.conf:sky_classification",
            config_key="overcast_km_threshold",
        ),
        ConfigField(
            field_id="sky_classification.overcast_kv_threshold",
            field_type="number",
            label="Overcast Kv Threshold",
            default="0.03",
            validation=(
                ValidationRule("min", 0),
                ValidationRule("max", 1),
                ValidationRule("step", 0.01),
            ),
            config_target="api.conf:sky_classification",
            config_key="overcast_kv_threshold",
        ),
        ConfigField(
            field_id="sky_classification.sza_min_elevation",
            field_type="number",
            label="SZA Minimum Elevation (°)",
            default="5.0",
            validation=(
                ValidationRule("min", 0),
                ValidationRule("max", 90),
                ValidationRule("step", 0.1),
            ),
            config_target="api.conf:sky_classification",
            config_key="sza_min_elevation",
        ),
    ),
)
