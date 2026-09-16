"""Retain the bounded preview delivery report; reads only its own forecast evidence."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_shared.show_preview import canonical, digest, immutable, physical, checked_file, utc

OUT = ROOT / "outputs/multisport-show-preview-producer-v1"
EXCHANGE = Path(r"C:\Users\james\asp-model-exchange\show-preview-forecasts-v1")
PLAN = OUT / "plans/sha256/df449de19921e637fee2fe0428b550667718640da31f217b527fdd7223f16ad1.json"
RUN = OUT / "publication-runs/sha256/fcdc04bef41c19deda150b956a9668f3bdc7b63ae693e45e1f33d37a3c88864b.json"


def write(name, value):
    raw = value.encode("utf-8") if isinstance(value, str) else canonical(value)
    immutable(OUT/name, raw)
    return physical(OUT/name)


def main():
    plan, run = json.loads(PLAN.read_bytes()), json.loads(RUN.read_bytes())
    discovery = json.loads(checked_file(run["discovery"]))
    sources = {s["source_forecast_id"]: s for s in plan["sources"]}
    rows, originals = [], {}
    for entry in discovery["packages"]:
        directory = EXCHANGE/entry["package_path"]
        f = json.loads((directory/"forecast.json").read_bytes())
        for ref in f["derivation"]["files"]:
            checked_file(ref)
            originals[ref["path"]] = ref
        rows.append({**entry, "game": f["game"], "model": f["model"], "expected_score": f["expected_score"],
                     "probabilities": f["probabilities"], "source_forecast_id": f["derivation"]["forecast_id"],
                     "source_forecast_sha256": f["derivation"]["forecast_sha256"],
                     "source_cutoff_utc": f["source_cutoff_utc"], "source_created_utc": f["derivation"]["created_utc"],
                     "preview_created_utc": f["created_utc"], "publish_by_utc": f["production_clock"]["publish_by_utc"],
                     "show_board_freeze_utc": f["intended_show_board_freeze_utc"], "draw_count": f["simulation"]["draw_count"],
                     "forecast": physical(directory/"forecast.json"), "manifest": physical(directory/"manifest.json"),
                     "delta_vs_exact_source": {"away_score": 0, "home_score": 0, "away_probability": 0, "home_probability": 0, "selection_changed": False}})
    elapsed = (utc(run["completed_utc"])-utc(run["started_utc"])).total_seconds()
    context = json.loads(checked_file(plan["context"]))
    capability = [
        {"sport": "MLB", "disposition": "BLOCKED_NO_ADMITTED_DAY_BEFORE_CONFIGURATION", "genuine_day_before_possible_now": False,
         "producer": "mlb_v18_current_publication.py under the existing Windows S4U V18 owner", "model": "Frozen V18 PA fold5 + current feature/preprocessing and accepted transitions",
         "model_sha256": "44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b",
         "required_inputs": ["two identified starters", "confirmed ordered nine-player lineups", "current participant histories", "active pitching roster", "source-backed 246-field inputs"],
         "earliest_reliable_availability": "Existing ordinary owner starts at T-60, then T-45/T-30/T-15/T-5, subject to evidence. No guarantee the preceding afternoon.",
         "reuse_without_recomputation": "No eligible day-before source bound to current requested games was admitted.",
         "distinct_preview_configuration_required": True,
         "missing_evidence": ["Governed current-feature projected-lineup contract", "time-stamped prior batting order and active roster bound to target", "preview-cutoff approximation with admissible paired final comparison"],
         "old_early_path": "mlb_v18_daily_slate.py has MOST_RECENT_PRIOR_COMPLETE_LINEUP_AVAILABLE_BEFORE_CAPTURE, but also SOURCE_END=2026-08-13 historical player templates and generic cold_batter substitution. It is not the current source-backed participant path.",
         "smallest_next_configuration": "A separately identified current-feature V18 preview using a frozen prior-complete-order rule, probable starters, active-roster checks and explicit uncertainty. First establish eligible evidence and cutoff-matched assessment; do not relax the final path.",
         "preview_performance": "UNAVAILABLE; no admitted paired preview/final population, no new outcome access, no accuracy claim.",
         "runtime": "Blocked before inference; no honest new-configuration runtime measured.", "editorial_model_market_comparison": False},
        {"sport": "NFL", "disposition": "OPERATIONAL_MANUAL_EXACT_REUSE_16_PUBLISHED", "genuine_day_before_possible_now": True,
         "producer": "NFL M1 prospective_shadow/current_shadow and existing AISP-owned invocation of Model Studio; separate from NFL play/drive research",
         "model": "NFL_M1_XGBOOST / NFL_M1_2026_RESEARCH_SHADOW_V1", "model_sha256": "7bec06646fd5035380107501d07e139425ac483a47e02e0bbbd56301124fb8fd",
         "required_inputs": ["verified existing forecast bundle", "exact scheduled identity", "197-feature binding", "complete retained joint mass"],
         "earliest_reliable_availability": "Days ahead once existing producer publishes; selected Week2 sources available September14–15, before their September16/19/20 show deadlines.",
         "owner": "Existing asp-nfl-shadow-producer-current at05:30 scheduler time; final owner remains separate and unchanged. Preview hook staged, no new scheduler.",
         "reuse_without_recomputation": True, "distinct_preview_configuration_required": "New editorial derivative configuration only; no model change",
         "missing_evidence": ["current personnel, injuries, starters and lineups", "information after original source cutoff"],
         "preview_performance": "Exact numerical delta0 versus each selected source. Later FINAL revision performance is unavailable; no outcomes assessed.",
         "limitations": "Empirical equal-score tie mass retained; not validated NFL overtime/tie calibration. MCSE is numerical precision.",
         "runtime": "Part of measured17-package batch; no simulation runtime.", "editorial_model_market_comparison": True},
        {"sport": "CFB", "disposition": "OPERATIONAL_MANUAL_EXACT_REUSE_1_PUBLISHED", "genuine_day_before_possible_now": True,
         "producer": "run_cfb_gen1_current_v1.py / publish_cfb_gen1_current_v1.py, manual governed owner", "model": "CFB_GEN1_RIDGE_A100_PAIRED_RESIDUAL_V1 baseline only",
         "model_sha256": "cb3f20293477100c202d48c174f1c3e706c943728697e1089bbb742453876bb6",
         "required_inputs": ["existing verified baseline package", "captured CFBD/ACC schedule", "35-feature binding", "original paired draws"],
         "earliest_reliable_availability": "Syracuse–Pittsburgh original publication2026-09-14T22:16:01.605132Z; preview deadlineSeptember16 16:00ET.",
         "reuse_without_recomputation": True, "distinct_preview_configuration_required": "Editorial derivative only",
         "missing_evidence": ["personnel/QB, injuries, lineups, weather", "canonical AISP game absent in captured schedule"],
         "preview_performance": "Delta0 versus source Ridge point/probability channels; no FINAL comparison or new assessment.",
         "limitations": "Ridge expected points and calibrated Ridge-margin winner probabilities are separate from residual intervals. Source joint home-win0.7692 and Elo0.66934248 are not substituted for Ridge0.74775625. No gap/cluster arm used.",
         "runtime": "Part of measured17-package batch; no simulation runtime.", "editorial_model_market_comparison": True},
        {"sport": "NBA", "disposition": "ADAPTER_TESTED_NO_ELIGIBLE_SLATE", "genuine_day_before_possible_now": "Capability yes; no target in September16–22 projection",
         "producer": "Existing NBA joint prospective manual publisher; new nba_source adapter tested only with synthetic fixture",
         "model": "NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1 around corrected Ridge alpha100; Elo remains separate",
         "model_sha256": "063e69ffb685a16bd784276fa94bce27f8e2d5e91f744e8c9a60a46f242f70ef",
         "required_inputs": ["eligible schedule", "original joint baseline, model/feature and publication bindings"],
         "earliest_reliable_availability": "Existing early snapshot exists forOctober20; no day-before NBA slate currently eligible.",
         "reuse_without_recomputation": True, "distinct_preview_configuration_required": "Editorial derivative only; no close-score promotion",
         "missing_evidence": ["eligible next slate", "players, injuries, lineups, possessions and boxes"],
         "preview_performance": "UNAVAILABLE; fixture validation is software evidence only. Existing NBA historical joint results preserved.",
         "runtime": "Fixture-only adapter checks; live batch runtime unmeasured.", "editorial_model_market_comparison": "Supported when an authentic eligible source is registered"},
    ]
    write("CAPABILITY_MATRIX.json", {"sports": capability, "prepare_seconds": plan["prepare_seconds"], "publication_batch_seconds": elapsed})
    capmd = "# Show Preview capability\n\n| Sport | Current result | Evidence and limitation |\n|---|---|---|\n"
    for c in capability:
        capmd += f"| {c['sport']} | {c['disposition']} | {c['earliest_reliable_availability']} |\n"
    capmd += "\nThe JSON matrix retains producer/model identities, required inputs, owners, runtime, and gaps. No preview performance experiment was run.\n"
    write("CAPABILITY_MATRIX.md", capmd)
    write("external-call-accounting.json", {"external_provider_requests": 0, "external_provider_response_bytes": 0, "incremental_cost_usd": 0,
        "sportsgameodds_calls": 0, "odds_api_calls": 0, "model_executions": 0, "new_simulations": 0, "aisp_writes": 0,
        "loopback_contract_gets": 2, "retained_second_response_bytes": context["local_http_response_bytes"],
        "first_loopback_response_physical_size": None, "first_loopback_response_note": "Initial tool inspection returned parsed text; physical bytes were not retained. This is local HTTP, not a provider request.",
        "aisp_schedule_read": {"transactions": 1, "read_only": True, "outcome_columns": [], "team_identity_rows": len(context["rows"]), "receipt": plan["context"]},
        "scheduled_task_inspection": "Get-ScheduledTask returned Access denied; no bypass or scheduler mutation. Reuse prior successful owner receipt with qualification."})
    write("source-preservation.json", {"source_files_verified": len(originals), "byte_identical": True, "files": list(originals.values()),
        "scope": "All immutable files bound to these17 source forecasts; existing final files were never write targets. Independent owners may legitimately append new artifacts.",
        "current_season_outcome_payloads_opened": 0, "sealed_payloads_opened": 0, "AISP_rows_modified": 0})
    write("preview-publication-index.json", {"schema": "ASP_SHOW_PREVIEW_PUBLICATION_INDEX_V1", "discovery": run["discovery"], "packages": rows,
                                           "inventory": plan["inventory"], "plan": physical(PLAN), "publication_run": physical(RUN)})
    command = f'.\\.venv\\Scripts\\python.exe -B scripts/run_show_preview_v1.py verify --plan "{PLAN}"'
    contract = f'''# SHOW_PREVIEW producer contract V1

Wire schema `{ 'AISP_SHOW_PREVIEW_FORECAST_V1' }`, horizon exactly `SHOW_PREVIEW`. Frozen source documents remain unchanged. This producer creates a separate ID and configuration `MULTISPORT_SHOW_PREVIEW_EXACT_SOURCE_REUSE_V1` with explicit derivation, original evidence clocks, physical source files, reuse flags, limitations and editorial-only authority. No wagering, FINAL_PREGAME, promotion, positions, stake or scheduler authority is inherited.

`game.slate_date` is the kickoff date in America/New_York. The previous local date has identify15:00, resolve15:15, publication deadline16:00, Show Board freeze16:30 and recording17:00. DST is computed with ZoneInfo; e.g. NFL September18 00:15Z kickoff belongs to September17ET, with preview deadlineSeptember16 20:00Z. Source cutoff≤source creation≤source availability≤preview creation≤publication start≤16:00ET<kickoff. Package verification completion must also precede16:00. Early publication is permitted and labelled an earlier-source snapshot, not a claim about later evidence. Late new artifacts fail closed; old byte-identical previews can still be verified/reused.

All probabilities are fractions0..1; away+home+tie=1. Expected scores, original distributions and 10000-draw denominators are preserved. NFL source-0.json contains the original bundle; select the exact derivation.forecast_id, then jointScoreDistribution. CFB source-2.parquet is the original paired population. Never substitute independent marginals, discard tails or use an expected total as an Over probability. CFB expected scores/winner channel and residual intervals are independently estimated and explicitly identified. NFL equal-score tie mass is retained with its limitation.

Consumer-required fields follow the live contract. Additive fields include publication_utc (publication-start clock), production_clock, intended_show_board_freeze_utc, feature_contract, simulation, derivation, team_evidence, support_classification, forecast_output_semantics and predecessor_forecast_id. Availability UNKNOWN is accompanied by per-team missing-evidence codes and explicit no-substitution fallback. Detailed source-status certification is not invented.

Canonical JSON is UTF-8, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",",":"). `forecast_id` hashes the document before forecast_id/integrity; `integrity.content_sha256` hashes the document without integrity. The full physical forecast hash is different. Physical members are SHA256/byte-bound. Package address is the physical manifest.json SHA256; no unrelated logical identity is substituted. Full members verify before atomic discovery replacement. Every discovery version also exists under indexes/sha256. Same source/config/schedule reuses the existing artifact, retaining clocks. A new admitted source or schedule revision gets a new ID with predecessor; it never overwrites a prior object.

Actual consumer validator: `{context['consumer_validator']['path']}` SHA256 `{context['consumer_validator']['sha256']}`. Its inspected pure function is loaded directly by path, with bytecode writes disabled; no app database is loaded by validation. Producer checks additionally reject nonfinite values, changed source values, deadline violations and relabelling without derivation. Consumer import validates its own canonical schedule and duplicate-ID contract; publication is not import.

Verification: `{command}`. No provider or model execution is performed. The source plan and existing original source objects must remain available. Imports read only packages named in discovery, never scan other research trees. AISP may display an unbound CFB producer reference; attach a canonical ID only after exact schedule reconciliation.
'''
    write("SHOW_PREVIEW_PRODUCER_CONTRACT.md", contract)
    activation = f'''# Activation: staged and inactive

No Windows task, deployed V18 owner, AISP runtime/configuration, STOP file, sport account or existing final process was changed. NFL/MLB owners continue independently. NBA/CFB remain manual. Get-ScheduledTask was denied; prior successful S4U evidence is retained in outputs/four-sport-operational-handoff-20260915-v1/operational-handoff.json (deployment77d39e1…, manifest8bf005ee…). No fresh owner-state certification is claimed.

The callable hook is scripts/run_show_preview_v1.py. Activation must append it to an existing appropriate owner/deployment, not register a second sport scheduler. For NFL the invocation owner is AISP's existing scheduler; Claude owns that runtime change. A proposed owner configuration is staged in activation-plan.json with active=false.

At15:00 America/New_York, the existing schedule owners populate their normal stores. Run the read-only capture using the configured AISP Python in its server working directory (no consumer writes):
`C:\\Users\\james\\ai-sports-predictor\\.venv\\Scripts\\python.exe -B {ROOT}\\scripts\\capture_show_preview_context.py --output <new immutable capture directory> --through <bounded next-slate end UTC>`

At15:15ET, from Model Studio run `.\\.venv\\Scripts\\python.exe -B scripts/run_show_preview_v1.py prepare --context <capture/context.json> --slate-date <tomorrow in ET>`. Consume the returned immutable plan.path, then run `.\\.venv\\Scripts\\python.exe -B scripts/run_show_preview_v1.py publish --plan <that path> --slate-date <tomorrow in ET>`. Preparation uses only existing publications. It does not generate or acquire missing inputs. A single-source failure is actionable; never loosen a model's gates to clear it. Do not start a fresh batch after15:55; hard publication cutoff16:00. Measured initial17-package publication batch: {elapsed:.2f}s, plus preparation{plan['prepare_seconds']:.2f}s. Source/consumer changes can fail closed; runtime is not a guarantee.

For NBA, register an eligible current original baseline through show_preview_sources.nba_source with verified forecast, population, publication, model and feature refs plus exact schedule projection. Fixture test covers this capability. BOS–DET is intentionally not rewrapped by this release. MLB remains disabled until its separate preview evidence/feature contract is admitted; existing final T-60/T-45/T-30/T-15/T-5 owner remains intact.

Claude's minimal consumer step: make the existing exchange consumer discover show-preview-forecasts-v1/discovery.json, verify each manifest/member and call app.show_preview.imports.import_preview_forecast(session,document,settings). Show Preview is currently disabled. Claude controls enabling it. No import/discovery route currently calls that function outside its module/tests. The declared15:15 import step is a callable capability, not a verified wired job. Consume later arrivals through16:00 before the16:30 freeze using the existing owner; do not run sportsbook work in this producer. Return explicit import/display receipts.

Manual repeat of the delivered plan is idempotent: `.\\.venv\\Scripts\\python.exe -B scripts/run_show_preview_v1.py publish --plan "{PLAN}"`. Existing preview clocks remain unchanged. No new publication may be backfilled after its deadline.
'''
    write("ACTIVATION.md", activation)
    write("activation-plan.json", {"active": False, "timezone": "America/New_York", "identify": "15:00", "resolve": "15:15", "last_new_batch": "15:55",
                                   "publish_deadline": "16:00", "consumer_freeze": "16:30", "entrypoint": "scripts/run_show_preview_v1.py",
                                   "owner_requirement": "APPEND_TO_EXISTING_OWNER_ONLY", "new_windows_tasks": 0,
                                   "MLB_enabled": False, "NBA_requires_eligible_registered_source": True, "provider_calls": False, "consumer_writes": False})
    report = f'''# MULTISPORT SHOW_PREVIEW FORECAST PRODUCER V1

**NFL and CFB preview production works and is published:16 NFL Week2 games and1 CFB game. NBA's adapter is tested, with no eligible September16–22 slate. MLB remains blocked by its current input contract.** No model was fitted, resimulated, replaced or promoted. The NFL EPA challenger remains queued.

The {len(rows)} editorial derivatives reuse exact source values and full10000-draw populations. Publication ran {run['started_utc']}–{run['completed_utc']} ({elapsed:.2f}s), separately from original September14–15 source clocks. Dedicated discovery: `{run['discovery']['path']}`, physical SHA256 `{run['discovery']['sha256']}`. All package addresses, values, source clocks and bindings are in preview-publication-index.json. These were published early for their future day-before shows; they do not claim the later afternoon's inputs were already captured.

| Sport | Result | Difference from final forecast |
|---|---|---|
| MLB |0 previews;39 captured future game identities, including15 September16 games | Current V18 needs confirmed ordered lineups and current pitching/participant evidence. Its first ordinary checkpoint is T-60. Today's September16 preview deadline was already past when work began. No backfill. |
| NFL |16 previews, exact retained source reuse | Same source numbers, no new personnel/news; later final revisions can differ. Tie mass is equal retained simulated scores, not separately validated tie calibration. |
| CFB |1: Syracuse at Pittsburgh, September17 23:30Z | Ridge points and calibrated Ridge-margin win probabilities retained; residual intervals remain separate. No QB/lineup/injury/weather evidence. Producer game reference is supported; canonical AISP binding remains absent. |
| NBA |Adapter and deterministic fixture only | Current joint baseline authority preserved; Elo separate, close-score arm not promoted. No BOS–DET restamp. |

MLB's older daily producer does have a prior-complete-lineup rule. It also borrows August13 historical templates and a generic cold batter, so it cannot certify the current source-backed preview requirement. No distinct MLB preview model was fitted. The smallest necessary follow-up is an explicitly separate projected-order configuration over current V18 features, with target-bound probable starters/roster/history, honest uncertainty and cutoff-matched evidence. No suitable preview/final assessment population was admitted here. Preview calibration, log loss/Brier and frequency of material final changes are unavailable; no outcomes were opened. For all17 published sources score/probability/selection deltas versus their exact reused source are zero by construction, which is integrity evidence, not accuracy evidence.

Daily target:15:00 schedule,15:15 resolve/reuse,by16:00 publish,16:30 Show Board freeze,17:00 recording, all America/New_York with DST. Automatic preview production is **staged inactive**. Existing final owners are untouched. Consumer validator compatibility is verified, but discovery ingestion is not wired and Show Preview is disabled in the captured contract. Claude must attach the dedicated index to the existing consumer owner. No AISP import/display acknowledgement is claimed.

Focused verification:8 targeted tests pass (consumer Unicode/horizon, source-value binding, chronology/DST, identity/probability/status/missingness, atomic discovery, replay/tamper, exclusive lock, MLB fail-closed and synthetic NBA capability). The actual17 packages also passed source-native and unmodified consumer validation before discovery. Each bound original file was rehashed unchanged. Existing source artifacts remain intact; test fixtures are never forecasting evidence. Initial tempfile-based tests hit Windows sandbox ACL errors before calculations; inherited-permission fixture directories resolved that test-environment issue. No permissions were changed on denied directories. Scheduled-task inspection was denied; the prior bound owner receipt is used with that qualification.

External provider calls0, external response bytes0, incremental cost$0, model executions0, new simulated draws0, AISP writes0. Two local contract GETs (second physical response4020bytes retained) and one read-only schedule transaction110team rows. No SportsGameOdds, Odds API, provider balance, current-season outcome payload, sealed data, position, policy or final forecast write. All paid authorities remain untouched.

Verify: `{command}`. See SHOW_PREVIEW_PRODUCER_CONTRACT.md, CAPABILITY_MATRIX.json, ACTIVATION.md, external-call-accounting.json and CLAUDE_HANDOFF.md. Stop here; no NFL challenger or new study is started.
'''
    write("REPORT.md", report)
    handoff = f'''# Claude handoff — SHOW_PREVIEW producer V1

Type: producer delivery + staged activation / consumer discovery wiring request. Publishing this handoff activates nothing.

17 immutable preview packages are published:16 NFL Week2 and1 CFB Syracuse–Pittsburgh. Exact discovery: `{run['discovery']['path']}`. Physical SHA256 **{run['discovery']['sha256']}**, {run['discovery']['bytes']}bytes. Immutable index: `{EXCHANGE}/indexes/sha256/{run['discovery']['sha256']}.json`.

Schema AISP_SHOW_PREVIEW_FORECAST_V1; horizon exactly SHOW_PREVIEW. Use each package manifest.json (directory address equals its physical SHA256), verify every member and the forecast content hash, then call your existing import_preview_forecast. Your contract.py SHA256 `{context['consumer_validator']['sha256']}` accepted every package. Forecast IDs are new editorial derivatives; original sources/horizons/clocks/10000-draw populations are unchanged and physically bound. Probability units are fractions0..1. NFL ties retain the empirical equal-score limitation. CFB displays Ridge scores/calibrated Ridge-margin win probabilities; residual intervals and joint0.7692 home probability are separate from Ridge0.7477562513840457. Do not promote a channel implicitly.

NFL16 games have exact AISP canonical schedule/orientation bindings from a read-only projection. CFB uses cfbd:401858225, SYR at PITT, kickoff2026-09-17T23:30Z; no canonical AISP game was found. Your board's producer-only branch can display it without manufacturing a canonical binding. NBA no eligible slate; MLB no admitted preview configuration. September16 MLB preview deadline was already expired; no artifacts were backfilled.

Original source availability is preserved; new artifact creation/publication and intended freeze clocks are separate. These are deliberately early available snapshots for future shows, not refreshed final-pregame evidence. Production plan15:00/15:15/by16:00 America/New_York; freeze16:30, recording17:00. NFL DET–BUF kickoff00:15Z September18 is September17ET; preview deadlineSeptember16 20:00Z and freeze20:30Z. DST tested. Consumer must preserve late-input limitations.

Your Show Preview flag is disabled and import_preview_forecast has no discovered caller outside its own module/tests. Add this dedicated index to your **existing** exchange consumer and import explicitly under your authority. No new producer or consumer scheduler was activated. No sportsbook calls or AISP writes belong to this producer. Return exact forecast/package import and display receipts; producer publication is not acknowledgement.

| Game | Preview ID suffix | Package SHA256 | Physical forecast SHA256 |
|---|---|---|---|
'''
    for r in rows:
        handoff += f"| {r['game']['away']['abbreviation']} at {r['game']['home']['abbreviation']} {r['game']['slate_date']} | {r['forecast_id'].split(':')[-1]} | {r['package_sha256']} | {r['forecast_sha256']} |\n"
    handoff += f"\nFull package paths are `{EXCHANGE}\\sha256\\<package SHA256>`. Required import member is forecast.json. Discovery retains receipt paths with actual publication completion clocks. See `{OUT}\\preview-publication-index.json` for source IDs, exact values and all clocks, and `{OUT}\\ACTIVATION.md` for the staged existing-owner command. Reproducible verification: `{command}`. No consumer acknowledgement exists at producer closeout.\n"
    write("CLAUDE_HANDOFF.md", handoff)
    files = [physical(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "INDEX.json"]
    write("INDEX.json", {"schema": "ASP_SHOW_PREVIEW_DELIVERY_EVIDENCE_V1", "files": files,
                         "published_discovery": run["discovery"], "consumer_acknowledgement": None})
    print(json.dumps({"handoff": physical(OUT/"CLAUDE_HANDOFF.md"), "index": physical(OUT/"INDEX.json"),
                      "package_count": len(rows), "source_files_rehashed": len(originals), "batch_seconds": elapsed}, indent=2))


if __name__ == "__main__":
    main()
