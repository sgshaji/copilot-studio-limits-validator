# Copilot Studio Limits Validator

Measure where a specific Copilot Studio capability stops working reliably, instead of treating a documented number or a successful upload as proof of end-to-end capability.

The skill is designed for **quantitative, bounded validation**: file size, page count, attachment count, tool payload size, record count, generated-output size, execution duration, and similar numeric boundaries.

> **Harness Explorer discovers what exists. Limits Validator measures how far a specific capability reliably works.**

## Why this exists

Three mistakes make platform limits easy to misstate:

1. **Accepted is not usable.** A file can be accepted while only part of its content is available later.
2. **Documentation is not a runtime measurement.** Published limits are the supported contract; environment behaviour still needs scoped validation when accuracy matters.
3. **A failed content probe is not automatically a parsing failure.** The cause may be parsing, indexing, retrieval, context handling, or another stage. The skill reports only the failure stage directly supported by evidence.

## What changed in v0.3

Review of v0.2 found three defects that could produce confidently wrong conclusions. All are fixed:

- **Reconciliation no longer claims more than was tested.** v0.2 called a run `more-permissive-than-documented` when the documented value was the *only* value tested, and `more-restrictive` when nothing had failed at all. Verdicts are now earned by evidence actually collected: `confirmed-match` requires the documented value to have been tested directly and repeated, with the nearest tested value above it failing.
- **A documented value between a pass and a fail is no longer a match.** If 40 passes and 60 fails, 50 has not been validated; that is now `consistent-with-guidance`, which cannot contradict the planner still asking for a bisection.
- **`formats` mode is gone.** It assigned a categorical metric (`format = pdf`) that the numeric pipeline could not process, crashing on `could not convert string to float: 'pdf'`. Format is a dimension to hold constant, not a metric to sweep: run one sweep per format and compare the ledgers.

Three further changes strengthen what the evidence means:

- **Path integrity.** A canary proves the agent obtained the content by *some* route. If it can read the artefact with Python, unzip it, or grep the filesystem, a correct token says nothing about ingestion or parsing. Runs now record `--path-integrity`, and the report weakens its language when the claim is not attested.
- **Canaries are verified by digest.** `manifest.json` stores SHA-256 hashes; the 96-bit token exists only inside the artefact. Reading the manifest cannot reveal an answer, so correctness no longer depends on keeping a file away from the model.
- **Scope is recorded, not merely asserted.** Platform, harness, environment, region, channel, model, licence, and date live in the ledger, alongside the date the official guidance was read. Evidence is labelled `Official guidance + Measured` only when a value, a source, and a check date are all present.

Experimental isolation was tightened too: artefacts are written to `<out-dir>/upload/`, uploaded **one per turn**, and attachment-count scenarios need a **fresh conversation** rather than a fresh turn.

## What changed in v0.2

- Canary tokens are now **independently cryptographically random** and cannot be derived from the visible run id, page number, file name, or bundled code.
- The ledger/planner/report model is now **metric-agnostic** rather than byte-only.
- Page-count tests keep file byte size constant so page count is the isolated variable.
- Attachment-count tests are represented as separate per-turn scenarios.
- Canary evidence is phrased correctly: a hit proves end-to-end availability at that position; a miss does not identify the internal root cause by itself.
- Unbounded discovery no longer auto-doubles workloads; it requires an authoritative or user-approved safe cap.
- Added standard-library unit tests and CI.

## Typical prompts

| You ask | The skill does |
| --- | --- |
| “Validate the real maximum PDF upload size.” | Tests around the documented/suspected byte boundary and checks end-to-end content availability. |
| “How many pages are actually usable?” | Varies page count while keeping byte size constant. |
| “Test the attachment-count limit.” | Builds separate fixed-size attachment scenarios, each for its own fresh conversation. |
| “Compare direct upload and SharePoint.” | Keeps separate ledgers and compares the same metric/success criterion across paths. |
| “Where does this tool response start failing?” | Uses the generic numeric ledger/planner for a tool-specific active probe. |
| “Is Microsoft’s documented limit reproducible here?” | Records official guidance first, measures, then reconciles. |

## Built-in generated test packs

### File size

```bash
python scripts/build_test_pack.py --mode size --around 50MB \
  --format pdf --pages 60 --out-dir pack
```

The page count remains fixed while byte size changes.

### Page count

```bash
python scripts/build_test_pack.py --mode pages --sweep 50,100,250,500 \
  --format pdf --out-dir pack-pages
```

Every file is padded to the **same byte size**, so page count is the variable under test.

### Format comparison

Format has no ordering, so it cannot have a boundary. Run the same sweep once per format and compare the ledgers in one report:

```bash
python scripts/build_test_pack.py --mode size --around 50MB \
  --format docx --out-dir pack-docx
python scripts/generate_report.py --ledger pdf.json --ledger docx.json \
  --out report.md
```

### Attachment count

```bash
python scripts/build_test_pack.py --mode count --sweep 1,5,10,20 \
  --format pdf --size 32KB --out-dir pack-count
```

Each count is a separate scenario needing its own **fresh conversation**: attachments from an earlier turn can remain in context and inflate the count actually under test.

### Uploading

Artefacts land in `<out-dir>/upload/`. Upload them **one per turn**, and use a fresh conversation for the values that decide the boundary. Uploading the whole sweep at once varies per-file size, attachment count, and total turn payload simultaneously, so a failure cannot be attributed to any of them. Batch generation is the labour saving; batch uploading destroys the measurement.

In Copilot Studio, building into `/app/created/limits-validator/<run-id>/` puts the pack where the sandbox surfaces files back to the user. That directory is ephemeral, so capture ledgers and reports before the session ends.

## Canary design

Generated artefacts carry independent 96-bit random tokens at selected positions (early positions, quartiles, 90%, and the end).

The token exists **only inside the artefact**. `manifest.json` stores its SHA-256 digest, and verification hashes what the model claimed before comparing. Reading the manifest therefore cannot reveal an answer — a meaningful change, because the old design's correctness rested on an operator remembering not to open a file.

The model receives `probe-sheet.md`, which identifies **where** to probe but never reveals the expected tokens.

### Path integrity

A correct token proves the agent obtained that content by **some** route available to it. It is evidence about the *tested path* only if no other route existed.

This matters because the agent may have a Python-capable runtime. If it can open the PDF directly, unzip an Office package, or grep the filesystem, a correct token says nothing about ingestion, parsing, indexing, or retrieval — only that it found the string somehow.

So retrieve canaries only through the path under test, and record what was true:

| `--path-integrity` | Meaning |
| --- | --- |
| `attested` | no alternate route was available or used; coverage evidence applies to the tested path |
| `not-attested` | not verified; coverage shows only that the agent obtained the content somehow |
| `bypass-observed` | an alternate route was available or used; coverage evidence is void for this path |

Code cannot verify this. The report states which attestation was recorded and weakens its claims accordingly.

A missing token means availability was not demonstrated; it does **not** by itself prove whether parsing, indexing, retrieval, or context handling failed.

## Generic metric ledger

The same planner/reporting framework supports numeric metrics beyond bytes.

```bash
python scripts/record_result.py --ledger runtime.json --init \
  --capability "Tool execution duration" --path tool-input \
  --metric-name execution-duration --metric-unit milliseconds \
  --documented-value 120000 --documented-source "<official URL>" \
  --documented-checked-at 2026-08-31 \
  --scope platform="Copilot Studio" --scope region=<region> \
  --path-integrity attested

python scripts/record_result.py --ledger runtime.json \
  --subject "run-60000ms" --metric-value 60000 \
  --outcome pass --failure-stage none

python scripts/record_result.py --ledger runtime.json \
  --subject "run-90000ms" --metric-value 90000 \
  --outcome fail --failure-stage tool-invocation

python scripts/plan_boundary.py --ledger runtime.json
```

Tool/runtime tests are path-specific; the bundled file generator does not pretend to invoke your tool, API, flow, or production agent automatically.

## Evidence classes

| Label | Requires |
| --- | --- |
| **Official guidance + Measured** | a documented value, a source, and the date the source was read |
| **Documented value supplied + Measured** | a documented value without full attribution |
| **Measured** | no documented value recorded |

Reconciliation verdicts must be earned by evidence actually collected:

| Verdict | Requires |
| --- | --- |
| `confirmed-match` | the documented value tested directly and passed on repeated trials, with the nearest tested value above it failing on repeated trials |
| `consistent-with-guidance` | nothing contradicts the documented value, but the boundary is unresolved |
| `more-restrictive-than-documented` | a value at or below the documented boundary failed consistently |
| `observed-headroom` | a value strictly above the documented boundary passed |
| `no-published-limit` | no authoritative figure recorded |
| `inconclusive` | the evidence does not settle it — including when the documented value passed but nothing above it was tested |

Observed behaviour beyond a documented Microsoft boundary is **unsupported headroom**, not a new supported product limit.

## Safety

This is boundary validation, not load or stress testing.

- synthetic content only;
- test/non-production targets by default;
- announce artefact count and bytes before active testing;
- explicit direction required for production;
- no bypassing enforced limits;
- no concurrency/throttling/quota-exhaustion experiments;
- stop once the boundary is sufficiently established;
- unbounded discovery requires a safe cap.

See `references/safety-boundaries.md`.

## Repository layout

```text
copilot-studio-limits-validator/
├── SKILL.md
├── README.md
├── metadata.json
├── scripts/
│   ├── metrics.py
│   ├── make_test_file.py
│   ├── build_test_pack.py
│   ├── record_result.py
│   ├── plan_boundary.py
│   └── generate_report.py
├── references/
│   ├── documented-limits.md
│   ├── safety-boundaries.md
│   └── test-protocol.md
├── assets/
│   ├── ledger.schema.json
│   └── report-template.md
├── tests/
│   └── test_core.py
├── build_package.py
├── dist/
└── .github/workflows/test.yml
```

## Tests

```bash
python -m unittest discover -s tests -v
```

35 tests, no third-party Python packages. They cover canary independence and digest verification, exact-size generation, structural validity of all five formats, pack isolation, planner convergence, every reconciliation verdict, evidence gating, scope and path-integrity recording, schema conformance, and a build → record → plan → report round trip.

## Packaging

Build the uploadable skill package:

```bash
python build_package.py
```

This writes `dist/copilot-studio-limits-validator-skill-v<version>.zip` with `SKILL.md` at the **ZIP root** alongside `references/`, `scripts/` and `assets/`. The version comes from `metadata.json`, and the build refuses to produce a package whose front matter is malformed or which is missing a file `SKILL.md` references. `tests/`, `.github/` and `metadata.json` are excluded — the first two are development-only, and the third is the CAT submission manifest rather than part of the skill format.

Import it in Copilot Studio: **agent → Build → Skills → Add skill → Upload a skill**. Skills require an agent on the GitHub Copilot harness; the Skills panel does not appear otherwise.

Re-run the build after changing any skill file — the committed zip is a snapshot, not a live view.

The CAT submission folder should contain only the canonical skill material and its human-facing sidecars — `metadata.json`, `README.md`, `SKILL.md`, `scripts/`, `references/`, `assets/`. Keep `tests/` and `.github/` in the development repository; anything else in the submission is bundled into the agent unnecessarily.
