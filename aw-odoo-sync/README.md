# aw-odoo-sync

Central Odoo sync daemon for ActivityWatch.

## Responsibilities
- Read ActivityWatch buckets/events from local aw-server
- Poll Odoo tracking state frequently and publish it locally for UI/diagnostics
- Sync only when Odoo reports tracking is enabled and a timer/task is running
- Sync only bucket-events with `duration > 0` to Odoo
- Upload screenshot files as Odoo attachments
- Keep watcher-specific direct Odoo push out of the default integration path

## Current status
This is an implementation skeleton for the new sync direction.

## Policy
- Bucket events are synced only when `duration > 0`
- `bucket_allowlist` lists event types eligible for Odoo sync, defaulting to `os.hid.input`
- `afkstatus`, `currentwindow`, and `os.hid.input` are valid bucket-event types
- Events are discarded locally while Odoo reports `is_working=false` or `is_tracking=false`
- Events older than the current Odoo timer `started_at` are skipped
- Idle input/AFK events are synced only when Odoo reports `is_tracking_idle=true`
- Screenshot metadata events are not pushed to Odoo; only attachments are uploaded
- Screenshot uploads are selected by deterministic per-cycle targets from Odoo `screenshot_per_cycle` and `cycle_time_secs`
