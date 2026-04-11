<!-- Thanks for contributing! Please keep the checklist intact and fill out the sections below. -->

## What does this PR do?

<!-- A concise description of the change. One or two sentences is usually enough. -->

## Why?

<!-- The problem or use case this solves. Link to an issue if there is one: Fixes #123 -->

## How did you test it?

<!--
Because the tool touches real external APIs, testing is usually manual.
Describe what you ran, against what kind of account (real org vs. throwaway),
and what you observed. Include redacted output if useful.
-->

- [ ] I ran the affected commands against a throwaway / test Qonto client
- [ ] I verified pre-mutation summaries still render correctly
- [ ] I did NOT bypass any typed-confirmation or `y/N` gate

## Type of change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing behavior to change)
- [ ] Documentation only

## Safety checklist (required for changes touching the write path)

- [ ] No new code path writes to Qonto or Gmail without an explicit confirmation gate
- [ ] `gmail.modify` scope remains the only Gmail scope requested (no `gmail.send`, no `gmail.compose`)
- [ ] `finalize` still requires typed confirmation of the invoice number
- [ ] No secrets, API keys, OAuth tokens, or real client data are present in the diff
