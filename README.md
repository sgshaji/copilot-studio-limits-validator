# Copilot Studio Limits Validator

Find out where a Copilot Studio capability **actually** stops working -- by
measuring it, not by reading the documentation and hoping.

Documentation tells you a limit is 50 MB. It does not tell you whether a 50 MB
file is genuinely usable once it arrives, which stage rejects a 51 MB one, or
whether SharePoint enforces the same boundary as direct upload. This skill
answers those questions with controlled experiments and writes up the result
with its evidence.

## The problem it solves

Two failures make quantitative limits genuinely hard to reason about.

**"It uploaded" is not "it works."** A file can be accepted, transferred, and
parsed, and still only be half readable. Nothing raises an error -- the agent
simply answers using the first few pages and sounds perfectly confident. This
is the most expensive failure mode in document-processing agents, because it
passes review and ships.

**Asking the model is not measuring.** "Can you read the end of this document?"
will get you a plausible yes. Models produce plausible content on demand; that
is what they are for. So the skill does not ask.

## How it works

Generated artefacts carry **unguessable canary tokens** at known page
positions -- page 1, the early pages, quartiles, and the last page. To prove a
page was parsed, the agent must reproduce that page's exact token. A random
token cannot be guessed, so:

- a **hit** is real evidence the page was parsed;
- a **miss** is real evidence it was not;
- an **invented token** is caught by verbatim comparison and scored as *not
  found*, then flagged as fabricated.

The agent is given a `probe-sheet.md` listing the positions with the tokens
**withheld**, so it cannot echo answers it has already seen.

## Batched, because the agent cannot upload to itself

A skill runs inside the agent, but file upload happens before the agent is
invoked. A naive binary search would need a human round trip per probe -- build
a 52 MB file, upload, wait, then 51 MB, upload, wait. Nobody finishes that.

So the whole sweep is generated up front and handed over **once**. Forty round
trips become one.

## Step-by-step in Copilot Studio

1. **Add this skill** -- in the Build tab, add the `copilot-studio-limits-validator`
   folder with its `SKILL.md`, `scripts/`, `references/` and `assets/`.
2. **Ask for a validation** in the Preview tab, e.g. *"validate the real maximum
   PDF upload size"*.
3. **Upload the pack** the agent generates, in a single turn, and tell it about
   anything the client rejected before sending -- that is a
   `client-validation` failure the agent can never see for itself.
4. **Read the report.**

## Talk to the agent

| You say | The skill does |
| --- | --- |
| "Validate the real maximum PDF upload size." | Frames the path, records the documented figure, builds a bracketing sweep, probes canaries, reports the boundary and the failure stage. |
| "How many pages actually get parsed?" | Builds a page-count sweep and finds where canary retrieval stops. |
| "Test the attachment limit." | Builds N small artefacts with per-file tokens so each one is individually attributable. |
| "Do SharePoint and direct upload have the same limit?" | Keeps a ledger per path and renders a comparison table. |
| "Compare how the formats behave at 10 MB." | Builds one artefact per format at a fixed size. |
| "Is that boundary trustworthy yet?" | Reports convergence status and asks for repeat trials when evidence is thin. |

## Safety at a glance

- **Generation is entirely local.** The scripts write files and read JSON. They
  never touch a tenant.
- **Tenant interaction is agent-driven and announced.** Artefact count and total
  bytes are stated before any upload, because consumption is metered.
- **Production is opt-in and explicit.** Nothing runs against a live agent
  without specific direction.
- **This is validation, not stress testing.** Never bypasses an enforced limit,
  never pursues throttling or resource exhaustion, and stops at convergence.
- **Synthetic content only.** Artefacts contain deterministic filler and random
  tokens. Never test with real customer documents.

See `references/safety-boundaries.md`.

## Running the scripts directly

Python 3.8+ (developed on 3.13). No third-party dependencies.

```bash
cd scripts

# 1. Build a sweep bracketing a suspected 50 MB limit
python build_test_pack.py --mode size --around 50MB --format pdf --pages 60 \
    --out-dir pack

# other modes
python build_test_pack.py --mode pages   --sweep 10,50,100,250 --format pdf --out-dir pack
python build_test_pack.py --mode formats --size 10MB --out-dir pack
python build_test_pack.py --mode count   --count 20 --format pdf --out-dir pack

# 2. Open a ledger for one capability on one ingestion path
python record_result.py --ledger run.json --init \
    --capability "Direct file upload - PDF" --path direct-upload \
    --documented 50MB --documented-source "https://learn.microsoft.com/..."

# 3. Record each artefact, verifying the tokens the agent reported
python record_result.py --ledger run.json --manifest pack/manifest.json \
    --file pdf-50MB.pdf --canaries-claimed "1=CANARY-...,5=CANARY-..."

python record_result.py --ledger run.json --manifest pack/manifest.json \
    --file pdf-51MB.pdf --accepted fail --failure-stage client-validation

# 4. Decide what to test next -- or whether the boundary is settled
python plan_boundary.py --ledger run.json

# 5. Render the report (repeat --ledger for a cross-path comparison)
python generate_report.py --ledger run.json --out report.md
```

A single artefact can also be generated on its own:

```bash
python make_test_file.py --format pdf --size 49MB --pages 100 \
    --out t.pdf --manifest t.json
```

## What the report contains

- The **acceptance** boundary and the **usable** boundary, separately -- and an
  explicit warning when they differ.
- The **stage** at which processing failed, from client validation through to
  generated output.
- A per-artefact table with every lifecycle stage and canary hit rate.
- Any **unparsed pages**, listed by number.
- A **reconciliation verdict** against published guidance: `match`,
  `more-restrictive-than-documented`, `more-permissive-than-documented`, or
  `no-published-limit`.
- A scope caveat, because a figure without its scope and date is a myth.

## What this skill is not

- **Not a runtime inventory.** It does not enumerate Python libraries, tools or
  MCP servers -- use `agent-harness-explorer` for that. *Harness Explorer
  discovers what exists; this measures how far it reliably works.*
- **Not an answer-quality evaluator.** It does not judge whether the agent
  responds well.
- **Not a documentation summariser.** Published figures are the hypothesis, not
  the result.
- **Not a load-testing tool.** See the safety boundaries.

## Folder layout

```
copilot-studio-limits-validator/
├── SKILL.md                    # agent trigger + workflow
├── metadata.json               # gallery catalog sidecar
├── README.md                   # this file
├── scripts/                    # standard-library-only Python
│   ├── make_test_file.py       # exact-size artefacts carrying canary tokens
│   ├── build_test_pack.py      # batched sweeps + upload/probe instructions
│   ├── record_result.py        # stage-by-stage ledger, verbatim verification
│   ├── plan_boundary.py        # bisection + intermittency guards
│   └── generate_report.py      # Verified Limits Report
├── references/
│   ├── test-protocol.md        # the methodology
│   ├── safety-boundaries.md    # what may run, and what must never
│   └── documented-limits.md    # finding and citing published figures
└── assets/
    ├── ledger.schema.json
    └── report-template.md
```

## Extending it

**Add a format** by writing a `build_<fmt>(pages, run_id, pad_len) -> bytes`
builder in `make_test_file.py` and registering it in `_BUILDERS`. It must place
canary text at page positions and accept incompressible padding so the exact
size solver can hit its target.

**Add an ingestion path** by adding a key to the `path` enum in
`assets/ledger.schema.json` and a row to the table in
`references/test-protocol.md`.

**Add a failure stage** by extending `FAILURE_STAGES` in `record_result.py` and
`_STAGE_LABEL` in `generate_report.py`.
