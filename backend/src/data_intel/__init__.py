"""data_intel — ACE Data Intelligence Layer.

Backend-local services powering the Relationship/Orphan Auditor, the Field
Coverage Matrix (Data Lineage Engine), and the Commercial Data Explorer.

See docs.md/ACE-Data-Intelligence-Layer.md (data-assimilation/docs.md/) for
the full design rationale. This package deliberately lives in `backend/src/`
rather than `data-assimilation/` — the backend container is the only
continuously-running, live-DB-connected process; `data-assimilation/` is a
separately-deployed ETL toolkit with no filesystem/DB bridge to the backend
(see entity_field_maps.py docstring for why this means a second, hand-mirrored
copy of the Sage field mappings exists here).
"""
