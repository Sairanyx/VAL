# yasasha: yasasha/dashboard
**Goal:** A good-looking dashboard per Excel record, opened from the object panel.
**Done:** app/dashboard.py (matplotlib: health gauge, condition, service with overdue in red, 3-day telemetry per equipment kind, events, maintenance, data problems; header warns on unconfirmed links). `GET /api/assets/{id}/dashboard.png` (cached) in app/api/main.py; Dashboard button and overlay in web/. app/copilot/store.py now also reads the pack's real telemetry names, event status and downtime.
**Verified:** make check; tests/test_dashboard.py (every kind, empty record, unknown record, API 200/404). Real data: 30 of 30 drawn; API 0.9 s then 2 ms; Chromium: P-005 opens, Esc closes, unlinked cart has no button.
**Next:** Tell Hannu: Val's trend checks in copilot.py use current_a, temperature_c, vibration_rms_mm_s, which this pack doesn't have, so Val misses P-005's rising current.
**Blockers:** none. web/ is Benjamin's area and the store is Hannu's: ask before merging.
