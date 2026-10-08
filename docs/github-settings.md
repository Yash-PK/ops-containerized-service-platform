# Proposed GitHub repository settings

Status: proposal only. No branch protection or ruleset has been enabled by this
document. Publication, exact-revision CI and repository settings must be verified
separately; local checks do not establish any of them.

After the public repository exists and its `validate` job has actually reported a
check on `main`, propose a repository-scoped rule that:

- Requires a pull request and the observed `validate` status check before merging.
- Blocks force pushes and branch deletion on `main`.
- Preserves a usable solo-maintainer path: do not require an unavailable second
  reviewer. Keep a narrowly assigned maintainer bypass for emergency repairs,
  with a recorded reason and follow-up PR/check results.

Confirm the exact check name from the real Actions run before configuring a
required status. An incorrectly named check can prevent every merge. Keep the
normal change path through tested pull requests; any bypass should be explicit
and reviewable. Applying these rules is a separate settings action, not part of
the application's local integration or release proof.

After publication, record the actual availability and enabled/disabled state of
repository secret scanning, push protection, private vulnerability reporting and
dependency vulnerability alerts. On 2026-10-08 all four were **verified enabled**
for this public repository: repository metadata returned secret-scanning and
push-protection `enabled`, reporting returned `enabled: true`, and the alert
endpoint returned HTTP 204. Only repository-scoped reporting/alert settings and
topics were changed; no ruleset or account setting was applied.
[GitHub documents free public-repository secret scanning](https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning).
Use only features available without adding a paid service, and make no
account-wide changes. Do not describe a proposed setting as an enforced control.
