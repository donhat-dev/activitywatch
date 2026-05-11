# aw-odoo-sync

Central Odoo sync daemon for ActivityWatch.

## Responsibilities
- Read ActivityWatch buckets/events from local aw-server
- Sync only bucket-events with `duration > 0` to Odoo
- Upload screenshot files as Odoo attachments
- Avoid watcher-specific direct Odoo push as the default integration path

## Current status
This is an implementation skeleton for the new sync direction.

## Policy
- Bucket events are synced only when `duration > 0`
- `afkstatus`, `currentwindow`, and `os.hid.input` are valid initial bucket types
- Screenshot metadata events are not pushed to Odoo; only attachments are uploaded
