# Release Procedure

Step-by-step process for publishing a Clear Skies release. Each step includes a verification checkpoint — do not proceed until the checkpoint passes.

---

## Pre-release checks

- [ ] All repos clean (`git status` shows no uncommitted changes)
- [ ] CI green on all repos (DCO, gitleaks, dep-audit passing on latest commit)
- [ ] CHANGELOG.md updated in each repo with the release version and date
- [ ] Version strings consistent across all components (see Phase 4 of BETA-RELEASE-PLAN.md)

---

## Publishing order

The Config UI package depends on the API package on PyPI. The API must publish first.

### 1. Tag and release API

```bash
cd repos/weewx-clearskies-api
git tag v1.0.0b1
git push origin v1.0.0b1
```

This triggers the API release workflow: pytest → PyPI publish → GHCR push → GitHub Release.

**Checkpoint:** Wait for the workflow to complete, then verify:
```bash
pip install --pre weewx-clearskies-api==1.0.0b1
python -c "import weewx_clearskies_api; print(weewx_clearskies_api.__version__)"
# Should print: 1.0.0b1
```

### 2. Tag and release Stack (Config UI)

```bash
cd repos/weewx-clearskies-stack
git tag v1.0.0b1
git push origin v1.0.0b1
```

This triggers the Stack release workflow: PyPI publish (`weewx-clearskies-config`) → GHCR push → GitHub Release.

**Checkpoint:**
```bash
pip install --pre weewx-clearskies-config==1.0.0b1
weewx-clearskies-config --version
# Should print: 1.0.0b1
```

### 3. Tag and release Dashboard

```bash
cd repos/weewx-clearskies-dashboard
git tag v1.0.0b1
git push origin v1.0.0b1
```

This triggers the Dashboard release workflow: GHCR push → GitHub Release.

**Checkpoint:**
```bash
docker pull ghcr.io/clearskies-wx/weewx-clearskies-dashboard:1.0.0b1
```

### 4. Tag and release extensions

Extensions use their own version numbers (not the beta version).

```bash
# Loop Relay
cd repos/weewx-clearskies-extension
git tag v1.1.0
git push origin v1.1.0

# TrueSun
cd repos/weewx-clearskies-truesun
git tag v0.1.0
git push origin v0.1.0
```

**Checkpoint:** Both GitHub Releases created with `.tar.gz` attachments.

### 5. Final verification

```bash
# Docker compose pull (from single-host directory)
cd repos/weewx-clearskies-stack/single-host
docker compose pull

# pip install both packages
pip install --pre weewx-clearskies-api weewx-clearskies-config
```

---

## Version scheme

| Component | Version format | Example |
|-----------|---------------|---------|
| API, Config UI (Python) | PEP 440 | `1.0.0b1`, `1.0.0b2`, `1.0.0` |
| Dashboard (npm) | semver | `1.0.0-beta.1`, `1.0.0` |
| Docker images | matches Python | `1.0.0b1` + floating `beta` tag |
| Loop Relay extension | independent semver | `1.1.0` |
| TrueSun extension | independent semver | `0.1.0` |

## Notes

- `pip install weewx-clearskies-api` (without `--pre`) will NOT install betas. Operators must use `pip install --pre` or pin the exact version.
- The floating `beta` Docker tag always points to the latest beta image.
- Cross-repo dependency: Config UI declares `weewx-clearskies-api>=1.0.0b1` — the API must be on PyPI before the Config UI can publish.
