---
name: Bug report
about: Report something that's broken or behaving unexpectedly
title: ''
labels: bug
assignees: ''
---

## Description

<!-- A clear and concise description of what the bug is. -->

## To Reproduce

1. Run `invoicer ...`
2. ...
3. See error

## Expected behavior

<!-- What you expected to happen. -->

## Actual behavior

<!-- What actually happened. Include the full error message if any. -->

## Environment

- `invoicer` version: <!-- `invoicer --version` or commit hash -->
- Python version: <!-- `python --version` -->
- OS: <!-- macOS / Linux / Windows + version -->
- Installed via: <!-- uv tool install / pip install -e / git clone -->

## Config sketch (REDACTED)

<!--
If relevant, share a sketch of your invoicer.yaml WITH ALL IDS, API KEYS,
and real client data REMOVED. Never paste real secrets or client data.
-->

```yaml
clients:
  - clockify_id: "<redacted>"
    qonto_id: "<redacted>"
projects:
  "<redacted>":
    alias: "my-project"
    rate_eur_per_hour: 85
    ...
```

## Additional context

<!-- Anything else that might help us reproduce or fix this. -->
