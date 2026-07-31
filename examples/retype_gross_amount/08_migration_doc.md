# Migration: retype-orders-gross_amount

`gross_amount` remains present, but its native type changed from NUMBER(12,2) to VARCHAR(20) — detected as a retype.

The deterministic engine changed 2 file artifact(s). 3 downstream model(s) remain insulated by aliases, and 7 code-bearing asset(s) were correctly skipped using DataHub lineage evidence.

Every generated SQL reference passed the validator hard gate before this artifact was emitted.
