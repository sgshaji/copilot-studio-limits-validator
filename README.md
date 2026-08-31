# Copilot Studio Limits Validator

Measure where a specific Copilot Studio capability stops working reliably, instead of treating a documented number or a successful upload as proof of end-to-end capability.

The skill is designed for **quantitative, bounded validation**: file size, page count, attachment count, tool payload size, record count, generated-output size, execution duration, and similar numeric boundaries.

> **Harness Explorer discovers what exists. Limits Validator measures how far a specific capability reliably works.**

## Why this exists

Three mistakes make platform limits easy to misstate:

1. **Accepted is not usable.** A file can be accepted while only part of its content is available later.
2. **Documentation is not a runtime measurement.** Published limits are the supported contract; environment behaviour still needs scoped validation when accuracy matters.
3. **A failed content probe is not automatically a parsing failure.** The cause may be parsing, indexing, retrieval, context handling, or another stage. The skill reports only the failure stage directly supported by evidence.

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
| “Test the attachment-count limit.” | Builds separate fixed-size attachment scenarios for independent turns. |
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

```bash
python scripts/build_test_pack.py --mode formats --size 10MB \
  --pages 40 --out-dir pack-formats
```

### Attachment count

```bash
python scripts/build_test_pack.py --mode count --sweep 1,5,10,20 \
  --format pdf --size 32KB --out-dir pack-count
```

Each count is a separate scenario and must be uploaded in a separate conversation turn. Mixing counts in one turn invalidates the count measurement.

## Canary design

Generated artefacts carry independent random tokens at selected positions (early positions, quartiles, 90%, and the end).

The model receives `probe-sheet.md`, which identifies **where** to probe but never reveals the expected tokens. `manifest.json` contains the secrets and must remain hidden until after the model has returned its claims.

A correct token is strong evidence that content at that position was available end-to-end during the probe. A missing token means availability was not demonstrated; it does **not** by itself prove whether parsing, indexing, retrieval, or context handling failed.

## Generic metric ledger

The same planner/reporting framework supports numeric metrics beyond bytes.

```bash
python scripts/record_result.py --ledger runtime.json --init \
  --capability "Tool execution duration" --path tool-input \
  --metric-name execution-duration --metric-unit milliseconds \
  --documented-value 120000 --documented-source "<official URL>"

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

External reports use only:

- **Official guidance + Measured**
- **Measured**

Reconciliation outcomes are:

- `match`
- `more-restrictive-than-documented`
- `more-permissive-than-documented`
- `no-published-limit`
- `inconclusive`

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
└── .github/workflows/test.yml
```

## Tests

```bash
python -m unittest discover -s tests -v
```

No third-party Python packages are required.
