# Source and evidence matrix

| Source | Physical identity | Rows/bytes | Admitted use | Excluded use |
|---|---|---:|---|---|
| `raw-development.parquet` | `d5fdb7bcbe058f34334483a21b14e83129d19c1727d20eddb469c18668ff3b82` | 676,499 rows; 56,949,469 bytes | 2023 fold 0 outcomes and identities for chronological team-defense histories | 2025/2026 rows; prospective availability certification |
| `matched-oof.parquet` | `3e816c20f6276837062b97aaa5398984ac0b3660731cc086dfae4aef04f2c8ba` | 494,432 OOF rows; 71,164,182 bytes | Exact V18 fold-1 probabilities for matched reused diagnostic assessment | Model refit; Final OOT; game-level forecast claims |
| `game-context.parquet` | physical `9a642b0f...0296d`; logical directory `b94fa317...bfd9a` | 8,976 games; 268,180 bytes | Home/away orientation and fielding-team mapping | Named defender identity or alignment |
| `timing-evidence.json` | `5bbcdf6c7cae0332b903db18b410a6bae2da05da6871e2125688c6e8394b0e6b` | 15,886 bytes | Completion proxies, delayed-game exclusions, unresolved finalization exclusion | Certification of the original rolling-feature chronology |
| Earlier V19 archive | immutable local archive | 14 delayed games / 1,033 PAs; 61 unresolved PAs | Blocker evidence and capability audit | Candidate performance or promotion |

No new provider acquisition occurred. The team-defense model uses only fielding-team identity, completion-aware dates, and four governed BIP outcome classes. It does not consume names, locations, descriptions, or protected payloads.

The permanent Final OOT quarantine remains binding. No Final OOT report was attempted, so `final_oot_eligible_key_mask` and `require_reduced_final_oot_report` were not invoked and the sealed payload remained unopened.
