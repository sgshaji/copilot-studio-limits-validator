# Safety boundaries

This skill validates live product boundaries with the minimum controlled workload needed to answer a question. It is not a load, stress, quota-exhaustion, or denial-of-service tool.

## Passive — allowed by default

- generate synthetic artefacts locally;
- read/write local ledgers;
- plan a bounded next probe;
- render reports;
- inspect current official documentation.

## Active-safe — announce before running

- upload a small controlled pack to a test agent;
- query canaries from synthetic documents;
- read controlled SharePoint/OneDrive test content;
- invoke a non-destructive tool/API against a non-production target.

State the scenario count, artefact count, and total bytes before active testing.

Check that figure against free space first. The agent sandbox holds a few
hundred MB, and the pack is copied again when handed to the user, so a
multi-path comparison generated up front can exhaust it mid-run. Build one pack
at a time.

## Active-sensitive — explicit direction required

- production agents or live-user environments;
- tools/actions that create, update, delete, send, notify, approve, purchase, or otherwise cause side effects;
- customer tenants the user does not administer;
- tests whose failure can create duplicate or real business records.

## Never

- bypass or spoof a platform-enforced limit;
- pursue throttling, concurrency exhaustion, quota exhaustion, or resource exhaustion;
- continue probing after the boundary is adequately established;
- auto-double an unbounded workload merely to make something fail;
- use real customer documents when synthetic content can answer the question;
- store tenant IDs, environment IDs, user identities, secrets, connection details, or customer content in ledgers/reports.

## Safe discovery

If there is no documented or suspected upper bound, obtain an explicit safe cap or choose a conservative bound supported by authoritative guidance. If every value under the cap passes, report `no-upper-bound-within-tested-range`; do not keep expanding automatically.

## Evidence discipline

A test that was not run is `not-tested`/`unknown`, not `unsupported`. A canary miss identifies an end-to-end coverage failure, not an internal root cause unless direct evidence identifies that stage.

Never obtain a canary through a route other than the path under test. Reading the artefact with runtime code, unzipping it, or searching the filesystem produces a correct token that proves nothing about ingestion, parsing, indexing, or retrieval. If such a route was available, record `--path-integrity not-attested`; if one was used, record `bypass-observed` and do not publish the coverage result as evidence about that path.

Record the scope a measurement is valid under rather than asserting it in prose, and never record tenant identifiers, user identities, secrets, or connection details while doing so.
