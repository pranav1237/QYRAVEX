# Progressive challenge suite

Eight offline challenges test core reliability without paid API credentials:

- **C1 — Evidence identity:** evidence includes stable identity and source.
- **C2 — Conflict detection:** divergent values are preserved as conflicts.
- **C3 — Confidence bounds:** confidence remains between zero and one.
- **C4 — Missing source:** provider failure is visible as a report limitation.
- **C5 — Provenance:** source is retained for each evidence item.
- **C6 — Unit awareness:** values can carry units.
- **C7 — Memory deduplication:** stable evidence IDs use SQLite upsert semantics.
- **C8 — No invented output:** empty evidence produces no sourced findings.

Run with workbridge benchmark --all or pytest. These are baseline acceptance checks, not a substitute for provider integration tests, adversarial evaluation, or investment-domain validation.
