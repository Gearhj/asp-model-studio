# ATLAS Documentation Audit

Audit date: 2026-07-03  
Scope: source docs, generated docs, governance outputs, notebook export, and user-facing documentation.

## Executive Summary

ATLAS has strong generated documentation ambitions, but project documentation is behind the product. The root README still describes a starter binary fraud workflow, not ATLAS. Generated reports have improved styling, but the documentation strategy needs sharper separation between executive summary, final model document, governance report, technical appendix, notebook export, and full decision journal.

## Current Documentation Assets

| Asset | Path | Status |
|---|---|---|
| Root README | `README.md` | Outdated. Still says DS Workflow Starter. |
| Startup instructions | `Startup Instructions.txt` | Useful local notes, but outdated and contains unrelated package cleanup commands. |
| Model Development Document generator | `src/lib/modelDevelopmentDocument.ts` | Functional; needs final-model focus. |
| Governance Report generator | `src/lib/governanceReport.ts` | Functional; uses professional table renderer. |
| Report formatting helpers | `src/lib/reportFormatting.ts` | Strong improvement; still needs sanitization. |
| Notebook export | `src/lib/notebookExport.ts` | Functional workflow reproduction export. |
| Decision Journal export | `src/lib/decisionJournal.ts` and `src/steps/DecisionJournal.tsx` | Functional but verbose. |
| Experiment export | `src/lib/experimentTracking.ts` and `src/steps/ExperimentComparison.tsx` | Functional CSV export. |

## Source Documentation Gaps

| Gap | Impact | Recommendation |
|---|---|---|
| README still uses old product name | New collaborators start with wrong mental model. | Replace with ATLAS overview, architecture, local setup, app modes, and common tasks. |
| No architecture diagram | Hard to understand mixed ATLAS/STELA/guitarist workspace. | Add `docs/ARCHITECTURE.md` after restructure. |
| No persistence map | Browser state vs backend checkpoint confusion causes save/reopen bugs. | Add `docs/PERSISTENCE.md`. |
| No workflow-specific docs | Experimental Design and Predictive Modeling behavior is embedded in code. | Add `docs/workflows/predictive-modeling.md` and `docs/workflows/experimental-design.md`. |
| No security notes | Users may zip or share sensitive runtime data. | Add `docs/SECURITY_AND_DATA_HANDLING.md`. |
| No release checklist | Hard to verify functionality after changes. | Add `docs/RELEASE_CHECKLIST.md`. |

## Generated Model Development Document

### What It Should Be

The Model Development Document should be a polished, final-model document suitable for model risk management review. It should explain:

- What model was built.
- Why it was built.
- Which data was used.
- Which features were used.
- Which candidate models were compared.
- Why the champion was selected.
- How it performed.
- What limitations exist.
- How it will be implemented and monitored.

### Current Risks

| Risk | Evidence | Recommendation |
|---|---|---|
| Too much event history | Decision Journal and Experiment Appendix can become long. | Keep full history in appendix only; add a material decision summary. |
| Markdown/HTML hybrid | Markdown export includes HTML/style snippets. | Make HTML/PDF/DOC exports primary; keep Markdown clean or label it "HTML-flavored Markdown". |
| Project state dependency | Generated from browser state and experiments. | Add report readiness validation before export. |
| Raw JSON risk | Some sections previously rendered object data directly; many are now table-rendered. | Add tests to prevent raw JSON/object dumps. |

## Governance Report

### Strengths

- Uses ATLAS branding.
- Covers project context, data, preprocessing, candidate models, champion, performance, monitoring, appendices.
- Experimental Design report can pull synchronized analysis objects.
- Workflow Definition now uses `professionalTableHtml`.

### Remaining Needs

1. Add report validation status before export.
2. Add "missing required evidence" callouts.
3. Add report version number and prepared-by/reviewer fields.
4. Add landscape PDF guidance for wide tables.
5. Add an executive export with fewer appendices.

## Decision Journal

The Decision Journal is useful for audit defensibility but too long as a normal document section.

Recommended structure:

| Layer | Purpose |
|---|---|
| Material Decision Summary | 10 to 20 important decisions, grouped by stage. |
| Full Decision Timeline | Complete audit trail, exported separately or appendix. |
| User Rationale Gaps | List decisions missing rationale. |
| Overrides | Highlight places where user overrode ATLAS recommendations. |

## Notebook Export

Notebook export should remain reproducibility-focused, not governance-primary.

Recommended additions:

- Include project ID/model ID in first markdown cell.
- Include dataset hash/version, not raw data.
- Include a "manual actions required" cell for external data paths.
- Include decision journal notes per step only in summarized form.
- Add a validation cell checking column alignment before scoring.

## Experimental Design Documentation

The Experimental Design documentation should be generated from the shared analysis object. That direction is already present in `src/lib/experimentalDesign.ts` and `src/lib/governanceReport.ts`.

Recommended report sections:

1. Experiment charter.
2. Research question and hypotheses.
3. Factor hierarchy.
4. Treatment structure and matrix.
5. Blocking decision.
6. Randomization method and QA.
7. Sample size and power.
8. Monte Carlo validation.
9. Run plan.
10. ANOVA model plan.
11. Optimization recommendation.
12. Governance evidence and decision log.

## Documentation Redesign Principles

1. The live workflow and exported report should use the same analysis object.
2. The final document should summarize final decisions, not every UI event.
3. Full audit history belongs in an appendix or separate Decision Journal export.
4. Tables must render as professional HTML tables, not raw Markdown pipes.
5. Executive sections should be concise and business-readable.
6. Technical sections should preserve reproducibility and validation evidence.

## Recommended Documentation Folder After Migration

```text
docs/
  README.md
  ARCHITECTURE.md
  LOCAL_DEVELOPMENT.md
  PERSISTENCE.md
  SECURITY_AND_DATA_HANDLING.md
  RELEASE_CHECKLIST.md
  workflows/
    predictive-modeling.md
    experimental-design.md
  governance/
    model-development-document-template.md
    governance-report-template.md
    decision-journal-policy.md
```

