# Image security remediation

Review date: 2026-09-28. These are local results, not a GitHub Actions run.

## Targeted backend change

The backend Dockerfile retains Python 3.13.13, Bookworm, uv 0.11.7,
locked application dependencies and runtime UID/GID 10001. A shared base stage
runs `apt-get update` followed by `apt-get install --only-upgrade` for exactly:

| Package | Original | Installed security update |
|---|---|---|
| libgnutls30 | 3.7.9-2+deb12u6 | 3.7.9-2+deb12u7 |
| libpcre2-8-0 | 10.42-1 | 10.42-1+deb12u1 |
| libssl3 | 3.0.20-1~deb12u1 | 3.0.22-1~deb12u1 |
| openssl | 3.0.20-1~deb12u1 | 3.0.22-1~deb12u1 |

APT confirmed four upgrades, no additions and no removals. Package lists are
removed afterward. Both builder and runtime inherit the patched OS libraries;
uv remains builder-only. No application dependency or lockfile changed. The
interrupted pip upgrade was removed to keep this change limited to the targeted
OS remediation. Existing pip findings remain visible in the inventory below.

The packages originated in the Python image's Debian OS layer, digest
`sha256:068fedd6b0f109b8186d00d49327b6fc6747c428fd3c9a8739424ff5f38d7531`.
Debian confirms fixes for [GnuTLS CVE-2026-33845](https://security-tracker.debian.org/tracker/CVE-2026-33845),
[PCRE2 CVE-2026-86145](https://security-tracker.debian.org/tracker/CVE-2026-86145),
and [OpenSSL CVE-2026-45447](https://security-tracker.debian.org/tracker/CVE-2026-45447).
The installed OpenSSL update also addresses newer findings from the refreshed DB.
Exact package pins depend on Debian retaining those versions; builds fail rather
than silently substitute a different version. Future security updates need a new
review and scan; this is not a perpetual guarantee of a clean image.

## Preserved frontend remediation

The runtime remains the already-remediated
`nginx:1.30.5-alpine3.24-slim@sha256:32463212baf0e7d91aded2e9b843a4f2b9e017804b8c9d5bae7b51dcef64389c`.
No frontend Dockerfile changes were made during this resumed task.

The original HIGH `CVE-2026-93990` affected OS package `libexpat 2.8.4-r0`
(reported fix `2.8.5-r0`). It came from the Nginx runtime's optional
`nginx-module-image-filter -> libgd -> fontconfig -> libexpat` chain, not an npm
dependency or the Node build stage. The original layer digest was
`sha256:b27cf3f7c39dd0da0aa52a285f0c0cce938ac61472babfea353b1daa83586c49`.
The slim image omits that unused chain while retaining Nginx 1.30.5 and envsubst.

## Validation and interpretation

Both production images were rebuilt as `rook-backend:local` and
`rook-frontend:local`. Trivy 0.69.3 scanned all severities with its refreshed
2026-09-28 database. No ignore file, severity downgrade, `--ignore-unfixed`, or
package-metadata removal was used. The existing CI scan policy is unchanged.
Full local JSON artifacts are in ignored `tmp/security-review/final-*.json`;
the inventory below preserves every remaining finding for review.

Backend tests: 120 passed, one opt-in PostgreSQL test skipped, two dependency
deprecation warnings (Starlette/httpx and AnyIO). Frontend: 21 tests passed,
TypeScript and production build passed. Helm 4.2.3 default/canary lint and
rendering passed with eight chart tests; all five operator-switch/rollback tests
passed using test doubles, not a Kubernetes rollout. Four scanner-helper tests
passed. Actionlint 1.7.7 passed; optional ShellCheck/Pyflakes were unavailable.
YAML, TOML, OpenAPI, Python syntax and changed/untracked-file whitespace checks
passed. YAML validation used the cached isolated CI tooling environment because
PyYAML is deliberately not an application dependency.

Temporary containers returned HTTP 200 for backend `/health/live` and frontend
`/healthz`; both ran with UID/GID 10001. Only those verification containers were
removed. No existing Rook or Demo containers were restarted, and no image was
pushed. Liveness does not prove database readiness or incident behavior.

Remaining findings are unresolved, not accepted risk or false-positive dismissals.
An empty fixed-version field means this scanner reports no fix for the installed
distribution; it does not prove no upstream patch or newer-distribution fix exists.
Changing Debian releases is outside this targeted package update. Fixable
unrelated packages and pip remain follow-up work, explicitly identified below.
The scanner also warns that Alpine 3.24 is absent from its EOL metadata; a zero
finding scan is limited to this scanner/database's coverage.

## Remaining finding inventory

Generated directly from the final scan; one row per image/package/advisory.

Database updated: `2026-09-28T13:05:44.359328237Z`.

| Image | CRITICAL | HIGH | MEDIUM | LOW | UNKNOWN |
|---|---:|---:|---:|---:|---:|
| rook-backend:local | 5 | 55 | 106 | 78 | 5 |
| rook-frontend:local | 0 | 0 | 0 | 0 | 0 |

Frontend has no remaining findings. Backend rows below retain scanner severity
and status unchanged. Upstream evidence is from the [Debian tracker JSON](https://security-tracker.debian.org/tracker/data/json)
and scanner fixed-version fields. A fix in a different Debian release is not
a supported Bookworm package update. Unknown upstream status is explicitly
unverified, rather than a claim that no fix exists.

| Image | Package/version | Severity | Advisory | Available fix evidence | Why unresolved / scanner status |
|---|---|---|---|---|---|
| rook-backend:local | apt 2.6.1 | LOW | [CVE-2011-3374](https://avd.aquasec.com/nvd/cve-2011-3374) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | bash 5.2.15-2+b13 | LOW | [TEMP-0841856-B18BAF](https://security-tracker.debian.org/tracker/TEMP-0841856-B18BAF) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | bsdutils 1:2.38.1-5+deb12u3 | HIGH | [CVE-2026-53613](https://avd.aquasec.com/nvd/cve-2026-53613) | No Bookworm fix reported; forky: 2.42.2-1; sid: 2.42.2-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | bsdutils 1:2.38.1-5+deb12u3 | HIGH | [CVE-2026-76642](https://avd.aquasec.com/nvd/cve-2026-76642) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | bsdutils 1:2.38.1-5+deb12u3 | HIGH | [CVE-2026-78408](https://avd.aquasec.com/nvd/cve-2026-78408) | No Bookworm fix reported; sid: 2.42.4-1 | No installed-distribution fix reported; affected |
| rook-backend:local | bsdutils 1:2.38.1-5+deb12u3 | HIGH | [CVE-2026-78409](https://avd.aquasec.com/nvd/cve-2026-78409) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | bsdutils 1:2.38.1-5+deb12u3 | HIGH | [CVE-2026-78410](https://avd.aquasec.com/nvd/cve-2026-78410) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | bsdutils 1:2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-13595](https://avd.aquasec.com/nvd/cve-2026-13595) | No Bookworm fix reported; forky: 2.42.2-1; sid: 2.42.2-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | bsdutils 1:2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-27456](https://avd.aquasec.com/nvd/cve-2026-27456) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | bsdutils 1:2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-3184](https://avd.aquasec.com/nvd/cve-2026-3184) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1 | No installed-distribution fix reported; will_not_fix |
| rook-backend:local | bsdutils 1:2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-53615](https://avd.aquasec.com/nvd/cve-2026-53615) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | bsdutils 1:2.38.1-5+deb12u3 | LOW | [CVE-2022-0563](https://avd.aquasec.com/nvd/cve-2022-0563) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | bsdutils 1:2.38.1-5+deb12u3 | LOW | [CVE-2025-14104](https://avd.aquasec.com/nvd/cve-2025-14104) | No Bookworm fix reported; forky: 2.41.3-1; sid: 2.41.3-1; trixie: 2.41.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | ca-certificates 20230311+deb12u1 | UNKNOWN | [DLA-4726-1](https://security-tracker.debian.org/tracker/DLA-4726-1) | Yes: 20250419~deb12u1 | Outside the four-package OS remediation; follow-up update required |
| rook-backend:local | coreutils 9.1-1 | LOW | [CVE-2016-2781](https://avd.aquasec.com/nvd/cve-2016-2781) | No Bookworm fix reported; forky: 9.4-1; sid: 9.4-1; trixie: 9.4-1 | No installed-distribution fix reported; will_not_fix |
| rook-backend:local | coreutils 9.1-1 | LOW | [CVE-2017-18018](https://avd.aquasec.com/nvd/cve-2017-18018) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | coreutils 9.1-1 | LOW | [CVE-2025-5278](https://avd.aquasec.com/nvd/cve-2025-5278) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | coreutils 9.1-1 | LOW | [CVE-2026-56391](https://avd.aquasec.com/nvd/cve-2026-56391) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | coreutils 9.1-1 | LOW | [CVE-2026-56392](https://avd.aquasec.com/nvd/cve-2026-56392) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | diffutils 1:3.8-4 | LOW | [CVE-2026-53910](https://avd.aquasec.com/nvd/cve-2026-53910) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | gcc-12-base 12.2.0-14+deb12u1 | LOW | [CVE-2022-27943](https://avd.aquasec.com/nvd/cve-2022-27943) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | gpgv 2.2.40-1.1+deb12u2 | MEDIUM | [CVE-2025-30258](https://avd.aquasec.com/nvd/cve-2025-30258) | No Bookworm fix reported; forky: 2.2.46-5; sid: 2.2.46-5; trixie: 2.2.46-5 | No installed-distribution fix reported; affected |
| rook-backend:local | gpgv 2.2.40-1.1+deb12u2 | MEDIUM | [CVE-2025-68972](https://avd.aquasec.com/nvd/cve-2025-68972) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | gpgv 2.2.40-1.1+deb12u2 | LOW | [CVE-2022-3219](https://avd.aquasec.com/nvd/cve-2022-3219) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | gpgv 2.2.40-1.1+deb12u2 | LOW | [CVE-2026-57062](https://avd.aquasec.com/nvd/cve-2026-57062) | No Bookworm fix reported; forky: 2.4.9-5; sid: 2.4.9-5 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | gzip 1.12-1 | HIGH | [CVE-2026-41992](https://avd.aquasec.com/nvd/cve-2026-41992) | No Bookworm fix reported; forky: 1.14-1; sid: 1.14-1; trixie: 1.13-1+deb13u1 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | gzip 1.12-1 | MEDIUM | [CVE-2026-41991](https://avd.aquasec.com/nvd/cve-2026-41991) | No Bookworm fix reported; forky: 1.14-1; sid: 1.14-1; trixie: 1.13-1+deb13u1 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libacl1 2.3.1-3 | HIGH | [CVE-2026-54369](https://avd.aquasec.com/nvd/cve-2026-54369) | No Bookworm fix reported; forky: 2.4.0-1; sid: 2.4.0-1 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libacl1 2.3.1-3 | MEDIUM | [CVE-2026-54370](https://avd.aquasec.com/nvd/cve-2026-54370) | No Bookworm fix reported; forky: 2.4.0-1; sid: 2.4.0-1 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libapt-pkg6.0 2.6.1 | LOW | [CVE-2011-3374](https://avd.aquasec.com/nvd/cve-2011-3374) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libattr1 1:2.5.1-4 | MEDIUM | [CVE-2026-54371](https://avd.aquasec.com/nvd/cve-2026-54371) | No Bookworm fix reported; forky: 1:2.6.0-1; sid: 1:2.6.0-1 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libblkid1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-53613](https://avd.aquasec.com/nvd/cve-2026-53613) | No Bookworm fix reported; forky: 2.42.2-1; sid: 2.42.2-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | libblkid1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-76642](https://avd.aquasec.com/nvd/cve-2026-76642) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libblkid1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78408](https://avd.aquasec.com/nvd/cve-2026-78408) | No Bookworm fix reported; sid: 2.42.4-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libblkid1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78409](https://avd.aquasec.com/nvd/cve-2026-78409) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libblkid1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78410](https://avd.aquasec.com/nvd/cve-2026-78410) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libblkid1 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-13595](https://avd.aquasec.com/nvd/cve-2026-13595) | No Bookworm fix reported; forky: 2.42.2-1; sid: 2.42.2-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | libblkid1 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-27456](https://avd.aquasec.com/nvd/cve-2026-27456) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | libblkid1 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-3184](https://avd.aquasec.com/nvd/cve-2026-3184) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1 | No installed-distribution fix reported; will_not_fix |
| rook-backend:local | libblkid1 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-53615](https://avd.aquasec.com/nvd/cve-2026-53615) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | libblkid1 2.38.1-5+deb12u3 | LOW | [CVE-2022-0563](https://avd.aquasec.com/nvd/cve-2022-0563) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libblkid1 2.38.1-5+deb12u3 | LOW | [CVE-2025-14104](https://avd.aquasec.com/nvd/cve-2025-14104) | No Bookworm fix reported; forky: 2.41.3-1; sid: 2.41.3-1; trixie: 2.41.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libbz2-1.0 1.0.8-5+b1 | MEDIUM | [CVE-2026-42250](https://avd.aquasec.com/nvd/cve-2026-42250) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | MEDIUM | [CVE-2026-18374](https://avd.aquasec.com/nvd/cve-2026-18374) | No Bookworm fix reported; forky: 2.43-5; sid: 2.43-5 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | MEDIUM | [CVE-2026-19499](https://avd.aquasec.com/nvd/cve-2026-19499) | No Bookworm fix reported; forky: 2.43-5; sid: 2.43-5 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | MEDIUM | [CVE-2026-19542](https://avd.aquasec.com/nvd/cve-2026-19542) | No Bookworm fix reported; forky: 2.43-4; sid: 2.43-4 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | MEDIUM | [CVE-2026-5435](https://avd.aquasec.com/nvd/cve-2026-5435) | No Bookworm fix reported; forky: 2.43-3; sid: 2.43-3 | No installed-distribution fix reported; affected |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | MEDIUM | [CVE-2026-5450](https://avd.aquasec.com/nvd/cve-2026-5450) | No Bookworm fix reported; forky: 2.42-17; sid: 2.42-17; trixie: 2.41-12+deb13u4 | No installed-distribution fix reported; affected |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | MEDIUM | [CVE-2026-5928](https://avd.aquasec.com/nvd/cve-2026-5928) | No Bookworm fix reported; forky: 2.42-17; sid: 2.42-17; trixie: 2.41-12+deb13u4 | No installed-distribution fix reported; affected |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | MEDIUM | [CVE-2026-6238](https://avd.aquasec.com/nvd/cve-2026-6238) | No Bookworm fix reported; forky: 2.43-3; sid: 2.43-3 | No installed-distribution fix reported; affected |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | MEDIUM | [CVE-2026-6368](https://avd.aquasec.com/nvd/cve-2026-6368) | No Bookworm fix reported; forky: 2.43-4; sid: 2.43-4 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | MEDIUM | [CVE-2026-6791](https://avd.aquasec.com/nvd/cve-2026-6791) | No Bookworm fix reported; forky: 2.43-3; sid: 2.43-3 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | MEDIUM | [CVE-2026-77117](https://avd.aquasec.com/nvd/cve-2026-77117) | No Bookworm fix reported; forky: 2.43-5; sid: 2.43-5 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | MEDIUM | [CVE-2026-80489](https://avd.aquasec.com/nvd/cve-2026-80489) | No Bookworm fix reported; forky: 2.43-5; sid: 2.43-5 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | MEDIUM | [CVE-2026-8674](https://avd.aquasec.com/nvd/cve-2026-8674) | No Bookworm fix reported; forky: 2.43-6; sid: 2.43-6 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | MEDIUM | [CVE-2026-86805](https://avd.aquasec.com/nvd/cve-2026-86805) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | MEDIUM | [CVE-2026-89092](https://avd.aquasec.com/nvd/cve-2026-89092) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | MEDIUM | [CVE-2026-95818](https://avd.aquasec.com/nvd/cve-2026-95818) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | LOW | [CVE-2010-4756](https://avd.aquasec.com/nvd/cve-2010-4756) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | LOW | [CVE-2018-20796](https://avd.aquasec.com/nvd/cve-2018-20796) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | LOW | [CVE-2019-1010022](https://avd.aquasec.com/nvd/cve-2019-1010022) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | LOW | [CVE-2019-1010023](https://avd.aquasec.com/nvd/cve-2019-1010023) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | LOW | [CVE-2019-1010024](https://avd.aquasec.com/nvd/cve-2019-1010024) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | LOW | [CVE-2019-1010025](https://avd.aquasec.com/nvd/cve-2019-1010025) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libc-bin 2.36-9+deb12u14 | LOW | [CVE-2019-9192](https://avd.aquasec.com/nvd/cve-2019-9192) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libc6 2.36-9+deb12u14 | MEDIUM | [CVE-2026-18374](https://avd.aquasec.com/nvd/cve-2026-18374) | No Bookworm fix reported; forky: 2.43-5; sid: 2.43-5 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libc6 2.36-9+deb12u14 | MEDIUM | [CVE-2026-19499](https://avd.aquasec.com/nvd/cve-2026-19499) | No Bookworm fix reported; forky: 2.43-5; sid: 2.43-5 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libc6 2.36-9+deb12u14 | MEDIUM | [CVE-2026-19542](https://avd.aquasec.com/nvd/cve-2026-19542) | No Bookworm fix reported; forky: 2.43-4; sid: 2.43-4 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libc6 2.36-9+deb12u14 | MEDIUM | [CVE-2026-5435](https://avd.aquasec.com/nvd/cve-2026-5435) | No Bookworm fix reported; forky: 2.43-3; sid: 2.43-3 | No installed-distribution fix reported; affected |
| rook-backend:local | libc6 2.36-9+deb12u14 | MEDIUM | [CVE-2026-5450](https://avd.aquasec.com/nvd/cve-2026-5450) | No Bookworm fix reported; forky: 2.42-17; sid: 2.42-17; trixie: 2.41-12+deb13u4 | No installed-distribution fix reported; affected |
| rook-backend:local | libc6 2.36-9+deb12u14 | MEDIUM | [CVE-2026-5928](https://avd.aquasec.com/nvd/cve-2026-5928) | No Bookworm fix reported; forky: 2.42-17; sid: 2.42-17; trixie: 2.41-12+deb13u4 | No installed-distribution fix reported; affected |
| rook-backend:local | libc6 2.36-9+deb12u14 | MEDIUM | [CVE-2026-6238](https://avd.aquasec.com/nvd/cve-2026-6238) | No Bookworm fix reported; forky: 2.43-3; sid: 2.43-3 | No installed-distribution fix reported; affected |
| rook-backend:local | libc6 2.36-9+deb12u14 | MEDIUM | [CVE-2026-6368](https://avd.aquasec.com/nvd/cve-2026-6368) | No Bookworm fix reported; forky: 2.43-4; sid: 2.43-4 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libc6 2.36-9+deb12u14 | MEDIUM | [CVE-2026-6791](https://avd.aquasec.com/nvd/cve-2026-6791) | No Bookworm fix reported; forky: 2.43-3; sid: 2.43-3 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libc6 2.36-9+deb12u14 | MEDIUM | [CVE-2026-77117](https://avd.aquasec.com/nvd/cve-2026-77117) | No Bookworm fix reported; forky: 2.43-5; sid: 2.43-5 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libc6 2.36-9+deb12u14 | MEDIUM | [CVE-2026-80489](https://avd.aquasec.com/nvd/cve-2026-80489) | No Bookworm fix reported; forky: 2.43-5; sid: 2.43-5 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libc6 2.36-9+deb12u14 | MEDIUM | [CVE-2026-8674](https://avd.aquasec.com/nvd/cve-2026-8674) | No Bookworm fix reported; forky: 2.43-6; sid: 2.43-6 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libc6 2.36-9+deb12u14 | MEDIUM | [CVE-2026-86805](https://avd.aquasec.com/nvd/cve-2026-86805) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libc6 2.36-9+deb12u14 | MEDIUM | [CVE-2026-89092](https://avd.aquasec.com/nvd/cve-2026-89092) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libc6 2.36-9+deb12u14 | MEDIUM | [CVE-2026-95818](https://avd.aquasec.com/nvd/cve-2026-95818) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libc6 2.36-9+deb12u14 | LOW | [CVE-2010-4756](https://avd.aquasec.com/nvd/cve-2010-4756) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libc6 2.36-9+deb12u14 | LOW | [CVE-2018-20796](https://avd.aquasec.com/nvd/cve-2018-20796) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libc6 2.36-9+deb12u14 | LOW | [CVE-2019-1010022](https://avd.aquasec.com/nvd/cve-2019-1010022) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libc6 2.36-9+deb12u14 | LOW | [CVE-2019-1010023](https://avd.aquasec.com/nvd/cve-2019-1010023) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libc6 2.36-9+deb12u14 | LOW | [CVE-2019-1010024](https://avd.aquasec.com/nvd/cve-2019-1010024) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libc6 2.36-9+deb12u14 | LOW | [CVE-2019-1010025](https://avd.aquasec.com/nvd/cve-2019-1010025) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libc6 2.36-9+deb12u14 | LOW | [CVE-2019-9192](https://avd.aquasec.com/nvd/cve-2019-9192) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libgcc-s1 12.2.0-14+deb12u1 | LOW | [CVE-2022-27943](https://avd.aquasec.com/nvd/cve-2022-27943) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libgcrypt20 1.10.1-3 | MEDIUM | [CVE-2026-41989](https://avd.aquasec.com/nvd/cve-2026-41989) | Yes: 1.10.1-3+deb12u1 | Outside the four-package OS remediation; follow-up update required |
| rook-backend:local | libgcrypt20 1.10.1-3 | LOW | [CVE-2018-6829](https://avd.aquasec.com/nvd/cve-2018-6829) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libgcrypt20 1.10.1-3 | LOW | [CVE-2024-2236](https://avd.aquasec.com/nvd/cve-2024-2236) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libgnutls30 3.7.9-2+deb12u7 | LOW | [CVE-2011-3389](https://avd.aquasec.com/nvd/cve-2011-3389) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | liblzma5 5.4.1-1 | MEDIUM | [CVE-2026-34743](https://avd.aquasec.com/nvd/cve-2026-34743) | Yes: 5.4.1-1+deb12u1 | Outside the four-package OS remediation; follow-up update required |
| rook-backend:local | liblzma5 5.4.1-1 | UNKNOWN | [DLA-4783-1](https://security-tracker.debian.org/tracker/DLA-4783-1) | Yes: 5.4.1-1+deb12u2 | Outside the four-package OS remediation; follow-up update required |
| rook-backend:local | liblzma5 5.4.1-1 | UNKNOWN | [TEMP-1147318-639065](https://security-tracker.debian.org/tracker/TEMP-1147318-639065) | Yes: 5.4.1-1+deb12u2 | Outside the four-package OS remediation; follow-up update required |
| rook-backend:local | libmount1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-53613](https://avd.aquasec.com/nvd/cve-2026-53613) | No Bookworm fix reported; forky: 2.42.2-1; sid: 2.42.2-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | libmount1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-76642](https://avd.aquasec.com/nvd/cve-2026-76642) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libmount1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78408](https://avd.aquasec.com/nvd/cve-2026-78408) | No Bookworm fix reported; sid: 2.42.4-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libmount1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78409](https://avd.aquasec.com/nvd/cve-2026-78409) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libmount1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78410](https://avd.aquasec.com/nvd/cve-2026-78410) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libmount1 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-13595](https://avd.aquasec.com/nvd/cve-2026-13595) | No Bookworm fix reported; forky: 2.42.2-1; sid: 2.42.2-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | libmount1 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-27456](https://avd.aquasec.com/nvd/cve-2026-27456) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | libmount1 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-3184](https://avd.aquasec.com/nvd/cve-2026-3184) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1 | No installed-distribution fix reported; will_not_fix |
| rook-backend:local | libmount1 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-53615](https://avd.aquasec.com/nvd/cve-2026-53615) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | libmount1 2.38.1-5+deb12u3 | LOW | [CVE-2022-0563](https://avd.aquasec.com/nvd/cve-2022-0563) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libmount1 2.38.1-5+deb12u3 | LOW | [CVE-2025-14104](https://avd.aquasec.com/nvd/cve-2025-14104) | No Bookworm fix reported; forky: 2.41.3-1; sid: 2.41.3-1; trixie: 2.41.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libncursesw6 6.4-4 | HIGH | [CVE-2025-69720](https://avd.aquasec.com/nvd/cve-2025-69720) | No Bookworm fix reported; forky: 6.6+20251231-1; sid: 6.6+20251231-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libncursesw6 6.4-4 | MEDIUM | [CVE-2023-50495](https://avd.aquasec.com/nvd/cve-2023-50495) | No Bookworm fix reported; forky: 6.4+20230625-1; sid: 6.4+20230625-1; trixie: 6.4+20230625-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libncursesw6 6.4-4 | LOW | [CVE-2025-6141](https://avd.aquasec.com/nvd/cve-2025-6141) | No Bookworm fix reported; forky: 6.5+20251115-2; sid: 6.5+20251115-2 | No installed-distribution fix reported; affected |
| rook-backend:local | libp11-kit0 0.24.1-2 | MEDIUM | [CVE-2026-13757](https://avd.aquasec.com/nvd/cve-2026-13757) | No Bookworm fix reported; forky: 0.26.4-1; sid: 0.26.4-1 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libp11-kit0 0.24.1-2 | MEDIUM | [CVE-2026-18938](https://avd.aquasec.com/nvd/cve-2026-18938) | No Bookworm fix reported; forky: 0.26.5-1; sid: 0.26.5-1 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libpam-modules 1.5.2-6+deb12u2 | MEDIUM | [CVE-2024-10041](https://avd.aquasec.com/nvd/cve-2024-10041) | No Bookworm fix reported; forky: 1.7.0-2; sid: 1.7.0-2; trixie: 1.7.0-2 | No installed-distribution fix reported; will_not_fix |
| rook-backend:local | libpam-modules 1.5.2-6+deb12u2 | MEDIUM | [CVE-2026-54411](https://avd.aquasec.com/nvd/cve-2026-54411) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libpam-modules-bin 1.5.2-6+deb12u2 | MEDIUM | [CVE-2024-10041](https://avd.aquasec.com/nvd/cve-2024-10041) | No Bookworm fix reported; forky: 1.7.0-2; sid: 1.7.0-2; trixie: 1.7.0-2 | No installed-distribution fix reported; will_not_fix |
| rook-backend:local | libpam-modules-bin 1.5.2-6+deb12u2 | MEDIUM | [CVE-2026-54411](https://avd.aquasec.com/nvd/cve-2026-54411) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libpam-runtime 1.5.2-6+deb12u2 | MEDIUM | [CVE-2024-10041](https://avd.aquasec.com/nvd/cve-2024-10041) | No Bookworm fix reported; forky: 1.7.0-2; sid: 1.7.0-2; trixie: 1.7.0-2 | No installed-distribution fix reported; will_not_fix |
| rook-backend:local | libpam-runtime 1.5.2-6+deb12u2 | MEDIUM | [CVE-2026-54411](https://avd.aquasec.com/nvd/cve-2026-54411) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libpam0g 1.5.2-6+deb12u2 | MEDIUM | [CVE-2024-10041](https://avd.aquasec.com/nvd/cve-2024-10041) | No Bookworm fix reported; forky: 1.7.0-2; sid: 1.7.0-2; trixie: 1.7.0-2 | No installed-distribution fix reported; will_not_fix |
| rook-backend:local | libpam0g 1.5.2-6+deb12u2 | MEDIUM | [CVE-2026-54411](https://avd.aquasec.com/nvd/cve-2026-54411) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libsmartcols1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-53613](https://avd.aquasec.com/nvd/cve-2026-53613) | No Bookworm fix reported; forky: 2.42.2-1; sid: 2.42.2-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | libsmartcols1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-76642](https://avd.aquasec.com/nvd/cve-2026-76642) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libsmartcols1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78408](https://avd.aquasec.com/nvd/cve-2026-78408) | No Bookworm fix reported; sid: 2.42.4-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libsmartcols1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78409](https://avd.aquasec.com/nvd/cve-2026-78409) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libsmartcols1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78410](https://avd.aquasec.com/nvd/cve-2026-78410) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libsmartcols1 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-13595](https://avd.aquasec.com/nvd/cve-2026-13595) | No Bookworm fix reported; forky: 2.42.2-1; sid: 2.42.2-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | libsmartcols1 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-27456](https://avd.aquasec.com/nvd/cve-2026-27456) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | libsmartcols1 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-3184](https://avd.aquasec.com/nvd/cve-2026-3184) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1 | No installed-distribution fix reported; will_not_fix |
| rook-backend:local | libsmartcols1 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-53615](https://avd.aquasec.com/nvd/cve-2026-53615) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | libsmartcols1 2.38.1-5+deb12u3 | LOW | [CVE-2022-0563](https://avd.aquasec.com/nvd/cve-2022-0563) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libsmartcols1 2.38.1-5+deb12u3 | LOW | [CVE-2025-14104](https://avd.aquasec.com/nvd/cve-2025-14104) | No Bookworm fix reported; forky: 2.41.3-1; sid: 2.41.3-1; trixie: 2.41.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libsqlite3-0 3.40.1-2+deb12u2 | CRITICAL | [CVE-2025-7458](https://avd.aquasec.com/nvd/cve-2025-7458) | No Bookworm fix reported; forky: 3.42.0-1; sid: 3.42.0-1; trixie: 3.42.0-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libsqlite3-0 3.40.1-2+deb12u2 | HIGH | [CVE-2026-11822](https://avd.aquasec.com/nvd/cve-2026-11822) | No Bookworm fix reported; forky: 3.53.2-1; sid: 3.53.2-1; trixie: 3.46.1-7+deb13u2 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libsqlite3-0 3.40.1-2+deb12u2 | HIGH | [CVE-2026-11824](https://avd.aquasec.com/nvd/cve-2026-11824) | No Bookworm fix reported; forky: 3.53.2-1; sid: 3.53.2-1; trixie: 3.46.1-7+deb13u2 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libsqlite3-0 3.40.1-2+deb12u2 | MEDIUM | [CVE-2025-7709](https://avd.aquasec.com/nvd/cve-2025-7709) | No Bookworm fix reported; forky: 3.46.1-8; sid: 3.46.1-8; trixie: 3.46.1-7+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | libsqlite3-0 3.40.1-2+deb12u2 | MEDIUM | [CVE-2026-50812](https://avd.aquasec.com/nvd/cve-2026-50812) | No Bookworm fix reported; forky: 3.53.2-1; sid: 3.53.2-1 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libsqlite3-0 3.40.1-2+deb12u2 | MEDIUM | [CVE-2026-50813](https://avd.aquasec.com/nvd/cve-2026-50813) | No Bookworm fix reported; forky: 3.53.4-2; sid: 3.53.4-2 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libsqlite3-0 3.40.1-2+deb12u2 | LOW | [CVE-2021-45346](https://avd.aquasec.com/nvd/cve-2021-45346) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libsqlite3-0 3.40.1-2+deb12u2 | LOW | [CVE-2025-29088](https://avd.aquasec.com/nvd/cve-2025-29088) | No Bookworm fix reported; forky: 3.46.1-4; sid: 3.46.1-4; trixie: 3.46.1-4 | No installed-distribution fix reported; affected |
| rook-backend:local | libsqlite3-0 3.40.1-2+deb12u2 | LOW | [CVE-2025-70873](https://avd.aquasec.com/nvd/cve-2025-70873) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libssl3 3.0.22-1~deb12u1 | LOW | [CVE-2025-27587](https://avd.aquasec.com/nvd/cve-2025-27587) | No Bookworm fix reported; forky: 3.5.0-1; sid: 3.5.0-1; trixie: 3.5.0-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libstdc++6 12.2.0-14+deb12u1 | LOW | [CVE-2022-27943](https://avd.aquasec.com/nvd/cve-2022-27943) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libsystemd0 252.39-1~deb12u2 | HIGH | [CVE-2026-16742](https://avd.aquasec.com/nvd/cve-2026-16742) | No Bookworm fix reported; forky: 261.2-1; sid: 261.2-1 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libsystemd0 252.39-1~deb12u2 | MEDIUM | [CVE-2026-15059](https://avd.aquasec.com/nvd/cve-2026-15059) | No Bookworm fix reported; forky: 261~rc3-1; sid: 261~rc3-1 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libsystemd0 252.39-1~deb12u2 | LOW | [CVE-2013-4392](https://avd.aquasec.com/nvd/cve-2013-4392) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libsystemd0 252.39-1~deb12u2 | LOW | [CVE-2023-31437](https://avd.aquasec.com/nvd/cve-2023-31437) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libsystemd0 252.39-1~deb12u2 | LOW | [CVE-2023-31438](https://avd.aquasec.com/nvd/cve-2023-31438) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libsystemd0 252.39-1~deb12u2 | LOW | [CVE-2023-31439](https://avd.aquasec.com/nvd/cve-2023-31439) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libsystemd0 252.39-1~deb12u2 | LOW | [CVE-2026-40228](https://avd.aquasec.com/nvd/cve-2026-40228) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libtasn1-6 4.19.0-2+deb12u1 | LOW | [CVE-2025-13151](https://avd.aquasec.com/nvd/cve-2025-13151) | No Bookworm fix reported; forky: 4.21.0-2; sid: 4.21.0-2; trixie: 4.20.0-2+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | libtinfo6 6.4-4 | HIGH | [CVE-2025-69720](https://avd.aquasec.com/nvd/cve-2025-69720) | No Bookworm fix reported; forky: 6.6+20251231-1; sid: 6.6+20251231-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libtinfo6 6.4-4 | MEDIUM | [CVE-2023-50495](https://avd.aquasec.com/nvd/cve-2023-50495) | No Bookworm fix reported; forky: 6.4+20230625-1; sid: 6.4+20230625-1; trixie: 6.4+20230625-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libtinfo6 6.4-4 | LOW | [CVE-2025-6141](https://avd.aquasec.com/nvd/cve-2025-6141) | No Bookworm fix reported; forky: 6.5+20251115-2; sid: 6.5+20251115-2 | No installed-distribution fix reported; affected |
| rook-backend:local | libudev1 252.39-1~deb12u2 | HIGH | [CVE-2026-16742](https://avd.aquasec.com/nvd/cve-2026-16742) | No Bookworm fix reported; forky: 261.2-1; sid: 261.2-1 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libudev1 252.39-1~deb12u2 | MEDIUM | [CVE-2026-15059](https://avd.aquasec.com/nvd/cve-2026-15059) | No Bookworm fix reported; forky: 261~rc3-1; sid: 261~rc3-1 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | libudev1 252.39-1~deb12u2 | LOW | [CVE-2013-4392](https://avd.aquasec.com/nvd/cve-2013-4392) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libudev1 252.39-1~deb12u2 | LOW | [CVE-2023-31437](https://avd.aquasec.com/nvd/cve-2023-31437) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libudev1 252.39-1~deb12u2 | LOW | [CVE-2023-31438](https://avd.aquasec.com/nvd/cve-2023-31438) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libudev1 252.39-1~deb12u2 | LOW | [CVE-2023-31439](https://avd.aquasec.com/nvd/cve-2023-31439) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libudev1 252.39-1~deb12u2 | LOW | [CVE-2026-40228](https://avd.aquasec.com/nvd/cve-2026-40228) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libuuid1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-53613](https://avd.aquasec.com/nvd/cve-2026-53613) | No Bookworm fix reported; forky: 2.42.2-1; sid: 2.42.2-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | libuuid1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-76642](https://avd.aquasec.com/nvd/cve-2026-76642) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libuuid1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78408](https://avd.aquasec.com/nvd/cve-2026-78408) | No Bookworm fix reported; sid: 2.42.4-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libuuid1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78409](https://avd.aquasec.com/nvd/cve-2026-78409) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libuuid1 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78410](https://avd.aquasec.com/nvd/cve-2026-78410) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | libuuid1 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-13595](https://avd.aquasec.com/nvd/cve-2026-13595) | No Bookworm fix reported; forky: 2.42.2-1; sid: 2.42.2-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | libuuid1 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-27456](https://avd.aquasec.com/nvd/cve-2026-27456) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | libuuid1 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-3184](https://avd.aquasec.com/nvd/cve-2026-3184) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1 | No installed-distribution fix reported; will_not_fix |
| rook-backend:local | libuuid1 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-53615](https://avd.aquasec.com/nvd/cve-2026-53615) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | libuuid1 2.38.1-5+deb12u3 | LOW | [CVE-2022-0563](https://avd.aquasec.com/nvd/cve-2022-0563) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | libuuid1 2.38.1-5+deb12u3 | LOW | [CVE-2025-14104](https://avd.aquasec.com/nvd/cve-2025-14104) | No Bookworm fix reported; forky: 2.41.3-1; sid: 2.41.3-1; trixie: 2.41.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | login 1:4.13+dfsg1-1+deb12u2 | LOW | [CVE-2007-5686](https://avd.aquasec.com/nvd/cve-2007-5686) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | login 1:4.13+dfsg1-1+deb12u2 | LOW | [CVE-2024-56433](https://avd.aquasec.com/nvd/cve-2024-56433) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | login 1:4.13+dfsg1-1+deb12u2 | LOW | [TEMP-0628843-DBAD28](https://security-tracker.debian.org/tracker/TEMP-0628843-DBAD28) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | mount 2.38.1-5+deb12u3 | HIGH | [CVE-2026-53613](https://avd.aquasec.com/nvd/cve-2026-53613) | No Bookworm fix reported; forky: 2.42.2-1; sid: 2.42.2-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | mount 2.38.1-5+deb12u3 | HIGH | [CVE-2026-76642](https://avd.aquasec.com/nvd/cve-2026-76642) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | mount 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78408](https://avd.aquasec.com/nvd/cve-2026-78408) | No Bookworm fix reported; sid: 2.42.4-1 | No installed-distribution fix reported; affected |
| rook-backend:local | mount 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78409](https://avd.aquasec.com/nvd/cve-2026-78409) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | mount 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78410](https://avd.aquasec.com/nvd/cve-2026-78410) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | mount 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-13595](https://avd.aquasec.com/nvd/cve-2026-13595) | No Bookworm fix reported; forky: 2.42.2-1; sid: 2.42.2-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | mount 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-27456](https://avd.aquasec.com/nvd/cve-2026-27456) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | mount 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-3184](https://avd.aquasec.com/nvd/cve-2026-3184) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1 | No installed-distribution fix reported; will_not_fix |
| rook-backend:local | mount 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-53615](https://avd.aquasec.com/nvd/cve-2026-53615) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | mount 2.38.1-5+deb12u3 | LOW | [CVE-2022-0563](https://avd.aquasec.com/nvd/cve-2022-0563) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | mount 2.38.1-5+deb12u3 | LOW | [CVE-2025-14104](https://avd.aquasec.com/nvd/cve-2025-14104) | No Bookworm fix reported; forky: 2.41.3-1; sid: 2.41.3-1; trixie: 2.41.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | ncurses-base 6.4-4 | HIGH | [CVE-2025-69720](https://avd.aquasec.com/nvd/cve-2025-69720) | No Bookworm fix reported; forky: 6.6+20251231-1; sid: 6.6+20251231-1 | No installed-distribution fix reported; affected |
| rook-backend:local | ncurses-base 6.4-4 | MEDIUM | [CVE-2023-50495](https://avd.aquasec.com/nvd/cve-2023-50495) | No Bookworm fix reported; forky: 6.4+20230625-1; sid: 6.4+20230625-1; trixie: 6.4+20230625-1 | No installed-distribution fix reported; affected |
| rook-backend:local | ncurses-base 6.4-4 | LOW | [CVE-2025-6141](https://avd.aquasec.com/nvd/cve-2025-6141) | No Bookworm fix reported; forky: 6.5+20251115-2; sid: 6.5+20251115-2 | No installed-distribution fix reported; affected |
| rook-backend:local | ncurses-bin 6.4-4 | HIGH | [CVE-2025-69720](https://avd.aquasec.com/nvd/cve-2025-69720) | No Bookworm fix reported; forky: 6.6+20251231-1; sid: 6.6+20251231-1 | No installed-distribution fix reported; affected |
| rook-backend:local | ncurses-bin 6.4-4 | MEDIUM | [CVE-2023-50495](https://avd.aquasec.com/nvd/cve-2023-50495) | No Bookworm fix reported; forky: 6.4+20230625-1; sid: 6.4+20230625-1; trixie: 6.4+20230625-1 | No installed-distribution fix reported; affected |
| rook-backend:local | ncurses-bin 6.4-4 | LOW | [CVE-2025-6141](https://avd.aquasec.com/nvd/cve-2025-6141) | No Bookworm fix reported; forky: 6.5+20251115-2; sid: 6.5+20251115-2 | No installed-distribution fix reported; affected |
| rook-backend:local | openssl 3.0.22-1~deb12u1 | LOW | [CVE-2025-27587](https://avd.aquasec.com/nvd/cve-2025-27587) | No Bookworm fix reported; forky: 3.5.0-1; sid: 3.5.0-1; trixie: 3.5.0-1 | No installed-distribution fix reported; affected |
| rook-backend:local | passwd 1:4.13+dfsg1-1+deb12u2 | LOW | [CVE-2007-5686](https://avd.aquasec.com/nvd/cve-2007-5686) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | passwd 1:4.13+dfsg1-1+deb12u2 | LOW | [CVE-2024-56433](https://avd.aquasec.com/nvd/cve-2024-56433) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | passwd 1:4.13+dfsg1-1+deb12u2 | LOW | [TEMP-0628843-DBAD28](https://security-tracker.debian.org/tracker/TEMP-0628843-DBAD28) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | CRITICAL | [CVE-2026-13221](https://avd.aquasec.com/nvd/cve-2026-13221) | No Bookworm fix reported; forky: 5.42.3-1; sid: 5.42.3-1; trixie: 5.40.1-6+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | CRITICAL | [CVE-2026-42496](https://avd.aquasec.com/nvd/cve-2026-42496) | No Bookworm fix reported; forky: 5.42.3-1; sid: 5.42.3-1; trixie: 5.40.1-6+deb13u1 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | CRITICAL | [CVE-2026-8376](https://avd.aquasec.com/nvd/cve-2026-8376) | No Bookworm fix reported; forky: 5.40.1-8; sid: 5.40.1-8; trixie: 5.40.1-6+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | HIGH | [CVE-2026-42497](https://avd.aquasec.com/nvd/cve-2026-42497) | No Bookworm fix reported; forky: 5.42.3-1; sid: 5.42.3-1; trixie: 5.40.1-6+deb13u1 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | HIGH | [CVE-2026-48962](https://avd.aquasec.com/nvd/cve-2026-48962) | No Bookworm fix reported; forky: 5.40.1-8; sid: 5.40.1-8; trixie: 5.40.1-6+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | HIGH | [CVE-2026-57432](https://avd.aquasec.com/nvd/cve-2026-57432) | No Bookworm fix reported; forky: 5.40.1-8; sid: 5.40.1-8; trixie: 5.40.1-6+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | HIGH | [CVE-2026-57433](https://avd.aquasec.com/nvd/cve-2026-57433) | No Bookworm fix reported; forky: 5.40.1-8; sid: 5.40.1-8; trixie: 5.40.1-6+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | HIGH | [CVE-2026-9538](https://avd.aquasec.com/nvd/cve-2026-9538) | No Bookworm fix reported; forky: 5.42.3-1; sid: 5.42.3-1 | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | MEDIUM | [CVE-2025-15649](https://avd.aquasec.com/nvd/cve-2025-15649) | No Bookworm fix reported; forky: 5.40.1-8; sid: 5.40.1-8; trixie: 5.40.1-6+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | MEDIUM | [CVE-2026-12087](https://avd.aquasec.com/nvd/cve-2026-12087) | No Bookworm fix reported; forky: 5.42.3-1; sid: 5.42.3-1; trixie: 5.40.1-6+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | MEDIUM | [CVE-2026-15534](https://avd.aquasec.com/nvd/cve-2026-15534) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | MEDIUM | [CVE-2026-19487](https://avd.aquasec.com/nvd/cve-2026-19487) | No Bookworm fix reported; forky: 5.42.2-3; sid: 5.42.2-3 | No installed-distribution fix reported; affected |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | MEDIUM | [CVE-2026-48959](https://avd.aquasec.com/nvd/cve-2026-48959) | No Bookworm fix reported; forky: 5.40.1-8; sid: 5.40.1-8; trixie: 5.40.1-6+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | MEDIUM | [CVE-2026-48961](https://avd.aquasec.com/nvd/cve-2026-48961) | No Bookworm fix reported; forky: 5.40.1-8; sid: 5.40.1-8; trixie: 5.40.1-6+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | MEDIUM | [CVE-2026-7010](https://avd.aquasec.com/nvd/cve-2026-7010) | No Bookworm fix reported; forky: 5.40.1-8; sid: 5.40.1-8; trixie: 5.40.1-6+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | MEDIUM | [CVE-2026-7017](https://avd.aquasec.com/nvd/cve-2026-7017) | No Bookworm fix reported; forky: 5.42.3-1; sid: 5.42.3-1; trixie: 5.40.1-6+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | LOW | [CVE-2011-4116](https://avd.aquasec.com/nvd/cve-2011-4116) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | LOW | [CVE-2023-31486](https://avd.aquasec.com/nvd/cve-2023-31486) | No Bookworm fix reported; forky: 5.38.2-2; sid: 5.38.2-2; trixie: 5.38.2-2 | No installed-distribution fix reported; affected |
| rook-backend:local | perl-base 5.36.0-7+deb12u3 | UNKNOWN | [CVE-2026-82560](https://avd.aquasec.com/nvd/cve-2026-82560) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | sysvinit-utils 3.06-4 | LOW | [TEMP-0517018-A83CE6](https://security-tracker.debian.org/tracker/TEMP-0517018-A83CE6) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | tar 1.34+dfsg-1.2+deb12u1 | MEDIUM | [CVE-2026-18477](https://avd.aquasec.com/nvd/cve-2026-18477) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | tar 1.34+dfsg-1.2+deb12u1 | MEDIUM | [CVE-2026-18508](https://avd.aquasec.com/nvd/cve-2026-18508) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; fix_deferred |
| rook-backend:local | tar 1.34+dfsg-1.2+deb12u1 | MEDIUM | [CVE-2026-5704](https://avd.aquasec.com/nvd/cve-2026-5704) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | tar 1.34+dfsg-1.2+deb12u1 | LOW | [CVE-2005-2541](https://avd.aquasec.com/nvd/cve-2005-2541) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | tar 1.34+dfsg-1.2+deb12u1 | LOW | [TEMP-0290435-0B57B5](https://security-tracker.debian.org/tracker/TEMP-0290435-0B57B5) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | tzdata 2026b-0+deb12u1 | UNKNOWN | [DLA-4792-1](https://security-tracker.debian.org/tracker/DLA-4792-1) | Yes: 2026c-0+deb12u1 | Outside the four-package OS remediation; follow-up update required |
| rook-backend:local | util-linux 2.38.1-5+deb12u3 | HIGH | [CVE-2026-53613](https://avd.aquasec.com/nvd/cve-2026-53613) | No Bookworm fix reported; forky: 2.42.2-1; sid: 2.42.2-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux 2.38.1-5+deb12u3 | HIGH | [CVE-2026-76642](https://avd.aquasec.com/nvd/cve-2026-76642) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78408](https://avd.aquasec.com/nvd/cve-2026-78408) | No Bookworm fix reported; sid: 2.42.4-1 | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78409](https://avd.aquasec.com/nvd/cve-2026-78409) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78410](https://avd.aquasec.com/nvd/cve-2026-78410) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-13595](https://avd.aquasec.com/nvd/cve-2026-13595) | No Bookworm fix reported; forky: 2.42.2-1; sid: 2.42.2-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-27456](https://avd.aquasec.com/nvd/cve-2026-27456) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-3184](https://avd.aquasec.com/nvd/cve-2026-3184) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1 | No installed-distribution fix reported; will_not_fix |
| rook-backend:local | util-linux 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-53615](https://avd.aquasec.com/nvd/cve-2026-53615) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux 2.38.1-5+deb12u3 | LOW | [CVE-2022-0563](https://avd.aquasec.com/nvd/cve-2022-0563) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux 2.38.1-5+deb12u3 | LOW | [CVE-2025-14104](https://avd.aquasec.com/nvd/cve-2025-14104) | No Bookworm fix reported; forky: 2.41.3-1; sid: 2.41.3-1; trixie: 2.41.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux-extra 2.38.1-5+deb12u3 | HIGH | [CVE-2026-53613](https://avd.aquasec.com/nvd/cve-2026-53613) | No Bookworm fix reported; forky: 2.42.2-1; sid: 2.42.2-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux-extra 2.38.1-5+deb12u3 | HIGH | [CVE-2026-76642](https://avd.aquasec.com/nvd/cve-2026-76642) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux-extra 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78408](https://avd.aquasec.com/nvd/cve-2026-78408) | No Bookworm fix reported; sid: 2.42.4-1 | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux-extra 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78409](https://avd.aquasec.com/nvd/cve-2026-78409) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux-extra 2.38.1-5+deb12u3 | HIGH | [CVE-2026-78410](https://avd.aquasec.com/nvd/cve-2026-78410) | No Bookworm fix reported; forky: 2.42.3-1; sid: 2.42.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux-extra 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-13595](https://avd.aquasec.com/nvd/cve-2026-13595) | No Bookworm fix reported; forky: 2.42.2-1; sid: 2.42.2-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux-extra 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-27456](https://avd.aquasec.com/nvd/cve-2026-27456) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux-extra 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-3184](https://avd.aquasec.com/nvd/cve-2026-3184) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1 | No installed-distribution fix reported; will_not_fix |
| rook-backend:local | util-linux-extra 2.38.1-5+deb12u3 | MEDIUM | [CVE-2026-53615](https://avd.aquasec.com/nvd/cve-2026-53615) | No Bookworm fix reported; forky: 2.42-1; sid: 2.42-1; trixie: 2.41.5-0+deb13u1 | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux-extra 2.38.1-5+deb12u3 | LOW | [CVE-2022-0563](https://avd.aquasec.com/nvd/cve-2022-0563) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | util-linux-extra 2.38.1-5+deb12u3 | LOW | [CVE-2025-14104](https://avd.aquasec.com/nvd/cve-2025-14104) | No Bookworm fix reported; forky: 2.41.3-1; sid: 2.41.3-1; trixie: 2.41.3-1 | No installed-distribution fix reported; affected |
| rook-backend:local | zlib1g 1:1.2.13.dfsg-1 | CRITICAL | [CVE-2023-45853](https://avd.aquasec.com/nvd/cve-2023-45853) | No Bookworm fix reported; forky: 1:1.3.dfsg-2; sid: 1:1.3.dfsg-2; trixie: 1:1.3.dfsg-2 | No installed-distribution fix reported; will_not_fix |
| rook-backend:local | zlib1g 1:1.2.13.dfsg-1 | MEDIUM | [CVE-2026-27171](https://avd.aquasec.com/nvd/cve-2026-27171) | No Bookworm fix reported; forky: 1:1.3.dfsg+really1.3.2-1; sid: 1:1.3.dfsg+really1.3.2-1 | No installed-distribution fix reported; affected |
| rook-backend:local | zlib1g 1:1.2.13.dfsg-1 | MEDIUM | [CVE-2026-85091](https://avd.aquasec.com/nvd/cve-2026-85091) | No Bookworm fix reported; upstream fix unverified | No installed-distribution fix reported; affected |
| rook-backend:local | pip 26.0.1 | MEDIUM | [CVE-2026-13346](https://avd.aquasec.com/nvd/cve-2026-13346) | Yes: 26.2.0 | Outside the four-package OS remediation; follow-up update required |
| rook-backend:local | pip 26.0.1 | MEDIUM | [CVE-2026-3219](https://avd.aquasec.com/nvd/cve-2026-3219) | Yes: 26.1 | Outside the four-package OS remediation; follow-up update required |
| rook-backend:local | pip 26.0.1 | MEDIUM | [CVE-2026-6357](https://avd.aquasec.com/nvd/cve-2026-6357) | Yes: 26.1 | Outside the four-package OS remediation; follow-up update required |
| rook-backend:local | pip 26.0.1 | MEDIUM | [CVE-2026-8643](https://avd.aquasec.com/nvd/cve-2026-8643) | Yes: 26.1.2 | Outside the four-package OS remediation; follow-up update required |
