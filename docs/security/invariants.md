# WebFA Security Invariants

These rules are non-negotiable. Any violation is a Phase-blocking failure.

## Approval Binding

1. **No execute without preview.** Plan must pass through preview (policy check + diff generation) before execution is possible.
2. **No execute without approval.** Execution requires an approved approval with valid token.
3. **Approval binds plan_hash.** If plan content changes after approval, execution must fail with plan_hash mismatch.
4. **Approval binds diff_hash.** If diff changes after approval, execution must fail with diff_hash mismatch.
5. **Approval has expiry.** Expired approvals cannot be used for execution.
6. **Approval token not reusable across plans.** Token A for plan A cannot execute plan B.
7. **Rejected approval cannot be re-approved.** Once rejected, approval is terminal.
8. **plan_hash recomputed on execute.** The executor must recompute plan_hash from current DB fields and compare against stored hash. Do NOT compare stored hash against caller-provided hash.

## Policy Enforcement

9. **Blocked paths are backend-enforced.** Policy check happens in the Runtime service layer, not in the UI.
10. **File count limit enforced.** Changed files > 5 → blocked.
11. **Diff line limit enforced.** Diff > 800 lines → blocked.
12. **High-risk transactions require approval.** Risk level medium/high/critical → approval_required=true.

## Token Security

13. **Agent never sees tokens.** approval_token only returned once in the approve response.
14. **Token stored as hash only.** DB stores sha256(token), never plaintext.
15. **Token not in logs.** Logs must redact token, authorization, credential, secret, private_key.
16. **Token not in audit.** Audit payloads must not contain token or token_hash.
17. **Token not in proof.** Proof bundles must not contain token.

## Proof Integrity

18. **Verified execution must have proof.** execution.status=verified implies proof exists.
19. **Proof binds execution.** proof.execution_id must reference a real execution.
20. **Proof contains verification.** proof.verification.passed and proof.verification.checks must be present.
21. **Proof hash is recomputable.** proof.hash must be verifiable by recomputing from canonical proof payload.
22. **Proof DB and file consistent.** SQLite proof_json and proofs/ file must match.

## Audit Completeness

23. **Audit records full chain.** Minimum events: plan.created, plan.previewed, policy.checked, approval.created, approval.approved, execution.created, execution.started, execution.step.succeeded, execution.verifying, execution.verified, proof.created.
24. **Audit records failures.** Policy blocks, execution failures, and verification failures must be audited.
25. **Audit timestamps ordered.** Events must be chronologically correct.

## Architecture Boundary

26. **Electron does not contain business logic.** Electron main process: spawn/stop runtime, window, tray, IPC status only.
27. **Runtime is the business core.** All plan/policy/approval/execution/verification/proof/audit logic lives in Python Runtime.
28. **MCP is protocol adapter only.** MCP server does not write DB, does not generate hashes, does not bypass approval.

## Taint Tracking

29. **External content is tainted.** GitHub issue body, comments, README; HF model card, README, discussion.
30. **Tainted content cannot:** expand permissions, modify target repo, skip approval, modify blocked paths, cross provider write, change credential scope.
