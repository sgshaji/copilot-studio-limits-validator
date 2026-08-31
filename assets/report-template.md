# Verified Limits Report

Generated <timestamp> by `copilot-studio-limits-validator` v<version>.

Every measured value is scoped to the environment and conditions in which it was observed. Product updates, tenant configuration, region, licence, harness, ingestion path, and downstream dependencies can change the result.

A verdict describes only what was actually tested. `confirmed-match` requires the documented value to have been tested directly and repeated; `consistent-with-guidance` means nothing contradicted it; `inconclusive` means the evidence does not settle the question either way.

## <Capability>

**Path:** `<path>`  
**Metric:** <metric name> (<unit>)  
**Documented limit:** <value + official source, or none identified>  
**Scope:** <platform; harness; environment; region; channel; model; licence; date, or "not recorded">  
**Path integrity:** `<attested | not-attested | bypass-observed>`  
**Largest verified usable value:** <value>  
**First consistent failing value:** <value>  
**Largest explicitly accepted value:** <value>  
**Observed failure stage:** <stage or Not determined>  
**Evidence:** <Official guidance + Measured | Documented value supplied + Measured | Measured>  
**Reconciliation:** `<confirmed-match | consistent-with-guidance | more-restrictive-than-documented | observed-headroom | no-published-limit | inconclusive>`

`Official guidance + Measured` requires a documented value, a source, and the date the source was read. Without all three the evidence is `Documented value supplied + Measured`.

### Result

One concise paragraph stating what the test established and what it means for design decisions.

> **Boundary status:** Include when the planner has not converged. Do not publish an exact boundary from inconsistent, non-monotonic, single-trial, or unbounded evidence.

> **Path integrity:** Always include. A correct canary proves the agent obtained the content by some available route; it is evidence about the tested path only when path integrity is attested.

> **Scope:** Include when scope was not recorded. A boundary with no tenant, region, licence, harness, or date cannot be compared with anything.

### Test record

| Subject | Test value | Format | Bytes | Pages | Accept | Retrieve | Coverage | Trial | Outcome | Failure stage |
| --- | ---: | --- | ---: | ---: | --- | --- | --- | ---: | --- | --- |
| `<subject>` | <metric value> | <format> | <bytes> | <pages> | Pass | Pass | Pass (n/n) | 1 | **pass** | None |

### Positions not demonstrated end-to-end

List only when canary claims were missing or mismatched.

A missing canary means the expected token was not reproduced for that position. It does **not** by itself prove whether parsing, indexing, retrieval, or context handling caused the failure.

Claims are verified by comparing the SHA-256 digest of the claimed token with the digest stored in the manifest. The token itself exists only inside the artefact.

## Path comparison

Use only when the ledgers measure the same metric and success criterion.

| Path | Capability | Metric | Largest usable | First fail | Failure stage | Evidence |
| --- | --- | --- | ---: | ---: | --- | --- |
