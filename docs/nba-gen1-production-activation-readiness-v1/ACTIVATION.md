# NBA Gen1 activation

Current status: **BLOCKED_NOT_INSTALLED**. Read [the activation closeout](../nba-gen1-producer-activation-v1/CLAUDE_HANDOFF.md) for the exact supported Install/Verify/Remove commands, successful six-test rerun, Administrator-consent blocker, and corrected full-slate limitations. The original command-only handoff below is historical; it does not establish opening-night readiness.

This release is staged but inactive. It requires one explicit producer activation authorization. Use the exact immutable commands and pins in:

`C:\Users\james\asp-model-exchange\nba-gen1-production-v1\activation-readiness\sha256\a2c828a1c2692571495fba8e3c072d66491c12a58f9a02ae10903ce1a9024b63\ACTIVATION.md`

The installer must leave one `ASP NBA Forecast Publisher` task with S4U, Limited and IgnoreNew, then the next natural invocation must be checked. AISP activation is a separate Claude-owned action using the two exact pins in that file. The removal command deletes only this new task and runtime binding; it preserves the deployment, forecast and receipts.
