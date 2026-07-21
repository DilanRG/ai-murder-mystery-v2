# Historical save fixtures

`foundation_v4_positional_save.json` was emitted directly by the code at the
annotated tag `ashwick-authored-foundation-v1`, commit
`761193a55828772ec7668190c8a010b2f51ee841`. The tagged tree created an
`ashwick_sample` engine, advanced the opening, then applied a move to the
library with the persisted NPC selection
`{"captain_marcus_drake": "option_01"}` before calling `snapshot_engine`.

The fixture is intentionally static. Tests must not regenerate it with the
current engine or invoke Git at runtime.
