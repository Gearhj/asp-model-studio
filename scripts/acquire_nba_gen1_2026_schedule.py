"""One licensed 2026 season export, with a strictly metadata-only first pass.

The complete source bytes are retained. Outcome columns are not materialized by
this script; the frozen identity cohort must precede any later score conversion.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_nba_gen1.authority import json_bytes, reference, verified_bytes

OUT = ROOT / "outputs/nba-gen1-long-gap-v1"
ADMISSION = OUT / "source-review/admission.json"
ADMISSION_SHA = "995811df3c0a75152a6a30d54d6a8f3ffe4eb7681a6fa5f5a4df06e1f2ba4b70"
DECLARATION_SHA = "9356f8bad72967746fed4aacc6c97091bdfa147796955bd8ef62dd336615973b"
SAFE_METADATA = {
    "id", "game_id", "uid", "date", "game_date", "game_date_time",
    "season", "season_type", "season_slug", "type_id", "type_abbreviation",
    "neutral_site", "conference_competition", "tournament_id", "groups_id",
    "status_type_id", "status_type_name", "status_type_state",
    "status_type_completed", "status_type_description",
    "home_id", "away_id", "home_team_id", "away_team_id",
    "home_abbreviation", "away_abbreviation", "home_team_abbrev", "away_team_abbrev",
    "home_name", "away_name", "home_display_name", "away_display_name",
    "home_location", "away_location", "home_short_display_name", "away_short_display_name",
    "home_conference_id", "away_conference_id", "venue_id", "venue_full_name",
    "notes_type", "notes_headline", "game_type", "short_name", "name",
    "PBP", "team_box", "player_box",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def main():
    pointer = OUT / "acquisition-2026.json"
    if pointer.exists():
        previous = json.loads(pointer.read_bytes())
        verified_bytes(previous["original"])
        verified_bytes(previous["metadata"])
        print(json.dumps({"status": "REUSED_NO_NETWORK", "receipt": reference(pointer)}, indent=2))
        return
    admission_raw = ADMISSION.read_bytes()
    assert hashlib.sha256(admission_raw).hexdigest() == ADMISSION_SHA
    admission = json.loads(admission_raw.decode("utf-8-sig"))
    declaration = OUT / "declaration.json"
    assert hashlib.sha256(declaration.read_bytes()).hexdigest() == DECLARATION_SHA
    assert admission["license"] == "CC-BY-4.0"
    assert admission["status"] == "ADMITTED_FOR_METADATA_FIRST_CATEGORY_A_RESEARCH"
    assert admission["intake"]["logicalDatasetGets"] == 1
    assert admission["intake"]["maximumBytes"] == 600000
    asset = admission["asset"]
    attempt = OUT / "source-review/dataset-attempt.json"
    assert not attempt.exists(), "One-GET attempt already recorded; do not reset the allowance."
    started = now()
    attempt.write_bytes(json_bytes({"startedAtUtc": started, "url": asset["url"],
        "maximumBytes": 600000, "logicalDatasetGet": 1, "declaration": reference(declaration),
        "admission": reference(ADMISSION), "priorAllowanceReset": False}))
    with urlopen(Request(asset["url"], headers={"User-Agent": "ASP-Model-Studio-NBA-Research/1.0"}), timeout=45) as response:
        status = response.status
        headers = {k: v for k, v in response.headers.items()
                   if k.lower() in {"content-type", "content-length", "last-modified", "etag", "date"}}
        raw = response.read(600001)
    acquired = now()
    sha = hashlib.sha256(raw).hexdigest()
    raw_path = OUT / "source/sha256" / sha / asset["name"]
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw)
    assert status == 200 and len(raw) == asset["bytes"] and sha == asset["sha256"], \
        "Published asset mismatch: retained actual response, no retries or outcome parsing."
    schema = pq.read_schema(raw_path)
    schema_path = OUT / "source-schema-2026.json"
    schema_path.write_bytes(json_bytes({"createdAtUtc": now(), "source": reference(raw_path),
        "columns": [{"name": field.name, "type": str(field.type)} for field in schema],
        "rowStatisticsExamined": False}))
    chosen = [column for column in schema.names if column in SAFE_METADATA]
    assert "season" in chosen and "season_type" in chosen
    assert "home_id" in chosen and "away_id" in chosen
    assert "id" in chosen or "game_id" in chosen
    metadata = pq.read_table(raw_path, columns=chosen)
    meta_path = OUT / "scope-metadata-2026.parquet"
    pq.write_table(metadata, meta_path)
    frame = metadata.to_pandas()
    group_cols = [c for c in ["season", "season_type", "status_type_state", "status_type_completed"] if c in frame]
    counts = frame.groupby(group_cols, dropna=False).size().reset_index(name="sourceRows").to_dict("records")
    receipt = {"schema": "nba-gen1-2026-metadata-first-acquisition-v1",
        "createdAtUtc": now(), "downloadStartedAtUtc": started, "acquiredAtUtc": acquired,
        "evidenceClass": "A_HISTORICAL_FINALIZED_RECORD_RECONSTRUCTION",
        "admission": reference(ADMISSION), "declaration": reference(declaration),
        "asset": asset, "httpStatus": status, "responseHeaders": headers,
        "original": reference(raw_path), "schemaFile": reference(schema_path),
        "metadata": reference(meta_path), "metadataColumns": chosen, "metadataGroups": counts,
        "logicalDatasetGets": 1, "sourceBytes": len(raw), "maximumBytes": 600000,
        "costUsd": 0, "cumulativeNbaCorpusGets": 3, "cumulativeNbaCorpusBytes": 33661132 + len(raw),
        "priorAllowancesReset": False, "accountsOrTrials": 0, "sportsbookCredits": 0,
        "outcomeColumnsLoaded": False, "comparativePerformanceExamined": False,
        "originalGamePublicationVintages": None,
        "qualification": "Export revision and today's capture are not contemporaneous game-information evidence."}
    pointer.write_bytes(json_bytes(receipt))
    print(json.dumps({"receipt": reference(pointer), "original": receipt["original"],
        "schemaColumns": schema.names, "metadataColumns": chosen, "metadataGroups": counts}, indent=2, default=str))


if __name__ == "__main__":
    main()
