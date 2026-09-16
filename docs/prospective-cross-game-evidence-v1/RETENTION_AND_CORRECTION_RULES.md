# Retention and correction rules

1. Retain physical forecast packages unchanged under their existing identities.
2. Store each pre-outcome envelope as a new content-addressed sidecar bound to the package hash.
3. Never fill missing downstream timestamps by inference. Later discovery or acknowledgement uses an availability receipt.
4. Append forecast revisions. A successor must bind the exact preceding forecast, package and evidence identity.
5. Preserve null as null. `UNKNOWN` dependency state must never be converted to `RULED_OUT` merely because evidence is absent.
6. Record participant replacements, schedule corrections and dependency corrections in a successor envelope or linked correction receipt; do not overwrite the predecessor.
7. Store post-outcome assessments separately. They reference only the exact pre-outcome evidence hash and forecast binding.
8. Append corrected final-result revisions. Never modify the pre-outcome record or silently rescore against a different revision.
9. Retain excluded observations and their reasons. They do not count toward eligible readiness.
10. Preserve all predecessor/successor links during archival and recovery.

Historical records that lack physical timestamps remain historical or uncertified. This contract provides no mechanism to backfill them as prospective evidence.
