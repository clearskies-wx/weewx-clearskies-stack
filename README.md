# weewx-clearskies-stack

Phase 1 placeholder — real content lands during Phase 4 of the Clear Skies project.

Meta repo for the Clear Skies weather stack: docker-compose for the easy-button install, deployment guide, architecture diagrams, example Home Assistant configs.

Sibling repos:
- [weewx-clearskies-api](https://github.com/inguy24/weewx-clearskies-api) — HTTP/JSON API + per-provider plugin modules
- [weewx-clearskies-realtime](https://github.com/inguy24/weewx-clearskies-realtime) — SSE bridge from weewx loop packets
- [weewx-clearskies-dashboard](https://github.com/inguy24/weewx-clearskies-dashboard) — React SPA

The `dev/` subdirectory contains the Phase 1 docker-compose dev/test stack (MariaDB + backend-agnostic Python seed loader).

Distributed AS-IS under [GPL v3](LICENSE).
