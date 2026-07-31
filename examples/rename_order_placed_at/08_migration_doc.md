# Migration: rename-orders-order_placed_at

`order_placed_at` disappeared and `order_created_at` appeared with the same type TIMESTAMP_NTZ at the same ordinal position (3) — inferred as a rename with 0.95 confidence.

The deterministic engine changed 4 file artifact(s). 2 downstream model(s) remain insulated by aliases, and 7 code-bearing asset(s) were correctly skipped using DataHub lineage evidence.

Every generated SQL reference passed the validator hard gate before this artifact was emitted.
