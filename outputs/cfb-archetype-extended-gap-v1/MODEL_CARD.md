# CFB_ARCHETYPE_AND_EXTENDED_GAP_CHALLENGER_V1

Disposition: **RETAIN_GLOBAL_BASELINE**.

Scope: FBS-versus-FBS regular-season weeks ≤14, full-game scores including overtime. Historical source attribution: SportsDataverse / ESPN-derived retained exports, admitted private research; source review and acquisition receipts remain bound.

Base point configuration: frozen Ridge alpha100, 35 governed pregame features. Eight side-neutral state variables feed KMeans. Clusters fit only earlier Development; 2023–2025 use the fixed through-2022 objects.

Archetype mechanism: k=2, ordered away/home cluster residual bias, 0.5*n/(n+200) correction. Gates require ≥200 games, ≥3 seasons and ≥20 distinct teams per side, plus cluster quality and distance support. Unsupported targets reproduce the eligible comparison baseline exactly.

Gap mechanism: either team <2 current-season completed context games or >21 same-season days of inactivity; earlier Development margin residual variance ratio shrunk by 200 global games; factor constrained to [1,1.5], ≥150 target residuals and ≥2 seasons. No point correction.

Frozen through-2022 margin scale: 1.113567096277, estimated from 751 targeted Development residuals. Every first eligible primary game is included in this gate; first-context and first-primary opener counts are reported separately.

Distribution: 10,000 paired earlier-season OOF residual draws, frozen original seed and discrete support transformation. Legacy earlier-kickoff donor output is retained only as an exact historical reference because completion-time eligibility is unverified. The comparison eligibility rule is separately identified and has not changed production.

Selection: six season-forward Development folds 2017–2022; frozen later comparison 2023–2024; 2025 secondary reused. No pristine test, no prospective superiority claim. Calendar-week paired bootstrap intervals assess sampling across games, not draws.

All controls false: AISP integration, wagering, real money, promotion and new prospective forecast authority. No injuries, players, returning-production, roster, quarterback or weather evidence is fabricated. See REPORT.md and ASSESSMENT.json for harms, missingness and all frozen admission checks.
