# Test protocol

The methodology this skill implements. The short version: **an accepted input
is not a working input**, and **a model saying it read something is not
evidence that it did**.

## 1. Name the capability *and* the ingestion path

Copilot Studio has no single universal file limit. Different subsystems
enforce different boundaries, so a result is meaningless without the path
attached. Test and report one path at a time:

| Path key | What it covers |
| --- | --- |
| `direct-upload` | A file the user attaches in the conversation |
| `agent-knowledge` | A file uploaded as agent knowledge at design time |
| `sharepoint` | A file reached through a SharePoint knowledge source |
| `sharepoint-library` | A whole library or folder as a source |
| `onedrive` | A file reached through OneDrive |
| `tool-input` | A file or payload passed *into* a tool/action |
| `tool-output` | A payload returned *by* a tool/action |
| `generated-output` | A file the agent produces and hands back |
| `runtime` | Execution duration, temp storage, subprocess behaviour |

Never generalise a measurement from one path to another. Use the comparison
table in the report instead -- the *differences between paths* are usually the
most valuable finding.

## 2. Record the documented limit before testing

Look up published guidance first and record it with its source URL, so the
report can reconcile measured against documented. If no authoritative figure
exists, say so explicitly -- `no-published-limit` is a legitimate and useful
result. See `documented-limits.md`.

Recording it first also protects against the obvious bias: it is much easier
to "confirm" a number you already believe once you have seen the results.

## 3. Generate the whole sweep before testing any of it

Build every artefact in one run with `build_test_pack.py`. The agent cannot
upload files to itself, so every ingestion test needs a human. Batching turns
N round trips into one, which is the difference between a test that gets
finished and one that does not.

Sizes bracket the suspected limit: well below, just below, at, just above,
well above. Keep every other variable constant -- same format, same page
count, same content shape -- so the only thing varying is the thing being
measured.

## 4. Walk the full lifecycle, not just the first stage

Record each stage separately:

| Stage | Question | Who can observe it |
| --- | --- | --- |
| `accepted` | Did the client/API take the file at all? | **The human.** The agent never sees a rejected upload. |
| `transferred` | Can the agent see the artefact? | The agent |
| `processed` | Did parsing/extraction/indexing complete? | The agent |
| `retrievable` | Can *any* content be read back? | The agent |
| `coverage` | Can content be read from **every** probed position? | The agent, via canaries |

The gap between `accepted` and `coverage` is where the expensive failures
live: the platform takes a 50 MB file, reports no error, and quietly gives the
model the first few pages. Nothing surfaces that except position-addressed
probing.

## 5. Probe canaries without seeing the answers

Every generated artefact carries unguessable tokens at known page positions.

1. Read `probe-sheet.md` -- it lists the positions and **withholds the tokens**.
2. Do **not** open `manifest.json` first. It contains the expected tokens, and
   an agent that has seen them can report them back without ever opening the
   document. That is not a measurement; it is an echo.
3. Ask for the exact token at each position, one artefact at a time.
4. Pass what was actually reported to
   `record_result.py --canaries-claimed "1=<token>,5=<token>,..."`.

The script compares each claim against the manifest. A token that does not
match verbatim is scored as **not found** and flagged as fabricated. Because
the tokens are random, a correct answer cannot be produced by guessing -- so a
hit is real evidence the page was parsed, and a miss is real evidence it was
not.

## 6. Converge deliberately

Run `plan_boundary.py` after each round. It bisects between the largest pass
and the smallest fail, and it refuses to converge when the evidence is not
clean:

* **Non-monotonic** -- something larger passed while something smaller failed.
  Size is not the governing variable. Suspect a timeout, a throttle, a
  page-count or complexity limit, or a transient failure.
* **Inconsistent** -- the same size both passed and failed across trials. That
  is intermittency, not a limit.

In both cases the correct action is repeat trials, not a conclusion.

## 7. Repeat before publishing

A single failure can be a transient service condition. Boundary sizes need at
least two consistent trials before they are reported as a boundary. The
planner tracks this and will tell you when the boundary is thinly evidenced.

## 8. Classify the evidence honestly

| Class | Meaning |
| --- | --- |
| `Official guidance + Measured` | A published limit exists and was tested |
| `Measured` | Observed here; no published limit was found |

And reconcile:

| Verdict | Meaning |
| --- | --- |
| `match` | Measured behaviour reproduces the documented limit |
| `more-restrictive-than-documented` | Reliable processing stopped below the documented figure -- design to the measured value |
| `more-permissive-than-documented` | Larger inputs worked, but **this is not supported capability** and can be withdrawn without notice |
| `no-published-limit` | Measured only; must not be quoted as a product limit |
| `inconclusive` | Nothing passed every stage |

## 9. State the scope of the result

Every measurement is scoped to the tenant, environment, licence, harness,
region and date it was taken in, and any service update can change it. The
report says this at the top; do not strip it when quoting figures. A number
without its scope is how a measurement becomes a myth.
