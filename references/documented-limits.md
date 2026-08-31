# Documented limits

This file deliberately contains **no hard-coded limit values**.

Published Copilot Studio limits change with service updates, and they differ by
licence, environment type, harness and region. A number pasted into a skill
bundle is stale the moment the product ships an update, and a stale number in a
tool that claims to measure reality is worse than no number at all -- people
quote it.

So this is a method for finding the current documented figure, and a template
for recording what you found, with its source and the date you read it.

## Where to look, in order of authority

1. **Microsoft Learn -- Copilot Studio quotas and limits.** The canonical
   reference for per-agent and per-tenant figures. Start at
   <https://learn.microsoft.com/microsoft-copilot-studio/> and search for
   "quotas and limits", "file", "attachment" or the specific capability.
2. **The feature's own Learn page.** Knowledge sources, file upload, tools and
   generative answers each document their own constraints, and these are often
   more specific than the central quota page.
3. **Power Platform limits.** Some boundaries are inherited from the underlying
   platform (connector timeouts, Dataverse row limits, flow run duration)
   rather than set by Copilot Studio.
4. **Licensing and consumption documentation.** Some apparent "limits" are
   really metering thresholds, which behave differently -- you get throttled,
   not rejected.
5. **The product UI.** Error text and helper text in Copilot Studio sometimes
   state a figure that documentation does not. Record it as a UI observation,
   not as published guidance.

If you find nothing authoritative, record `no-published-limit`. That is a
genuine, reportable result -- and it makes the measurement more valuable, not
less.

## What to record

Capture all four fields. A number without a source and a date cannot be
reconciled later.

```
python record_result.py --ledger run.json --init \
    --capability "Direct file upload - PDF" \
    --path direct-upload \
    --documented 50MB \
    --documented-source "https://learn.microsoft.com/<exact-page>"
```

## Registry template

Keep a copy of this table per engagement. Fill it in as you go; leave cells
blank rather than guessing.

| Capability | Path | Documented value | Source URL | Date read | Notes |
| --- | --- | --- | --- | --- | --- |
| File size -- PDF | `direct-upload` | | | | |
| File size -- DOCX | `direct-upload` | | | | |
| File size -- knowledge upload | `agent-knowledge` | | | | |
| File size -- SharePoint source | `sharepoint` | | | | |
| Attachment count per turn | `direct-upload` | | | | |
| Page count parsed | `direct-upload` | | | | |
| Supported file formats | `direct-upload` | | | | |
| Tool request payload size | `tool-input` | | | | |
| Tool response payload size | `tool-output` | | | | |
| Tool / connector timeout | `tool-input` | | | | |
| Generated file size | `generated-output` | | | | |

## Traps worth knowing about

**MB is ambiguous.** Documentation is rarely explicit about whether MB means
10^6 or 2^20 bytes -- a 4.9% difference, which is more than enough to
misidentify a boundary. This skill's tooling treats `MB` as 1024x1024 and
offers `--size-bytes` for an unambiguous count. When a measured boundary lands
suspiciously close to a documented figure, check whether the discrepancy is
exactly the binary/decimal gap before reporting a mismatch.

**"Supported" and "enforced" are different.** A documented limit describes what
Microsoft supports. It is not a promise that the platform rejects everything
above it. Inputs beyond the documented figure sometimes work -- that is
unsupported headroom, not capability, and it can disappear in any update. The
report classifies this as `more-permissive-than-documented` and says so
explicitly.

**A limit can be enforced in more than one place.** The client may block at one
size while ingestion blocks at another and the parser degrades at a third. This
is why the ledger records a failure *stage* rather than just a failure.

**Per-file and per-turn limits are different limits.** Ten files of 5 MB is not
the same test as one file of 50 MB, and they commonly have different answers.

**Metering is not rejection.** If large or frequent inputs slow down rather
than fail, you are observing throttling. Record it as such and back off; do not
keep pushing to find the breaking point.
