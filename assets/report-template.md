# Verified Limits Report

Generated <timestamp> by `copilot-studio-limits-validator` v<version>.

Every measured value is scoped to the environment and conditions in which it was observed. Product updates, tenant configuration, region, licence, harness, ingestion path, and downstream dependencies can change the result.

## <Capability>

**Path:** `<path>`  
**Metric:** <metric name> (<unit>)  
**Documented limit:** <value + official source, or none identified>  
**Largest verified usable value:** <value>  
**First consistent failing value:** <value>  
**Largest explicitly accepted value:** <value>  
**Observed failure stage:** <stage or Not determined>  
**Evidence:** <Official guidance + Measured | Measured>  
**Reconciliation:** `<match | more-restrictive-than-documented | more-permissive-than-documented | no-published-limit | inconclusive>`

### Result

One concise paragraph stating what the test established and what it means for design decisions.

> **Boundary status:** Include when the planner has not converged. Do not publish an exact boundary from inconsistent, non-monotonic, single-trial, or unbounded evidence.

### Test record

| Subject | Test value | Format | Bytes | Pages | Accept | Retrieve | Coverage | Trial | Outcome | Failure stage |
| --- | ---: | --- | ---: | ---: | --- | --- | --- | ---: | --- | --- |
| `<subject>` | <metric value> | <format> | <bytes> | <pages> | Pass | Pass | Pass (n/n) | 1 | **pass** | None |

### Positions not demonstrated end-to-end

List only when canary claims were missing or mismatched.

A missing canary means the expected token was not reproduced for that position. It does **not** by itself prove whether parsing, indexing, retrieval, or context handling caused the failure.

## Path comparison

Use only when the ledgers measure the same metric and success criterion.

| Path | Capability | Metric | Largest usable | First fail | Failure stage | Evidence |
| --- | --- | --- | ---: | ---: | --- | --- |
