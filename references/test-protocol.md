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

Each selected position has an independently random token. The token is not derived from run id, page number, filename, or any visible value.

1. Generate the pack.
2. Keep `manifest.json` hidden from the model.
3. Give the model `probe-sheet.md` only.
4. Capture exact claimed tokens.
5. Verify the claims against the manifest after the claims have been captured.

A correct canary proves end-to-end availability for that position during that probe. A miss means end-to-end availability was not demonstrated. It does not, alone, prove parsing failure.

## 6. Boundary search

Bracket with a known pass and known fail, then bisect. Repeat both boundary values before publishing.

Stop and investigate when:

- the same value sometimes passes and sometimes fails;
- a larger value passes while a smaller value fails;
- a baseline fails;
- a result depends on another variable that was not held constant.

When no upper fail exists, do **not** automatically keep doubling. Choose a safe upper bracket from official guidance or obtain an explicit user-approved cap.

## 7. Attachment-count tests

Each count is a separate scenario and must be uploaded in a separate turn. A 5-file and a 10-file case cannot be tested by uploading 15 files once and retrospectively treating subsets as separate observations.

## 8. Reconciliation

- `match`: measured interval is consistent with the published boundary;
- `more-restrictive-than-documented`: reliable pass stopped below it;
- `more-permissive-than-documented`: values above it worked, but remain unsupported headroom;
- `no-published-limit`: scoped measurement only;
- `inconclusive`: evidence is insufficient.

## 9. Scope

Always state that observations are scoped to the tested environment, path, tenant configuration, region, licence, harness/service version, downstream dependencies, and date. Do not convert one scoped observation into an unconditional product claim.
