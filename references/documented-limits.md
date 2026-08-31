# Finding documented limits

This repository intentionally does **not** hard-code current Copilot Studio limit values. Product limits change, can differ by feature/path, and may inherit constraints from Power Platform, connectors, Microsoft 365, or downstream services.

## Source hierarchy

Use, in order:

1. Microsoft Learn / official Copilot Studio quotas and limits.
2. The official Learn page for the specific feature or ingestion/tool path.
3. Official Power Platform / Power Automate / connector limits when the boundary is inherited.
4. Official licensing/consumption guidance when the apparent boundary is metering or throttling rather than rejection.
5. Product UI text as a **measured UI observation**, not as published documentation.

If no authoritative figure is found, record `no-published-limit`.

## Record the metric, not just a number

A documented limit must include:

- capability;
- path;
- metric name;
- numeric value;
- unit;
- exact source;
- date checked.

Examples of distinct metrics include file bytes, attachment count, pages, records, payload bytes, and execution duration. Do not collapse them into a generic “limit”.

## Unit traps

Microsoft pages may use MB without explicitly distinguishing decimal MB (1,000,000 bytes) from MiB (1,048,576 bytes). The scripts interpret `MB` as 1024² bytes for backward compatibility and print binary units as MiB/KiB. Use exact bytes when reconciling a boundary where the distinction matters.

## Supported vs observed

A value above a documented limit may sometimes work. That is unsupported headroom, not a supported capability. Report it as `more-permissive-than-documented` and keep the published limit as the design boundary unless Microsoft changes its guidance.
