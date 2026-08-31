# Test protocol

## 1. Frame one boundary at a time

Record the capability, path, numeric metric, unit, success criterion, and variables that must remain constant. Results do not transfer automatically between direct upload, knowledge upload, SharePoint, OneDrive, tools, generated outputs, and runtime execution.

## 2. Record official guidance before measuring

Use current first-party Microsoft guidance. Record the exact source and unit. If no authoritative figure exists, use `no-published-limit` rather than inventing one.

## 3. Change one governing variable

Examples:

- file-size test: vary bytes, hold format/page count/content pattern constant;
- page-count test: vary pages, hold file byte size/format/content pattern constant;
- attachment-count test: vary attachment count, keep per-file size/format/content pattern constant;
- tool-response test: vary response size/records, hold tool contract and request semantics constant.

If the supposedly controlled variables change materially, the result is confounded.

## 4. Distinguish lifecycle evidence

| Stage | What it means |
| --- | --- |
| `accepted` | client/UI/API accepted the input |
| `transferred` | input became available to the agent/runtime |
| `processed` | a directly observed processing/indexing/parsing signal succeeded |
| `retrievable` | at least some target content was available to the agent |
| `coverage` | all selected end-to-end probe positions were demonstrated |

Do not mark an internal stage failed merely because a downstream canary was missing.

## 5. Canary protocol

Each selected position carries an independently random 96-bit token. It is not derived from the run id, page number, filename, or any visible value.

The token is embedded in the artefact and nowhere else. `manifest.json` stores only its SHA-256 digest, and verification hashes what the model claimed before comparing. Reading the manifest therefore cannot reveal an answer: correctness no longer depends on keeping a file away from the model.

1. Generate the pack.
2. Give the model `probe-sheet.md` only; it lists probe positions, never tokens.
3. Capture the exact claimed tokens.
4. Verify with `record_result.py`, which compares digests.

A correct canary proves end-to-end availability for that position during that probe. A miss means end-to-end availability was not demonstrated. It does not, alone, prove parsing failure.

## 5a. Path integrity — do not let the answer arrive another way

A canary proves the agent **obtained** the content. It proves the *tested path* carried the content only if no other route existed.

This matters because the agent may have a Python-capable runtime. If it can open the uploaded PDF directly, unzip an Office package, or grep the filesystem, then a correct token says nothing about ingestion, parsing, indexing, or retrieval — only that the agent found the string somehow.

**Rule: retrieve canaries only through the path under test.** For a document-processing test, prohibit direct file reads, ZIP inspection, PDF parsing libraries, and filesystem search, unless one of those *is* the capability being measured. Check the activity trace where the product exposes one.

Record the outcome honestly with `--path-integrity`:

| Value | Meaning |
| --- | --- |
| `attested` | no alternate route was available or used; coverage evidence applies to the tested path |
| `not-attested` | not verified; coverage shows only that the agent obtained the content somehow |
| `bypass-observed` | an alternate route was available or used; coverage evidence is void for this path |

Code cannot check this. The report states which attestation was recorded and weakens its language accordingly.

## 6. Boundary search

Bracket with a known pass and known fail, then bisect. Repeat both boundary values before publishing.

Stop and investigate when:

- the same value sometimes passes and sometimes fails;
- a larger value passes while a smaller value fails;
- a baseline fails;
- a result depends on another variable that was not held constant.

When no upper fail exists, do **not** automatically keep doubling. Choose a safe upper bracket from official guidance or obtain an explicit user-approved cap.

## 7. One artefact per turn; fresh conversation per decisive test

Generating a whole sweep at once is a labour saving. Uploading it at once is a measurement error: six files totalling 260 MB in one turn varies per-file size, attachment count, and total turn payload simultaneously, so a failure cannot be attributed to any of them.

- Attach **one artefact per turn**.
- Use a **fresh conversation** for the values that decide the boundary, so earlier attachments and earlier context cannot participate.

## 7a. Attachment-count tests

Each count is a separate scenario and needs its own **fresh conversation**, not merely a new turn: attachments from earlier turns can remain in context and change the count actually under test. A 5-file and a 10-file case cannot be tested by uploading 15 files once and retrospectively treating subsets as separate observations.

## 8. Reconciliation

A verdict must be earned by evidence that was actually collected. Never call a boundary permissive or restrictive unless a value on the relevant side of it was really tested.

| Verdict | Requires |
| --- | --- |
| `confirmed-match` | the documented value itself tested and passed on repeated trials, and the nearest tested value above it failed on repeated trials, within tolerance |
| `consistent-with-guidance` | nothing contradicts the documented value, but the boundary is not resolved — typically it lies inside the measured interval without having been tested directly |
| `more-restrictive-than-documented` | a value at or below the documented boundary failed consistently |
| `observed-headroom` | a value strictly above the documented boundary passed. Unsupported headroom in one environment, not a product capability |
| `no-published-limit` | no authoritative figure was recorded; scoped measurement only |
| `inconclusive` | evidence does not settle the question — including the common case where the documented value passed but nothing above it was tested |

A documented value that lies between a pass and a fail is *not* a match. If 40 passes and 60 fails, the boundary is somewhere in (40, 60); 50 has not been validated.

## 9. Scope

Record the scope, do not merely assert it. The ledger carries `platform`, `harness`, `environmentType`, `region`, `channel`, `model`, `licenseContext`, `testedAt`, and `notes`; supply them with `--scope KEY=VALUE` at init. A result whose scope is unrecorded cannot be compared with a later run or another environment, and the report says so.

Record `--documented-checked-at` as well: guidance changes, and a documented value with no read date is not attributable. Evidence is only labelled `Official guidance + Measured` when a value, a source, and a check date are all present.

Never record tenant identifiers, user identities, secrets, or connection details.

Do not convert one scoped observation into an unconditional product claim.
