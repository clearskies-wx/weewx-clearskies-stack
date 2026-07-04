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
            help_text="Search radius in kilometers from your station. Earthquakes beyond this distance are not shown on the Seismic page.",
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
            help_text="Only show earthquakes at or above this magnitude on the Moment Magnitude scale (Mw). The scale is logarithmic — each whole number is roughly 32 times more energy.",
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
            help_text="How many days of earthquake history to show by default. Visitors can change this on the Seismic page.",
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
            help_text="Full URL to your Facebook page or profile.",
            config_target="branding.json:social",
            config_key="facebook_url",
        ),
        ConfigField(
            field_id="social.twitter_url",
            field_type="url",
            label="Twitter / X URL",
            help_text="Full URL to your Twitter / X profile.",
            config_target="branding.json:social",
            config_key="twitter_url",
        ),
        ConfigField(
            field_id="social.instagram_url",
            field_type="url",
            label="Instagram URL",
            help_text="Full URL to your Instagram profile.",
            config_target="branding.json:social",
            config_key="instagram_url",
        ),
        ConfigField(
            field_id="social.youtube_url",
            field_type="url",
            label="YouTube URL",
            help_text="Full URL to your YouTube channel.",
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
            help_text="Google Analytics 4 Measurement ID (starts with G-). Leave blank to disable tracking entirely.",
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
            help_text="Controls the consent banner shown to visitors based on their geographic region.",
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
            help_text="Show the Webcam page on the dashboard. When disabled, the page is hidden from navigation.",
            default=False,
            config_target="stack.conf:webcam",
            config_key="enabled",
        ),
        ConfigField(
            field_id="webcam.image_url",
            field_type="text",
            label="Still Image URL",
            help_text="Path or URL of the current webcam snapshot image, refreshed by your webcam software.",
            default="/webcam/weather_cam.jpg",
            config_target="stack.conf:webcam",
            config_key="image_url",
        ),
        ConfigField(
            field_id="webcam.video_url",
            field_type="text",
            label="Timelapse Video URL",
            help_text="Path or URL of the timelapse video file (MP4 format).",
            default="/webcam/weewx_timelapse.mp4",
            config_target="stack.conf:webcam",
            config_key="video_url",
        ),
        ConfigField(
            field_id="webcam.refresh_interval",
            field_type="number",
            label="Refresh Interval (seconds)",
            help_text="How often (in seconds) the dashboard re-fetches the webcam snapshot. Lower values show more current images.",
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
            help_text="Displayed in the browser tab and dashboard header.",
            validation=(ValidationRule("max_length", 100),),
            config_target="branding.json",
            config_key="site_title",
        ),
        ConfigField(
            field_id="branding.copyright_entity",
            field_type="text",
            label="Copyright Entity",
            help_text="Shown in the dashboard footer (e.g. your name or organisation).",
            validation=(ValidationRule("max_length", 100),),
            config_target="branding.json",
            config_key="copyright_entity",
        ),
        ConfigField(
            field_id="branding.accent",
            field_type="radio_swatch",
            label="Accent Color",
            help_text="Primary highlight colour used for buttons, links, and active states across the dashboard.",
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
            help_text="Controls the initial theme shown to visitors. Auto (OS) follows the visitor's system preference.",
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
            field_type="text",
            label="Favicon URL",
            help_text="Path or URL of the browser tab icon (ICO or PNG, 32x32 or 64x64 px). Leave blank for the default.",
            config_target="branding.json",
            config_key="favicon_url",
        ),
        ConfigField(
            field_id="branding.custom_css_url",
            field_type="url",
            label="Custom CSS URL",
            help_text="URL to a custom CSS file loaded after default styles. Use for advanced visual overrides.",
            config_target="branding.json",
            config_key="custom_css_url",
        ),
        ConfigField(
            field_id="branding.logo_light_url",
            field_type="file_or_url",
            label="Logo (Light Mode)",
            help_text="Upload a file or enter a path/URL. PNG or SVG with transparent background, max 500 KB.",
            config_target="branding.json",
            config_key="logo_light_url",
        ),
        ConfigField(
            field_id="branding.logo_dark_url",
            field_type="file_or_url",
            label="Logo (Dark Mode)",
            help_text="Upload a file or enter a path/URL. PNG or SVG with transparent background, max 500 KB.",
            config_target="branding.json",
            config_key="logo_dark_url",
        ),
        ConfigField(
            field_id="branding.logo_alt",
            field_type="text",
            label="Logo Alt Text",
            help_text="Describes the logo for screen readers. Required when a logo is uploaded.",
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
            help_text="Select pages to hide from the dashboard navigation. The Now page is always visible and cannot be hidden.",
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
            help_text="How Caddy handles HTTPS certificates. Self-signed for development; ACME for automatic Let’s Encrypt; Manual for your own certs; Behind Proxy when TLS is handled upstream.",
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
            help_text="The domain name for your weather dashboard (e.g. weather.example.com). Required for ACME certificate issuance.",
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
            help_text="Email address for Let's Encrypt certificate expiry notifications.",
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
            help_text="DNS provider whose API will create the validation record for DNS-01 verification.",
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
            help_text="API token for your DNS provider. Used to create DNS records for certificate validation. Stored securely in secrets.env.",
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
            help_text="Filesystem path to your TLS certificate file (PEM format).",
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
            help_text="Filesystem path to your TLS private key file (PEM format).",
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
            help_text="Km threshold between Clear and Few Clouds. Above this value, sky is classified as Clear.",
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
            help_text="Km threshold between Few Clouds and Scattered. Above this value (and below Few Max), sky is Few Clouds.",
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
            help_text="Km threshold between Scattered and Broken. Above this value (and below Scattered Max), sky is Scattered.",
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
            help_text="Km threshold for Overcast classification based on the clearness index.",
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
            help_text="Kv variability threshold for Overcast classification.",
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
            help_text="Minimum sun elevation (degrees above horizon) for sky classification to operate. Below this, conditions default to the provider forecast.",
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
