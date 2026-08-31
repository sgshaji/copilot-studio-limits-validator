# Verified Limits Report

<!--
Reference shape for the output of generate_report.py. The generator produces
this automatically; this file documents the contract so the format can be
reviewed, diffed, or reproduced by hand.

Rules that matter:
  * Lead with the USABLE boundary, not the acceptance boundary.
  * Always name the failure stage.
  * Never round a measured figure toward the documented one.
  * Never invent a percentage, score, or confidence number.
  * Keep the scope caveat. A figure without scope and date becomes a myth.
-->

Generated <timestamp> by `copilot-studio-limits-validator` v<version>.

Every figure below is an observation from **this environment**. Limits can
differ by tenant, environment, licence, harness and region, and can change with
any service update. Re-measure before relying on these numbers elsewhere.

## <Capability name>

**Ingestion path:** `<direct-upload | sharepoint | tool-input | ...>`
**Documented limit:** <value + source link, or "none identified">
**Observed input acceptance:** up to <value>
**Observed complete processing:** up to <value>
**First consistent failure:** <value, or "none observed">
**Failure stage:** <Client validation | Parsing | Ingestion | ...>
**Evidence:** <Official guidance + Measured | Measured>
**Reconciliation:** `<match | more-restrictive-than-documented | more-permissive-than-documented | no-published-limit | inconclusive>`

> **Acceptance exceeds usability.** Included only when the two boundaries
> differ. Between them the platform takes the file and silently returns
> incomplete content -- the most expensive failure mode, because nothing
> reports an error.

### Result

One paragraph. What was measured, what it means for design decisions, and --
when behaviour is more permissive than documented -- an explicit statement that
unsupported headroom is not capability and can be withdrawn without notice.

> **Boundary not yet settled.** Included when the planner has not converged.
> Carries the reason (`bisect`, `non-monotonic`, `inconsistent`,
> `no-upper-bound`, `no-lower-bound`) and the next action.

### Test record

| Artefact | Size | Pages | Accept | Process | Retrieve | Coverage | Trial | Outcome |
| --- | ---: | ---: | --- | --- | --- | --- | ---: | --- |
| `<file>` | <size> | <n> | Pass | Pass | Pass | Pass (10/10) | 1 | **pass** |
| `<file>` | <size> | <n> | Pass | Pass | Pass | Partial (5/10) | 1 | **partial** |
| `<file>` | <size> | <n> | Fail | - | - | - | 1 | **fail** |

`-` means not observed, never "unsupported". A stage is never failed because
nobody looked.

### Unparsed pages

Canary tokens that could not be retrieved. Because the tokens are random, a
miss is positive evidence the page was never parsed -- not a retrieval
preference.

- `<file>` -- pages <list>

## Path comparison

Included when more than one ledger is rendered. Copilot Studio has no single
universal file limit; the differences between paths are usually the most
valuable finding.

| Path | Capability | Accepted to | Fully usable to | Failure stage | Evidence |
| --- | --- | ---: | ---: | --- | --- |
| `direct-upload` | <capability> | <value> | <value> | <stage> | <class> |
| `sharepoint` | <capability> | <value> | <value> | <stage> | <class> |
