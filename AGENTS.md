# ActivityWatch agent guide

## Repo purpose
- This repository is the ActivityWatch meta-repo: it bundles official components as `git submodule`s for source installs, packaging, and releases.
- Prefer making changes in the relevant submodule (`aw-server`, `aw-server-rust`, `aw-qt`, `aw-tauri`, watchers) instead of adding root-level glue unless the change truly spans the bundle.

## First steps
- Initialize submodules before assuming files or commands are missing: `git submodule update --init --recursive`.
- Follow the official source-install guide for environment setup and platform prerequisites: <https://docs.activitywatch.net/en/latest/installing-from-source.html>.
- For contributor expectations, read `CONTRIBUTING.md`.

## Trusted root commands
Use CI-backed root commands from `Makefile` when validating changes:
- `make build`
- `make test`
- `make test-integration`
- `make lint`
- `make typecheck`
- `make package`

Typical setup flow used by CI:
- create and activate a virtualenv
- `pip3 install poetry==1.4.2`
- `poetry install`
- `make build`

## Build modes and flags
- `TAURI_BUILD=true`: build the Tauri desktop bundle instead of the `aw-qt` bundle.
- `TAURI_WATCHERS="aw-watcher-input aw-watcher-screenshot-mini aw-odoo-sync"`: watcher set bundled into the Tauri app.
- `TAURI_BUNDLES=app`: force Tauri to build only the `.app`; this is required when a separate signed DMG script will create the DMG.
- `TAURI_LOAD_ENV_FILE=false`: skip loading `.env`; use this for CI and any command where secrets come from the environment.
- `TAURI_SIGN=true`: require a macOS signing identity for the Tauri DMG flow.
- `TAURI_NOTARIZE=false` or `--skip-notarize`: sign locally without notarization.
- `TAURI_RUN_TESTS=false`: skip test execution in the Tauri workflow when packaging-only validation is intended.
- `SKIP_SERVER_RUST=true`: skip `aw-server-rust`.
- `SKIP_WEBUI=true`: skip Web UI-related build work where supported.
- `AW_EXTRAS=true`: include optional components such as `aw-notify` and `aw-watcher-input`.

## Tauri macOS build flow
- The active GitHub Actions Tauri workflow is macOS-only unless explicitly re-enabled for Windows. Do not add Ubuntu packaging jobs unless there is a concrete Linux artifact requirement.
- Local signed but unnotarized rebuild:
  - `TAURI_LOAD_ENV_FILE=false TAURI_SIGN=true TAURI_NOTARIZE=false APPLE_TEAMID=<team-id> PYTHON=python3 bash scripts/package/build-signed-tauri-dmg.sh --skip-notarize`
- CI signed build requirements:
  - `CERTIFICATE_MACOS_P12_BASE64`
  - `CERTIFICATE_MACOS_P12_PASSWORD`
  - `APPLE_TEAMID`
- CI notarization is optional. Provide `APPLE_EMAIL` and `APPLE_PASSWORD` only when notarization should run. Without them, the script should sign and skip notarization.
- The signed DMG script owns DMG creation. Keep Tauri's own build constrained with `TAURI_BUNDLES=app` so `bundle_dmg.sh` is not invoked accidentally.
- The workflow should call the packaging script with `bash scripts/package/build-signed-tauri-dmg.sh`; do not rely on executable bits surviving checkout.
- A successful local signed/unnotarized build produces `dist/activitywatch-tauri-<version>-macos-arm64.dmg` and a signed `dist/ActivityWatch.app`.

## Component map
- `aw-server`: Python server, current default implementation.
- `aw-server-rust`: Rust server; future-facing implementation, and Tauri builds package `aw-sync` from here.
- `aw-qt`: classic desktop shell/manager.
- `aw-tauri`: newer Tauri desktop shell.
- `aw-watcher-afk`, `aw-watcher-window`, `aw-watcher-input`, `awatcher`: watcher components.
- `aw-core`, `aw-client`: shared/core and client-library pieces.
- `aw-notify`: optional notification component.
- `aw-odoo-sync`: single owner for pushing ActivityWatch data to Odoo.
- `aw-watcher-screenshot-mini`: screenshot collector; it should not push directly to Odoo.

## Working conventions
- Root `Makefile` orchestrates submodule targets. Many actions are delegated into submodules.
- If a change is specific to one component, inspect that submodule's own docs and build files before editing.
- Prefer CI-proven command combinations over ad hoc build steps.
- Commit messages are encouraged to follow Conventional Commits (`feat`, `fix`, `chore`, `ci`, `docs`, `style`, `refactor`, `perf`, `test`).
- When changing a submodule, commit and push inside that submodule, then update and commit the root submodule pointer.
- Do not commit secrets or real `.env` values. GitHub Actions should receive signing/notarization credentials through repository secrets.

## Odoo sync conventions
- Treat `aw-odoo-sync` as the only component that sends data to Odoo. Watchers collect data locally and write to ActivityWatch buckets.
- Keep Odoo event sync allowlisted by bucket type, for example `os.hid.input`.
- `aw-odoo-sync` should poll Odoo tracking context frequently enough for task state changes to take effect promptly, separate from slower data collection cycles such as screenshots.
- If Odoo config is disabled, log that sync is disabled and skip pushing without treating it as a watcher crash.
- If tracking context is unavailable, log the response shape/error clearly and keep retrying rather than crashing collectors.
- Screenshot watcher logs may say it is waiting for `aw-odoo-sync` tracking context and using fallback config; that is expected during startup or when Odoo sync is disabled.

## Watcher packaging conventions
- Tauri watcher package targets must leave a directory at `dist/<watcher-name>`, even if PyInstaller emits a single executable on a platform.
- Before copying `config.toml.example`, defensively ensure `dist/<watcher-name>` is a directory.
- Apply the same packaging shape rule to `aw-watcher-input`, `aw-watcher-screenshot-mini`, and `aw-odoo-sync`.
- PyInstaller hidden-import noise for Linux/Windows backends on macOS, such as `Xlib.*` or `win32timezone`, is usually non-fatal. Diagnose the actual exit status before changing hooks.

## Common pitfalls
- The repo is incomplete without submodules.
- Not every submodule supports every target; the root `Makefile` checks target availability dynamically.
- Packaging differs between classic and Tauri builds.
- Tauri packaging differs between building a raw `.app` and building a DMG. For the signed DMG flow, use `TAURI_BUNDLES=app` and let `scripts/package/build-signed-tauri-dmg.sh` create/sign the DMG.
- `fatal: No names found, cannot describe anything.` from version discovery can be non-fatal; the build may continue with a `.dev-<sha>` version.
- `source venv/bin/activate || source venv/Scripts/activate` prints a harmless first-path failure on Windows bash when the Windows activation path is used next.
- Linux and packaging dependencies are platform-specific; rely on the official install guide and `.github/workflows/build.yml` instead of duplicating package lists here.
- Some older docs links still use `activitywatch.readthedocs.io`; prefer `docs.activitywatch.net` for new references.

## Key references
- Source install: <https://docs.activitywatch.net/en/latest/installing-from-source.html>
- Project overview: `README.md`
- Contribution guide: `CONTRIBUTING.md`
- Build workflow: `.github/workflows/build.yml`
- Tauri build workflow: `.github/workflows/build-tauri.yml`
- Signed Tauri DMG script: `scripts/package/build-signed-tauri-dmg.sh`
- Upgrade/integration workflow: `.github/workflows/test.yml`
- Submodule layout: `.gitmodules`

## When adding more agent customizations
Consider adding scoped instructions if future work clusters around one area:
- submodule-specific instructions for `aw-server` or `aw-server-rust`
- packaging/release instructions for `scripts/package/`
- test-focused instructions for integration and upgrade workflows
