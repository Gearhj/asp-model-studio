"""Render the completed, fixed QB residual comparison without re-simulation."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/nfl-m1-qb-context-residual-v1"


def read(r):
    b = Path(r["path"]).read_bytes()
    assert hashlib.sha256(b).hexdigest() == r["sha256"] and len(b) == r["bytes"]
    return json.loads(b)


def main():
    result_ref = json.loads((OUT/"assessment.json").read_bytes())
    r = read(result_ref)
    config_ref = json.loads((OUT/"fitted-config.json").read_bytes())
    cfg = read(config_ref)
    g, o = r["byContext"], r["overall"]
    d = o["candidateMinusBaseline"]
    lines = ["# NFL M1 lagged QB-usage-conditioned residual challenger", "",
        "**Decision: reject this configuration for advancement and retain the existing pooled sampler.** The joint energy difference was effectively zero, its interval included benefit and harm, and both winner guardrails worsened. No prospective candidate was frozen.", "",
        "The completed chronological comparison uses 838 paired residual donors from 2020–2022 and all 570 eligible games in 2023–2024. Each point forecast came from M1 trained only on earlier seasons. Both arms use the same point predictions, 10,000 draws per game, paired residual bank, nonnegative transformation, stochastic rounding and tie handling. The fitted production M1 artifacts and ordinary publication are unchanged.", "",
        "| Metric (lower is better) | A pooled | B conditioned | B − A | Paired 95% block interval |",
        "|---|---:|---:|---:|---:|"]
    for k in ("energy", "logLoss", "brierSum", "homeCRPS", "awayCRPS", "totalCRPS", "marginCRPS"):
        lo, hi = o["pairedBlockIntervals"][k]["interval95"]
        lines.append(f"| {k} | {o['baseline'][k]:.6f} | {o['candidate'][k]:.6f} | {d[k]:+.6f} | [{lo:+.6f}, {hi:+.6f}] |")
    lines += ["", "Brier is the sum of squared probability errors over **AWAY/TIE/HOME**, using the existing three-class probability convention. No MLB binary conversion is applied. The interval resamples 46 season/week blocks 2,000 times; the 10,000 simulated draws are not independent observed games. Paired simulation MCSE is retained separately.", "",
        "| Lagged context: home / away | Applied / fallback games | Matching donors | ESS | Δ expected home / away | Δ energy | Δ log loss | Δ summed Brier |",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for k in ("STABLE|STABLE", "MIXED|STABLE", "STABLE|MIXED", "MIXED|MIXED"):
        v = g[k]
        x = v["candidateMinusBaseline"]
        lines.append(f"| {k.replace('|', ' / ')} | {v['supportedGames']} / {v['fallbackGames']} | {v['meanDonorSupport']:.0f} | {v['meanESS']:.1f} | {x['homeMean']:+.3f} / {x['awayMean']:+.3f} | {x['energy']:+.5f} | {x['logLoss']:+.5f} | {x['brierSum']:+.5f} |")
    unknown = sum(v["games"] for k, v in g.items() if "UNKNOWN" in k)
    lines += [f"| Either side UNKNOWN | 0 / {unknown} | Not conditioned | 838.0 | 0 / 0 | 0 | 0 | 0 |", "",
        "Conditioning ran on **456 games**. The **114 exact pooled fallbacks** comprise 92 unknown contexts and 22 mixed/mixed games with only 26 matching donors, below the frozen minimum of 40. Every fallback uses all 838 pooled donors. The fitted local shrinkage is n/(n+100); no thresholds or weights were selected from assessment results.", "",
        "| Supported home / away context | Δ variance home / away | Δ home-away correlation | Δ P(total ≥ 60), pp | Δ P(home ≤ 10), pp | Δ P(away ≤ 10), pp | Δ P(abs margin ≥ 21), pp |",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for k in ("STABLE|STABLE", "MIXED|STABLE", "STABLE|MIXED"):
        x = g[k]["candidateMinusBaseline"]
        lines.append(f"| {k.replace('|',' / ')} | {x['homeVariance']:+.3f} / {x['awayVariance']:+.3f} | {x['homeAwayCorrelation']:+.4f} | {100*x['totalAtLeast60']:+.3f} | {100*x['homeAtMost10']:+.3f} | {100*x['awayAtMost10']:+.3f} | {100*x['absoluteMarginAtLeast21']:+.3f} |")
    lines += ["", "Variance is in squared points; pp means percentage points. Mixed lagged usage did not uniformly widen the score distribution or lower both teams' means. The population means shifted by "+f"{d['homeMean']:+.4f} home and {d['awayMean']:+.4f} away points ({d['totalMean']:+.4f} total). No arm was recentered after weighting.", "",
        "Period stability: "+"; ".join(f"{y}: Δ energy {v['candidateMinusBaseline']['energy']:+.6f}, Δ log loss {v['candidateMinusBaseline']['logLoss']:+.6f}, Δ Brier {v['candidateMinusBaseline']['brierSum']:+.6f}, {v['supportedGames']}/{v['games']} supported" for y,v in r["bySeason"].items())+".", "",
        "Coverage, interval-width and ESS guardrails passed. Primary-score confidence, period stability, winner guardrails and the all-marginal-CRPS guardrail did not. The small energy difference does not establish improvement, and the direction of winner-score changes triggers the predeclared rejection rule.", "",
        "Context means only the prior two or three eligible same-season games, with at least 20 dropbacks and 90% actor attribution per selected game. It uses a conservative reconstructed availability delay and never the target game's actual quarterback. Archived historical expected-starter/injury availability was not established, so it is absent. NFLverse documents separate update schedules for PBP, player stats, participation and depth charts; available present-day rows do not certify historical pregame availability. [Official source schedule](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html).", "",
        "This is reused Development with finalized-source corrections and inherited model-selection limitations. Chronological model training does not make it untouched external confirmation. Sealed 2025 and the two motivating opening-2026 results were excluded; no provider acquisition, point-model fit, production change or new monitor occurred.", "",
        "Frozen configuration: "+config_ref["path"]+"; physical SHA256 "+config_ref["sha256"]+".",
        "Assessment: "+result_ref["path"]+"; physical SHA256 "+result_ref["sha256"]+".", "",
        "Reproduce the comparison from the retained frozen configuration and admitted assessment data:", "", "```powershell",
        ".venv/Scripts/python.exe -B scripts/run_nfl_m1_qb_context_residuals.py --phase assess --data outputs/nfl-m1-qb-context-residual-v1/residuals/assessment-residuals.parquet --contexts outputs/nfl-m1-qb-context-residual-v1/contexts/contexts.parquet --source-receipt outputs/nfl-m1-qb-context-residual-v1/residuals/assessment-residuals-receipt.json",
        ".venv/Scripts/python.exe -B scripts/report_nfl_m1_qb_context_residuals.py", "```", "",
        "The sampler configuration is self-contained: `authority_from_config(config)` restores its paired bank; `simulate_comparison(...)` accepts point means, exact game identities/dates and honest context keys. It cannot establish current starter availability. The current decision does not authorize a prospective publication."]
    # The block count is an existing scorer output, not a presumed calendar count.
    lines = [line.replace("46 season/week blocks", str(o['pairedBlockIntervals']['energy']['seasonWeekBlocks'])+" season/week blocks") for line in lines]
    text = "\n".join(lines)+"\n"
    (OUT/"RESULTS.md").write_bytes(text.encode())
    print(json.dumps({"report": str((OUT/'RESULTS.md').resolve()), "verdict": r['verdict'], "simulationReruns": 0}))


if __name__ == '__main__':
    main()
