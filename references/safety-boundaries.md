# Safety boundaries

This skill probes a **live product**, frequently in a customer tenant, often
on metered consumption. It is a validation tool, not a stress-testing tool.
Safety is enforced at both the instruction layer (`SKILL.md`) and the script
layer.

## The distinction that matters

**Validation** establishes where a capability stops working, using the
smallest number of controlled inputs that answer the question.

**Stress testing** tries to make a service fail through volume, concurrency
or resource exhaustion.

They can look similar from the outside, and only one of them is acceptable
here. If a test's purpose is to find out how much the service will take
before it breaks, rather than where the supported boundary sits, stop.

## Probe safety levels

### Passive -- may run by default

- Generating test artefacts locally.
- Reading a manifest, ledger, or previously recorded results.
- Planning the next size to test.
- Rendering reports.

Nothing in this tier touches the tenant. The generator is pure local file I/O.

### Active-safe -- run only after telling the user what will happen

- Uploading a small number of controlled artefacts to a **test** agent.
- Asking the agent to read canary tokens from those artefacts.
- Reading a file through a configured SharePoint/OneDrive knowledge source.
- Invoking a tool with a controlled payload against a **non-production** target.

Announce the artefact count and total size before the user uploads. Consumption
is metered and large sweeps are not free.

### Active-sensitive -- require explicit, specific user direction every time

- Testing against a **production** agent, or any agent real users are using.
- Invoking tools that write, create, delete, or notify anyone.
- Any test whose failure mode is a real record being created (tickets, orders,
  emails, approvals). Duplicate-request testing is the classic example -- you
  can only discover a duplication bug by causing one.
- Uploading to a tenant the user does not own or administer.

The shipped scripts perform **none** of these. They generate local files and
process local JSON. Every tenant interaction is performed by the agent under
the user's direction, which is exactly where the consent gate belongs.

## Hard limits

**Never**:

- Attempt to bypass, spoof, or work around a platform-enforced limit. Observing
  that 51 MB is rejected is the finding; defeating the check is not.
- Run concurrent or repeated requests to induce throttling, quota exhaustion or
  denial of service. If throttling appears, that is an observation to record
  and back off from -- not a target to pursue.
- Continue sweeping once the boundary is established. Stop at convergence.
- Test against production without explicit, specific instruction.
- Generate artefacts far beyond the plausible boundary "to see what happens".
  The sweep brackets the limit; it does not explore the whole number line.

## Cost and consumption

Every uploaded artefact consumes messages/credits, and large files consume
more. Before any sweep, tell the user the file count and total bytes. Prefer
the smallest artefact that still exercises the variable: page-count tests do
not need large files, and attachment-count tests should use small ones.

## Data handling

Generated artefacts contain **only** synthetic content -- deterministic filler
text and random canary tokens. They never contain customer data, and no test
should ever be run using a real customer document as the payload. If a real
document is needed to reproduce a specific behaviour, that is a support case,
not a sweep.

Ledgers and reports record sizes, stages and tokens. They must not record
tenant identifiers, environment IDs, user identities, connection details or
file contents.

## Failure handling

A probe that could not observe something records `unknown`, `unverified` or
`not-tested` -- **never** `unsupported`. A capability is not absent because a
test was skipped, and the difference between "it failed" and "we did not look"
is the whole credibility of the report.
