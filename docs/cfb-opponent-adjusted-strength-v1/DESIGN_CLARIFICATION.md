# Pre-comparison clarification: zero-support prior semantics

Recorded while only strength feature histories were being fitted, before any point-model comparison, Development score or later assessment was produced or inspected.

In DESIGN.md, “No current evidence means the same prior” means the **same prior precision lambda at zero current support and the same transfer rule**, not numerically identical A/B prior means. Each procedure recursively estimates its preceding-season effects using its own static or dynamic update law. B's preceding-season pooled estimates may therefore differ from A's, and that difference can carry into a new-season cold start. An unseen team with no preceding-season support receives zero offense/defense prior under both.

This clarification describes the already implemented estimator. It adds no configuration, selection freedom, data source or numerical change. B-versus-A remains the ablation of dynamic shrinkage across the full chronological procedure, including its prior-season estimates; it does not isolate only the final current-season update. Both explicit update rules and support diagnostics remain inspectable in every retained strength artifact. The fixed adjusted/unadjusted comparison and all advancement gates are unchanged.
