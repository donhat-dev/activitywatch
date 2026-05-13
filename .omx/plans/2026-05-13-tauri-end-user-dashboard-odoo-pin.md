# Plan: Tauri End-User Dashboard With Odoo PIN Setup

## Requirements Summary

- Replace the current ActivityWatch welcome/home content in `aw-tauri/aw-webui/src/views/Home.vue`.
  Current content starts at `h3 Hello early user,` and ends with the settings hint in the same file (`aw-tauri/aw-webui/src/views/Home.vue:6-68`).
- Target first screen is an end-user dashboard, not a contributor/early-user landing page.
- Header area must show:
  - `Hello <USER>`
  - right-aligned `<USER_NAME> - [logout]`
  - visually similar to current compact `h3` heading placement in `Home.vue`.
- Add a UI model for entering:
  - `odoo_url`
  - `pin_code`
- Make Odoo-related config shared across `aw-odoo-sync`, `aw-watcher-screenshot-mini`, and `aw-watcher-input` through one general/global config source.
- Expose config through the general settings API:
  - use `/api/0/settings` for full settings visibility
  - use `/api/0/settings/odoo_config` for Odoo-only config read/write
- Add a public API endpoint that resolves public user data from a PIN and returns at least the user's display name.
- Leave the inner dashboard content blank for now.

## Current Code Facts

- Tauri uses its own copied Web UI at `aw-tauri/aw-webui/src/views/Home.vue`; it currently mirrors the classic ActivityWatch home text (`aw-tauri/aw-webui/src/views/Home.vue:1-82`).
- The same home view exists in `aw-server/aw-webui` and `aw-server-rust/aw-webui`, but the active Tauri build uses `aw-tauri/aw-webui`, so this change should start there.
- Tauri launches the Rust server through `aw-server-rust` and mounts API routes in `aw-server-rust/aw-server/src/endpoints/mod.rs:130-192`.
- Existing server settings API already supports generic persisted settings under `/api/0/settings` using `GET`, `POST`, and `DELETE` (`aw-server-rust/aw-server/src/endpoints/settings.rs:24-101`).
- Existing frontend global server store lives at `aw-tauri/aw-webui/src/stores/server.ts:1-28` and uses `getClient().getInfo()`.
- Existing AW client wrapper exposes the underlying client from `aw-tauri/aw-webui/src/util/awclient.ts:35-40`; nearby code already uses `$aw.baseURL` for direct API links (`aw-tauri/aw-webui/src/views/Buckets.vue:51`).
- `aw-odoo-sync` already models Odoo connection config as `base_url` and `pin_code` (`aw-odoo-sync/aw_odoo_sync/config.py:27-37`) and includes these fields in sync requests (`aw-odoo-sync/aw_odoo_sync/odoo_client.py:159-167`).
- `aw-odoo-sync` currently has its own TOML config discovery (`aw-odoo-sync/aw_odoo_sync/config.py:69-107`). The target design should keep TOML as a compatibility fallback, not the primary source for user-entered dashboard config.

## Proposed Design

### Frontend Scope

Implement this first only in `aw-tauri/aw-webui`. Do not touch `aw-server/aw-webui` or `aw-server-rust/aw-webui` unless the project later decides to keep all three UI copies synchronized.

`Home.vue` becomes a dashboard shell:

- Header row:
  - left: `h3 Hello {{ greetingUser }}`
  - right: `{{ userName }} - logout`
- Setup form:
  - `odoo_url` text/url input
  - `pin_code` password or text input
  - submit button to resolve public user
  - basic loading/error state
- Blank dashboard body:
  - render an empty content container after the header/form
  - no marketing/help text

State model:

- Add a small Pinia store, for example `aw-tauri/aw-webui/src/stores/odoo.ts`, instead of overloading `server.ts`.
- Store shape:
  - `odooUrl: string`
  - `pinCode: string`
  - `enabled: boolean`
  - `employeeId: string | null`
  - `deviceId: string | null`
  - `deviceName: string | null`
  - `timeoutSecs: number`
  - `pushScreenshots: boolean`
  - `pushMetadataEvents: boolean`
  - `publicUserName: string | null`
  - `publicUser: object | null`
  - `isLoading: boolean`
  - `error: string | null`
- Actions:
  - `loadConfig()` from `/api/0/settings/odoo_config`
  - `saveConfig()` to `/api/0/settings/odoo_config`
  - `resolvePublicUser()` POSTs `{ odoo_url, pin_code }` to the new API endpoint and saves returned user name.
  - `logout()` clears `pin_code`, `publicUserName`, `publicUser`, and persisted `odoo_config` auth identity fields.

Persisting via existing settings API avoids adding a second local config mechanism in the UI. The security caveat is that `pin_code` is then stored in the local ActivityWatch datastore; if the PIN should not be persisted, make the store persist only `odoo_url` and keep `pin_code` in memory. If watcher restart should preserve Odoo sync without user re-entry, persist `pin_code` but document that it is local-device sensitive config.

### Shared Odoo Config Contract

Use one canonical config key:

- `GET /api/0/settings/odoo_config`
- `POST /api/0/settings/odoo_config`
- `DELETE /api/0/settings/odoo_config`

Suggested stored JSON shape:

```json
{
  "enabled": true,
  "odoo_url": "http://localhost:8069",
  "pin_code": "123456",
  "employee_id": "",
  "device_id": "",
  "device_name": "",
  "timeout_secs": 10,
  "push_screenshots": true,
  "push_metadata_events": false,
  "public_user": {
    "name": "Employee Name"
  }
}
```

Field mapping:

- `odoo_url` is the UI/API name.
- `base_url` remains the internal `aw-odoo-sync` Python dataclass name for compatibility, but it should be populated from `odoo_config.odoo_url`.
- `pin_code`, `employee_id`, `device_id`, `device_name`, `timeout_secs`, `push_screenshots`, and `push_metadata_events` map directly to `aw-odoo-sync` config fields.

Consumers:

- `aw-odoo-sync` must read `odoo_config` from local ActivityWatch settings on startup and periodically before sync cycles, then fall back to its TOML `[odoo]` block only when the settings key is missing.
- `aw-watcher-screenshot-mini` must read the same `odoo_config` when it needs Odoo-aware behavior, especially `push_screenshots` and user identity context.
- `aw-watcher-input` must read the same `odoo_config` when it needs Odoo-aware behavior, especially `enabled`, `odoo_url`, and `pin_code`/resolved user identity.
- Any watcher-specific config stays in the watcher config file; Odoo identity/connection config must not be duplicated per watcher.

Implementation preference:

- Add a small shared Python helper in `aw-client`, for example `aw_client.settings`, because all three Python watcher/sync components already depend on ActivityWatch client functionality.
- Helper responsibilities:
  - `get_setting("odoo_config")`
  - `set_setting("odoo_config", value)` if needed by Python code
  - `get_odoo_config(host, port, timeout)` returning a typed dict/dataclass with safe defaults
  - mask `pin_code` in logs
- If changing `aw-client` is too broad for the first pass, duplicate a minimal read-only helper in `aw-odoo-sync` first and add follow-up work to move it into `aw-client`.

### Backend Scope

Add a small Odoo-focused endpoint module under `aw-server-rust/aw-server/src/endpoints`, for example:

- `odoo.rs`
- mounted in `build_rocket()` as `/api/0/odoo`

Endpoint:

- `POST /api/0/odoo/public-user`
- request body:
  ```json
  {
    "odoo_url": "http://localhost:8069",
    "pin_code": "123456"
  }
  ```
- success response:
  ```json
  {
    "success": true,
    "user": {
      "name": "Employee Name"
    }
  }
  ```
- error response should use existing `HttpErrorJson` conventions.

Config API:

- Do not add a separate Odoo config endpoint unless the generic settings API is insufficient.
- Prefer the existing generic settings API:
  - `GET /api/0/settings/odoo_config`
  - `POST /api/0/settings/odoo_config`
  - `DELETE /api/0/settings/odoo_config`
- The frontend Odoo store should treat `/api/0/settings/odoo_config` as the canonical local config endpoint.
- The public-user endpoint should either:
  - validate the supplied `{ odoo_url, pin_code }` without persisting, then the frontend persists via `/api/0/settings/odoo_config`; or
  - accept an explicit `persist: true` flag and persist through the same settings key.
  Prefer the first option to keep validation and persistence separate.

Odoo upstream call:

- Use Rust HTTP client already available in the dependency tree if present; otherwise add `reqwest` to `aw-server-rust/aw-server/Cargo.toml`.
- Normalize `odoo_url` by trimming trailing slash.
- Suggested Odoo endpoint contract:
  - `POST {odoo_url}/hr_attendance/get_employee_by_pin`
  - body `{ "pin_code": "<pin>" }`
  - accept `employee.name` as the primary response shape from Odoo, and keep compatibility with `{ success, data: { name } }` or `{ name }` if the controller response changes during rollout.
- Validate:
  - `odoo_url` is non-empty and starts with `http://` or `https://`
  - `pin_code` is non-empty
  - timeout is bounded, e.g. 10 seconds
  - do not log raw `pin_code`

If the Odoo endpoint name is not fixed yet, isolate it in one helper function so it can be renamed without touching UI code.

## Implementation Steps

1. **Add backend endpoint module**
   - Create `aw-server-rust/aw-server/src/endpoints/odoo.rs`.
   - Add request/response structs with `serde::{Deserialize, Serialize}`.
   - Add `#[post("/public-user", data = "<request>", format = "application/json")]`.
   - Return `HttpErrorJson` for invalid input, upstream HTTP errors, and missing user name after parsing the Odoo `get_employee_by_pin` response.

2. **Mount backend route**
   - Update `aw-server-rust/aw-server/src/endpoints/mod.rs`.
   - Add `mod odoo;` near the other endpoint modules.
   - Add `.mount("/api/0/odoo", routes![odoo::public_user])` near the other `/api/0/*` mounts.

3. **Add endpoint tests**
   - Extend `aw-server-rust/aw-server/tests/api.rs` with request validation tests:
     - empty `odoo_url` returns `400`
     - empty `pin_code` returns `400`
   - Add a small unit test for parsing supported response shapes in `odoo.rs` without needing a live Odoo server.
     Supported shapes should include an `employee` object returned from `/hr_attendance/get_employee_by_pin`.
   - If introducing outbound HTTP mocking is too heavy, keep upstream success as a helper-level unit test and manually verify against Odoo later.

4. **Define canonical Odoo config model**
   - Add a frontend `OdooConfig` type in `aw-tauri/aw-webui/src/stores/odoo.ts`.
   - Add a Rust request/response config struct in `aw-server-rust/aw-server/src/endpoints/odoo.rs` only if the Odoo endpoint needs to deserialize the same shape.
   - Keep the persisted key name exactly `odoo_config`.
   - Use `odoo_url` in API/UI JSON and map to Python `base_url` only inside `aw-odoo-sync`.

5. **Add shared Python config reader**
   - Preferred: add `aw-client/aw_client/settings.py` or similar shared helper.
   - Implement read access to `/api/0/settings/odoo_config` through the existing ActivityWatch client/base URL settings.
   - Return safe defaults when the key is missing or server is unavailable.
   - Mask `pin_code` in any log output.

6. **Wire `aw-odoo-sync` to global config**
   - Update `aw-odoo-sync/aw_odoo_sync/config.py` so the parsed TOML remains a fallback.
   - Before constructing `OdooPushConfig`, fetch `/api/0/settings/odoo_config` from the local ActivityWatch server.
   - Merge precedence:
     1. CLI/TOML explicit non-empty values if user supplied a custom config path
     2. `/api/0/settings/odoo_config`
     3. default TOML/dataclass defaults
   - Preserve existing `config.toml.example`, but mark `[odoo]` as fallback/advanced config once docs are updated.

7. **Wire `aw-watcher-screenshot-mini` to global config**
   - Add read-only use of the shared Odoo config helper.
   - Use the shared config for Odoo-related behavior only; keep screenshot interval/output-dir config watcher-local.
   - Ensure `push_screenshots=false` in `odoo_config` can disable Odoo screenshot push/sync behavior where applicable.

8. **Wire `aw-watcher-input` to global config**
   - Add read-only use of the shared Odoo config helper.
   - Keep input capture settings watcher-local.
   - Use `enabled`, `odoo_url`, and resolved identity from `odoo_config` for any Odoo-aware input classification/sync hooks.

9. **Add frontend Odoo dashboard store**
   - Create `aw-tauri/aw-webui/src/stores/odoo.ts`.
   - Use `getClient().req` from `aw-tauri/aw-webui/src/util/awclient.ts:35-40` for:
     - `GET /api/0/settings/odoo_config`
     - `POST /api/0/settings/odoo_config`
     - `DELETE /api/0/settings/odoo_config` or POST null/empty object
     - `POST /api/0/odoo/public-user`
   - Keep API response typing local and explicit.

10. **Replace Tauri Home view**
   - Edit `aw-tauri/aw-webui/src/views/Home.vue`.
   - Remove lines `6-68`, including the early-user text, spread/support/resources blocks, and settings hint.
   - Keep `mapState(useServerStore, ['info'])` only if needed for fallback hostname/device labels; otherwise remove it.
   - Add form bindings to the new Odoo store.
   - Render blank content area below setup.

11. **Header behavior**
   - `greetingUser` can initially be `"user"` or a derived name from `publicUserName`.
   - `userName` displays `publicUserName` when resolved; otherwise show blank or `"Not connected"`.
   - `logout` calls the store action and clears local persisted config.

12. **Build and smoke verify**
   - From `aw-tauri`: run `npm run build` or the project’s existing `make -C aw-tauri build` path.
   - Run Rust tests for `aw-server-rust/aw-server` endpoint code.
   - Launch Tauri build and verify Home renders without old text.

## Acceptance Criteria

- `aw-tauri/aw-webui/src/views/Home.vue` no longer contains:
  - `Hello early user,`
  - `Spread the word`
  - `Support us!`
  - `You can change which page opens when you open ActivityWatch`
- Home page shows a compact header with `Hello <USER>` on the left and `<USER_NAME> - logout` on the right.
- Home page includes editable fields for `odoo_url` and `pin_code`.
- Home page reads and writes Odoo config through `/api/0/settings/odoo_config`, not a dashboard-specific key.
- Submitting the form calls `POST /api/0/odoo/public-user`.
- `/api/0/settings` includes the `odoo_config` entry when config has been saved.
- `aw-odoo-sync`, `aw-watcher-screenshot-mini`, and `aw-watcher-input` all read Odoo-related config from the same canonical `odoo_config` source.
- Watcher-local config files no longer need duplicated Odoo URL/PIN values for the standard Tauri flow.
- Backend rejects blank `odoo_url` and blank `pin_code` with `400`.
- Backend does not log raw `pin_code`.
- Successful backend response exposes a user display name that the frontend shows as `<USER_NAME>`.
- Dashboard body below the header/setup area is intentionally blank.
- Tauri webui build completes.

## Risks and Mitigations

- **Unknown Odoo public endpoint contract**: keep the Rust Odoo client helper isolated around `{odoo_url}/hr_attendance/get_employee_by_pin` and tolerant of `employee.name`, `{ data: { name } }`, and `{ name }` response shapes.
- **PIN persistence risk**: decide during implementation whether to persist `pin_code`; default safer option is persist `odoo_url` only and keep `pin_code` in memory unless the user explicitly needs auto-login.
- **Config ownership drift**: avoid introducing `odoo_dashboard`, watcher-local `[odoo]`, and API body state as separate sources of truth. The canonical persisted source is `/api/0/settings/odoo_config`.
- **Watcher startup ordering**: if watchers start before the Rust server/settings endpoint is available, the shared helper must retry or fall back to local TOML defaults, then refresh config after startup.
- **Cross-submodule helper churn**: moving shared config code into `aw-client` affects multiple submodules. Keep helper narrow and read-only first.
- **Duplicated webui copies**: implement only in `aw-tauri/aw-webui` for the Tauri product target; do not silently change classic `aw-server` UI.
- **CORS/auth interaction**: because calls go through local `/api/0/odoo/public-user`, the browser avoids direct Odoo CORS issues and keeps token/auth handling aligned with ActivityWatch.
- **Build environment on Windows**: root build can fail on POSIX shell assumptions; verify with `make -C aw-tauri build` plus targeted Rust/webui checks if root `make build` is not usable.

## Verification Steps

- `rg -n "Hello early user|Spread the word|Support us|You can change which page opens" aw-tauri/aw-webui/src/views/Home.vue` returns no matches.
- `rg -n "odoo_dashboard" aw-tauri aw-server-rust aw-odoo-sync aw-watcher-screenshot-mini aw-watcher-input` returns no matches.
- Saving config from the Home page creates/updates `/api/0/settings/odoo_config`.
- `GET /api/0/settings` shows an `odoo_config` key after saving config.
- Start each watcher with only global `odoo_config` present and no watcher-local Odoo PIN duplication:
  - `aw-odoo-sync` uses the shared `odoo_url`/`pin_code`
  - `aw-watcher-screenshot-mini` sees the shared Odoo screenshot flags/context
  - `aw-watcher-input` sees the shared Odoo enabled/user context
- `cargo test -p aw-server` or the closest available `aw-server-rust/aw-server` test command passes for endpoint tests.
- `npm run build` in `aw-tauri/aw-webui` succeeds.
- `make -C aw-tauri build TAURI_WATCHERS="aw-watcher-input aw-watcher-screenshot-mini aw-odoo-sync"` succeeds.
- Manual smoke:
  - open Tauri app
  - enter `odoo_url` and invalid PIN; see error
  - enter valid PIN; see `<USER_NAME>`
  - click `logout`; name and pin state clear
