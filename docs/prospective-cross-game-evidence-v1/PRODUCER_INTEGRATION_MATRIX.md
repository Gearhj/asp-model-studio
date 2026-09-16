# Inactive producer integration matrix

| Sport | Existing/future owner | Additive hook | Current state |
|---|---|---|---|
| MLB | `server/sports_current_statcast/mlb_v18_current_publication.py` | After immutable forecast/package verification, before discovery update | Inactive; no import or owner change |
| NFL | `server/sports_nfl_m1/current_state_repaired_publication.py` | After immutable forecast/package verification, before prospective-index update | Inactive; no import or owner change |
| NBA | `scripts/publish_nba_gen1_joint_prospective.py` | After research package verification, before any future discovery update | Inactive; research only |
| CFB | `scripts/publish_cfb_gen1_current_v1.py` | After research package verification, before exchange publication | Inactive; research only |
| MMA | Future governing MMA publisher | Future post-package-verification sidecar adapter | Blocked: no publisher or model |

The shared library has no filesystem or publisher dependency. Sport owners would supply their already verified identities, clocks and dependency evidence to the common validator. Existing packages that cannot change receive a content-addressed sidecar. No current or final pointer is rewritten.

Activation requires separate authorization to edit each producer owner, create a dedicated evidence discovery index, publish new sidecars prospectively and let Claude implement AISP ingestion. Those are four distinct actions; none is implied by this branch.
