---
name: Reproducible lab failure
about: Report a controller or owned-lab failure with redacted evidence
title: ""
labels: ""
assignees: ""
---

## Revision and environment

Commit, controller OS/architecture/Python version, selected profile and available
resources. Do not include your environment dump, credentials or private paths.

## Reproduction

Exact documented command, synthetic input and expected behavior.

## Observed result

Exit code, failed assertion and a reviewed log extract or public evidence link.
Distinguish a controller fixture from real VM/container execution.

## Cleanup state

Was the owned VM/project removed? Is inventory retained? Do not use broad cleanup
commands to hide the original failure.

For a security issue, follow SECURITY.md instead of publishing sensitive details.
