# Weather Data Providers Reference

This page explains every external data provider that Clear Skies can connect to and helps you choose the right one for your station.

---

## Quick start — zero API keys

If you just want to get running without signing up for any external services, select:

| Domain | Provider |
|---|---|
| Forecast | Open-Meteo |
| Alerts | NWS Alerts (US only) |
| Air quality | Open-Meteo AQI |
| Earthquakes | USGS |
| Radar | RainViewer |

All five are free and keyless. US stations get full alert coverage. Non-US stations will have no active weather alerts (there is currently no global alerts provider), but all other data works worldwide.

---

## About domains

Clear Skies splits weather data into five independent domains. You pick one provider per domain; you can mix and match freely (for example, NWS for forecast and IQAir for air quality).

| Domain | What it provides |
|---|---|
| **Forecast** | Hourly and daily forecasts — temperature, wind, precipitation probability, weather codes |
| **Alerts** | Active severe weather watches, warnings, and advisories |
| **AQI** | Air Quality Index (US EPA 0–500 scale) and pollutant concentrations |
| **Earthquakes** | Recent seismic events near your station |
| **Radar** | Animated precipitation radar tiles |

---

## About API keys

Some providers are free and keyless — you just select them and they work. Others require you to create an account and paste in a key. Keys are stored in your `.env` file on the server; they never appear in the dashboard UI.

---

## Forecast providers

### NWS — National Weather Service

| | |
|---|---|
| **Data source** | US National Weather Service (weather.gov) |
| **Coverage** | United States, territories, and adjacent ocean zones only |
| **API key required** | No |
| **Signup URL** | — |
| **Rate limits** | No published quota; polite-use expected. The wizard sets a User-Agent header that identifies your installation — NWS asks operators to include a contact email or URL so they can reach you if your traffic spikes. |

**What it provides:** Hourly forecasts, 7-day day/night forecasts, and the Area Forecast Discussion (AFD) — a plain-English narrative written by your local NWS office explaining the forecast rationale. The AFD is unique to NWS; no other provider offers anything equivalent.

**What it does not provide:** Relative humidity, wind gusts, precipitation amounts, cloud cover, and UV index are not available through the standard NWS forecast endpoints used by Clear Skies. Those fields require the raw gridpoint endpoint, which is out of scope for v0.1.

**Limitations:** US only. Outside the contiguous US (including non-US stations), NWS returns a geographic-coverage error and Clear Skies falls back gracefully.

**Best for:** US stations that want the highest-quality, government-sourced forecast plus the meteorologist narrative.

**Tip:** Set `nws_user_agent_contact` in `api.conf` to your email address or website URL. NWS will log a warning in your server output if this is missing, and omitting it increases the risk of being rate-limited during NWS security events.

---

### Open-Meteo

| | |
|---|---|
| **Data source** | Open-Meteo (open-meteo.com) — an open-source forecast API backed by multiple numerical weather prediction models |
| **Coverage** | Global |
| **API key required** | No (non-commercial use) |
| **Signup URL** | — |
| **Rate limits** | ~10,000 calls per day fair-use limit. With Clear Skies's 30-minute cache, a single station makes roughly 48 real calls per day — well within limits. |

**What it provides:** Hourly and 7-day daily forecasts including temperature, humidity, wind speed and gusts, precipitation probability and amount, cloud cover, UV index, sunrise and sunset times, and weather codes.

**What it does not provide:** A forecast narrative or discussion text.

**Limitations:** The fair-use limit applies to non-commercial deployments. Commercial use requires a paid plan from Open-Meteo. No forecast discussion text is available.

**Best for:** Non-US stations that want a full-featured global forecast without any API key.

---

### OpenWeatherMap

| | |
|---|---|
| **Data source** | OpenWeatherMap One Call 3.0 (openweathermap.org) |
| **Coverage** | Global |
| **API key required** | Yes |
| **Signup URL** | https://home.openweathermap.org/api_keys |
| **Rate limits** | The One Call 3.0 endpoint (`/data/3.0/onecall`) requires the "One Call by Call" subscription — it is not available on a basic free API key. A basic key returns an empty forecast. The paid tier bills per call; check the OWM pricing page for current rates. |

**What it provides:** Hourly (48 hours) and 8-day daily forecasts including temperature, humidity, wind, gusts, precipitation, cloud cover, UV index, sunrise and sunset. No forecast discussion text.

**What it does not provide:** Forecast narrative or discussion text. Location names in AQI data.

**Limitations:** The `/data/3.0/onecall` endpoint is paid-only. A basic free OWM key will connect successfully but return empty forecast data — the wizard's connectivity test cannot distinguish a basic key from a paid key. If you see blank forecasts after setup, upgrade to the "One Call by Call" subscription in your OWM dashboard.

**Shared key with OWM AQI:** If you also select OpenWeatherMap for air quality, both use the same API key (`WEEWX_CLEARSKIES_OPENWEATHERMAP_APPID` in your `.env`). You only enter it once.

**Best for:** Operators who already have an OWM One Call 3.0 subscription and want global coverage with a single API key that also covers AQI.

---

### Aeris Weather

| | |
|---|---|
| **Data source** | Aeris (AerisWeather / Xweather) — aerisweather.com |
| **Coverage** | Global |
| **API key required** | Yes (client ID + client secret pair) |
| **Signup URL** | https://www.aerisweather.com/signup/ |
| **Rate limits** | Varies by plan. Free developer accounts exist for testing. Check the Aeris pricing page for current plan limits. |

**What it provides:** Hourly (up to 240 hours) and 14-day day/night daily forecasts including temperature, humidity, wind, gusts, precipitation probability and amount, cloud cover, UV index, sunrise and sunset, and weather codes. On paid plans with the `summary` field, a forecast discussion is also available.

**What it does not provide:** Forecast discussion on free/entry-level plans (the `summary` field is not present; Clear Skies automatically omits it rather than showing an error).

**Limitations:** Requires registering an Aeris application and generating a client ID + client secret. The credentials are bound to a registered domain or bundle ID in the Aeris dashboard.

**Shared key across domains:** The Aeris client ID and client secret (`WEEWX_CLEARSKIES_AERIS_CLIENT_ID` and `WEEWX_CLEARSKIES_AERIS_CLIENT_SECRET`) work across all Aeris-powered domains. If Aeris adds alerts or AQI support in a future release, the same credentials apply.

**Best for:** Operators who want the longest hourly forecast window (up to 10 days of hourly data) or who already have an Aeris subscription.

---

### Forecast comparison table

| Provider | Coverage | API key | Hourly window | Daily window | Forecast discussion | Humidity | Wind gusts | UV index |
|---|---|---|---|---|---|---|---|---|
| NWS | US only | None | ~156 hours | ~7 days | Yes (AFD) | No | No | No |
| Open-Meteo | Global | None | Provider default | 7 days | No | Yes | Yes | Yes |
| OpenWeatherMap | Global | Required (paid) | 48 hours | 8 days | No | Yes | Yes | Yes |
| Aeris | Global | Required | Up to 240 hours | 14 days | Paid tier only | Yes | Yes | Yes |

---

## Alerts providers

### NWS Alerts

| | |
|---|---|
| **Data source** | US National Weather Service alerts (api.weather.gov/alerts) |
| **Coverage** | United States, territories, and adjacent marine zones only |
| **API key required** | No |
| **Signup URL** | — |
| **Rate limits** | No published quota. Cache TTL is 5 minutes. A single station makes about 288 calls per day — well within polite-use expectations. |

**What it provides:** Active watches, warnings, advisories, and statements for your station's location. Each alert includes a headline, full description text, severity level, effective and expiry times, affected area description, and the issuing NWS office.

**Limitations:** US only. Non-US stations will always see an empty alerts list because the NWS service returns empty results for coordinates outside its coverage area — this is not an error.

**Only current provider:** NWS Alerts is the only alerts provider in v0.1. Global alerts support is planned for a future release.

**Best for:** All US stations.

---

### Alerts comparison table

| Provider | Coverage | API key | Alert types |
|---|---|---|---|
| NWS Alerts | US only | None | Watches, warnings, advisories, statements |

---

## Air quality providers

Air quality values are reported on the US EPA AQI scale (0–500) regardless of which provider you use. Clear Skies normalizes all providers to this standard scale.

### Open-Meteo AQI

| | |
|---|---|
| **Data source** | Open-Meteo Air Quality API (air-quality-api.open-meteo.com) |
| **Coverage** | Global |
| **API key required** | No |
| **Signup URL** | — |
| **Rate limits** | Same fair-use policy as the forecast API (~10,000 calls/day). With a 15-minute cache TTL, a single station makes roughly 96 calls per day. |

**What it provides:** US EPA AQI (computed from six pollutant sub-AQIs), AQI category (Good / Moderate / etc.), main contributing pollutant, and individual concentrations for PM2.5, PM10, ozone, nitrogen dioxide, sulfur dioxide, and carbon monoxide.

**What it does not provide:** A location label for the measurement station — Clear Skies will show AQI data without a location name.

**Best for:** Non-US stations or any station that wants global air quality without an API key.

---

### IQAir

| | |
|---|---|
| **Data source** | IQAir AirVisual API (airvisual.com) |
| **Coverage** | Global |
| **API key required** | Yes |
| **Signup URL** | https://www.iqair.com/dashboard/api |
| **Rate limits** | Community (free) plan: 5 calls per minute, 500 calls per day, 10,000 calls per month. With a 15-minute cache TTL, a single station makes roughly 96 calls per day — comfortably within the daily and monthly caps. |

**What it provides:** US EPA AQI (directly from the IQAir wire — no breakpoint computation needed), AQI category, main contributing pollutant, and a location label showing the nearest monitoring station name and state.

**What it does not provide (free tier):** Individual pollutant concentrations (PM2.5, PM10, O3, NO2, SO2, CO). These are only available on paid Startup+ plans; the wire format for paid tiers has not been verified in v0.1.

**Limitations:** The 5-calls-per-minute rate limit is the strictest of any provider in this list. Clear Skies respects it automatically — do not configure a cache TTL shorter than 15 minutes when using IQAir.

**Best for:** Operators who want a location name displayed next to their AQI reading, or who prefer IQAir's crowd-sourced station network.

---

### OpenWeatherMap AQI

| | |
|---|---|
| **Data source** | OpenWeatherMap Air Pollution API (/data/2.5/air_pollution) |
| **Coverage** | Global |
| **API key required** | Yes (same key as OWM forecast) |
| **Signup URL** | https://home.openweathermap.org/api_keys |
| **Rate limits** | The Air Pollution endpoint is on the OWM free tier — a basic API key works here, unlike the forecast endpoint which requires a paid subscription. OWM free tier allows 60 calls per minute (check the OWM pricing page for daily/monthly limits). With a 15-minute cache TTL, a single station makes roughly 96 calls per day. |

**What it provides:** US EPA AQI (computed client-side from pollutant concentrations via EPA breakpoints — OWM's own 1–5 ordinal scale is ignored), AQI category, main contributing pollutant, and individual concentrations for PM2.5, PM10, ozone, nitrogen dioxide, sulfur dioxide, and carbon monoxide.

**What it does not provide:** A location label for the measurement station.

**Shared key with OWM forecast:** If you also use OpenWeatherMap for forecast, both the forecast and AQI modules use the same `WEEWX_CLEARSKIES_OPENWEATHERMAP_APPID` key. You only enter it once.

**Note on AQI calculation:** OWM's native 1–5 AQI ordinal is not used. Clear Skies computes its own EPA 0–500 value from the raw pollutant concentrations using the official EPA piecewise-linear breakpoints. This gives you a value that is directly comparable to the other AQI providers (all of which also output EPA 0–500).

**Best for:** Operators who already have an OWM API key from the forecast domain and want full pollutant concentration data without signing up for a second service.

---

### AQI comparison table

| Provider | Coverage | API key | AQI scale | Location name | Pollutant concentrations | Free-tier notes |
|---|---|---|---|---|---|---|
| Open-Meteo AQI | Global | None | EPA 0–500 | No | Yes | ~10,000 calls/day |
| IQAir | Global | Required | EPA 0–500 | Yes | No (free tier) | 5/min, 500/day, 10k/month |
| OpenWeatherMap AQI | Global | Required | EPA 0–500 | No | Yes | Free endpoint; basic key works |

---

## Earthquakes providers

### USGS

| | |
|---|---|
| **Data source** | US Geological Survey FDSN-Event API (earthquake.usgs.gov) |
| **Coverage** | Global (M2.5 and larger events worldwide) |
| **API key required** | No |
| **Signup URL** | — |
| **Rate limits** | No published per-key quota. The USGS feed updates approximately every minute; Clear Skies uses a 60-second cache TTL to match. |

**What it provides:** Recent earthquakes near your station including magnitude, magnitude type, depth, location description, time, tsunami flag, USGS "felt" report count, ShakeMap intensity (MMI), USGS alert level, and a link to the USGS event page.

**Only current provider:** USGS is the only earthquake provider in v0.1. It covers global events, so no regional alternative is needed.

**Best for:** All stations.

---

### Earthquakes comparison table

| Provider | Coverage | API key | Minimum magnitude |
|---|---|---|---|
| USGS | Global | None | M2.5 (configurable) |

---

## Radar providers

### RainViewer

| | |
|---|---|
| **Data source** | RainViewer (rainviewer.com) — a global precipitation radar composite |
| **Coverage** | Global mosaic |
| **API key required** | No |
| **Signup URL** | — |
| **Rate limits** | No documented per-key quota. Clear Skies fetches the frame index once per minute. |

**What it provides:** An animated precipitation radar overlay for the dashboard map. RainViewer assembles data from weather radar networks around the world into a single global mosaic. The API returns a list of past frames plus short-term nowcast frames, which the dashboard plays as animation.

**Attribution required:** RainViewer's terms require a visible link back to https://www.rainviewer.com/ on any page that displays their tiles. The Clear Skies dashboard includes this automatically.

**Limitations:** RainViewer is a mosaic product — coverage quality varies by region. Areas with sparse radar networks (parts of Africa, remote Pacific) may show gaps or lower resolution.

**Only current provider:** RainViewer is the only radar provider in v0.1. It covers all regions globally, so no alternative is needed for most deployments.

**Best for:** All stations.

---

### Radar comparison table

| Provider | Coverage | API key | Attribution required |
|---|---|---|---|
| RainViewer | Global | None | Yes — link to rainviewer.com |

---

## Provider summary — all domains

| Provider | Domain | Coverage | API key | Free tier |
|---|---|---|---|---|
| NWS | Forecast | US only | None | Yes |
| Open-Meteo | Forecast | Global | None | Yes (~10k calls/day) |
| OpenWeatherMap | Forecast | Global | Required | No (paid One Call 3.0 only) |
| Aeris | Forecast | Global | Required | Limited developer tier |
| NWS Alerts | Alerts | US only | None | Yes |
| Open-Meteo AQI | AQI | Global | None | Yes (~10k calls/day) |
| IQAir | AQI | Global | Required | Yes (5/min, 500/day, 10k/month) |
| OpenWeatherMap AQI | AQI | Global | Required | Yes (basic key works) |
| USGS | Earthquakes | Global | None | Yes |
| RainViewer | Radar | Global | None | Yes |
