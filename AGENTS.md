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
- `SKIP_SERVER_RUST=true`: skip `aw-server-rust`.
- `SKIP_WEBUI=true`: skip Web UI-related build work where supported.
- `AW_EXTRAS=true`: include optional components such as `aw-notify` and `aw-watcher-input`.

## Component map
- `aw-server`: Python server, current default implementation.
- `aw-server-rust`: Rust server; future-facing implementation, and Tauri builds package `aw-sync` from here.
- `aw-qt`: classic desktop shell/manager.
- `aw-tauri`: newer Tauri desktop shell.
- `aw-watcher-afk`, `aw-watcher-window`, `aw-watcher-input`, `awatcher`: watcher components.
- `aw-core`, `aw-client`: shared/core and client-library pieces.
- `aw-notify`: optional notification component.

## Working conventions
- Root `Makefile` orchestrates submodule targets. Many actions are delegated into submodules.
- If a change is specific to one component, inspect that submodule's own docs and build files before editing.
- Prefer CI-proven command combinations over ad hoc build steps.
- Commit messages are encouraged to follow Conventional Commits (`feat`, `fix`, `chore`, `ci`, `docs`, `style`, `refactor`, `perf`, `test`).

## Common pitfalls
- The repo is incomplete without submodules.
- Not every submodule supports every target; the root `Makefile` checks target availability dynamically.
- Packaging differs between classic and Tauri builds.
- Linux and packaging dependencies are platform-specific; rely on the official install guide and `.github/workflows/build.yml` instead of duplicating package lists here.
- Some older docs links still use `activitywatch.readthedocs.io`; prefer `docs.activitywatch.net` for new references.

## Key references
- Source install: <https://docs.activitywatch.net/en/latest/installing-from-source.html>
- Project overview: `README.md`
- Contribution guide: `CONTRIBUTING.md`
- Build workflow: `.github/workflows/build.yml`
- Upgrade/integration workflow: `.github/workflows/test.yml`
- Submodule layout: `.gitmodules`

## When adding more agent customizations
Consider adding scoped instructions if future work clusters around one area:
- submodule-specific instructions for `aw-server` or `aw-server-rust`
- packaging/release instructions for `scripts/package/`
- test-focused instructions for integration and upgrade workflows
