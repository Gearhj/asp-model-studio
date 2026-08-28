"""Bronze acquisition CLI. Standalone; NO ASP imports.

    python -m tools.bronze_acquisition.acquire --source chadwick --staging-root <root>
    python -m tools.bronze_acquisition.acquire --source statcast --start-year 2024 --end-year 2024 [--max-partitions N]

Legacy year planners refuse any year > 2024. The explicit ``--start-date`` / ``--end-date`` Statcast path
is separately bounded through 2026-08-27. Resumable: verified partitions are skipped. Data lands ONLY under
the external staging root; nothing is joined, engineered, or modeled.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import CURRENT_STATCAST_MAX_DATE, MAX_YEAR, MIN_YEAR
from .download import http_download, sha256_file
from .manifest import BronzeManifest, inspect_csv, utc_now
from .safety import BronzeBoundaryError, contained_path, redact, safe_extract_zip, safe_filename
from .sources import PLANNERS, current_statcast_partitions

SOURCE_TERMS = {
    "statcast": {"owner": "MLB Advanced Media / Baseball Savant", "location": "https://baseballsavant.mlb.com",
                 "terms": "https://www.mlb.com/official-information/terms-of-use",
                 "classification": ["PUBLIC RESEARCH SOURCE", "ATTRIBUTION REQUIRED", "COMMERCIAL RIGHTS UNCLEAR"]},
    "retrosheet": {"owner": "Retrosheet", "location": "https://www.retrosheet.org",
                   "terms": "https://www.retrosheet.org/notice.txt",
                   "classification": ["PUBLIC RESEARCH SOURCE", "ATTRIBUTION REQUIRED"],
                   "notice": "The information used here was obtained free of charge from and is copyrighted by Retrosheet."},
    "chadwick": {"owner": "Chadwick Baseball Bureau", "location": "https://github.com/chadwickbureau/register",
                 "terms": "https://github.com/chadwickbureau/register (see repository LICENSE)",
                 "classification": ["PUBLIC RESEARCH SOURCE", "ATTRIBUTION REQUIRED"]},
    "lahman": {"owner": "Sean Lahman / Chadwick Baseball Bureau (baseballdatabank)",
               "location": "https://github.com/chadwickbureau/baseballdatabank",
               "terms": "CC BY-SA 3.0 (see repository)",
               "classification": ["PUBLIC RESEARCH SOURCE", "ATTRIBUTION REQUIRED"]},
}


def _log_file(root: Path):
    lp = root / "logs" / f"acquire-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}.log"
    lp.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lp, "a", encoding="utf-8")

    def log(msg: str) -> None:
        line = f"[{utc_now()}] {redact(str(msg))}"
        print(line, flush=True)
        fh.write(line + "\n"); fh.flush()
    return log


def _record_terms(root: Path, source: str, log) -> None:
    terms = SOURCE_TERMS.get(source)
    if not terms:
        return
    p = contained_path(root, "source-terms", f"{source}.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    import json
    p.write_text(json.dumps({"source": source, "retrievedAtUtc": utc_now(), **terms}, indent=2), encoding="utf-8")


def acquire(source: str, *, staging_root: Path, start_year: int, end_year: int, max_partitions: int | None,
            dry_run: bool, start_date: str | None = None, end_date: str | None = None,
            statcast_scope: str = "regular") -> dict:
    if source not in PLANNERS:
        raise BronzeBoundaryError(f"unknown source {source!r}")
    date_mode = start_date is not None or end_date is not None
    if date_mode:
        if source != "statcast" or not start_date or not end_date:
            raise BronzeBoundaryError("the date-bounded extension requires Statcast plus both --start-date and --end-date")
    elif end_year > MAX_YEAR or start_year < MIN_YEAR:
        raise BronzeBoundaryError(f"year window must be within [{MIN_YEAR}, {MAX_YEAR}] — use the explicit current Statcast date path")
    root = Path(staging_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    log = _log_file(root)
    _record_terms(root, source, log)
    manifest = BronzeManifest(root)
    partitions = (
        current_statcast_partitions(start_date, end_date, scope=statcast_scope)
        if date_mode else PLANNERS[source](start_year=start_year, end_year=end_year)
    )
    if max_partitions:
        partitions = partitions[:max_partitions]
    window = f"[{start_date},{end_date}]" if date_mode else f"[{start_year},{end_year}]"
    log(f"source={source} window={window} partitions={len(partitions)} dry_run={dry_run}")
    done = skipped = failed = 0
    for part in partitions:
        if manifest.has_valid(part.partition_id):
            skipped += 1
            log(f"skip (verified) {part.partition_id}")
            continue
        if dry_run:
            log(f"plan {part.partition_id} -> {redact(part.url)}")
            continue
        dest = contained_path(root, *Path(part.rel_dir).parts, safe_filename(part.filename))
        try:
            receipt = http_download(part.url, dest, log=log)
            record = {
                "partitionId": part.partition_id, "source": source, "scope": part.scope,
                "sourceUrlDomain": part.url.split("/")[2], "year": part.year, "query": part.query,
                "retrievalUtc": utc_now(), "toolVersion": "1.1", "httpStatus": receipt["status"],
                "attempts": receipt["attempts"], "reused": receipt["reused"],
                "rawFilename": dest.name, "relativePath": str(dest.relative_to(root)).replace("\\", "/"),
                "fileSizeBytes": receipt["bytes"], "fileSha256": receipt["sha256"],
                "license": SOURCE_TERMS.get(source, {}).get("classification"), "status": "COMPLETE",
            }
            if part.is_archive:
                extract_dir = contained_path(root, *Path(part.rel_dir).parts, part.filename.rsplit(".", 1)[0])
                members = safe_extract_zip(dest, extract_dir)
                record["archiveMemberCount"] = len(members)
                record["archiveMembers"] = members[:200]
                record["archiveMemberSha256"] = {m: sha256_file(extract_dir / m) for m in members[:200]}
            else:
                record.update(inspect_csv(dest, natural_keys=part.natural_keys, date_col=part.date_col))
                if part.date_col and record.get("maxDate"):
                    md = str(record["maxDate"])[:4]
                    if md.isdigit() and not date_mode and int(md) > MAX_YEAR:
                        record["status"] = "QUARANTINE_LATER_YEAR"
                        record["anomaly"] = f"maxDate {record['maxDate']} exceeds {MAX_YEAR}"
                    elif date_mode and (record.get("minDate") != part.query["date"] or record.get("maxDate") != part.query["date"]):
                        record["status"] = "QUARANTINE_DATE_MISMATCH"
                        record["anomaly"] = (
                            f"partition {part.partition_id} returned dates "
                            f"[{record.get('minDate')}, {record.get('maxDate')}]"
                        )
                if source == "statcast":
                    from .sources import STATCAST_ROW_CAP
                    if int(record.get("rowCount", 0)) >= STATCAST_ROW_CAP:
                        record["status"] = "TRUNCATED_CAP_HIT"
                        record["anomaly"] = f"rowCount {record['rowCount']} hit the Savant {STATCAST_ROW_CAP} cap; subdivide"
                    elif int(record.get("rowCount", 0)) == 0:
                        record["status"] = "COMPLETE_EMPTY"
            manifest.upsert(record)
            manifest.write()
            done += 1
            log(f"done {part.partition_id} rows={record.get('rowCount','-')} bytes={receipt['bytes']} sha={receipt['sha256'][:12]}")
        except Exception as exc:  # keep completed partitions; record the failure
            failed += 1
            manifest.upsert({"partitionId": part.partition_id, "source": source, "scope": part.scope,
                             "status": "FAILED", "retrievalUtc": utc_now(), "error": redact(str(exc))[:400]})
            manifest.write()
            log(f"FAIL {part.partition_id}: {redact(str(exc))[:200]}")
    sha = manifest.write()
    log(f"COMPLETE source={source} done={done} skipped={skipped} failed={failed} manifestSha={sha}")
    return {"source": source, "done": done, "skipped": skipped, "failed": failed, "manifestSha256": sha,
            "partitionsPlanned": len(partitions)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Quarantined MLB Bronze acquisition")
    ap.add_argument("--source", required=True, choices=sorted(PLANNERS))
    ap.add_argument("--staging-root", default=r"C:\Users\james\asp-data-staging\mlb-advanced-bronze-v1")
    ap.add_argument("--start-year", type=int, default=MIN_YEAR)
    ap.add_argument("--end-year", type=int, default=MAX_YEAR)
    ap.add_argument("--start-date", help="Explicit current Statcast start date (YYYY-MM-DD)")
    ap.add_argument("--end-date", help=f"Explicit current Statcast end date, at most {CURRENT_STATCAST_MAX_DATE}")
    ap.add_argument("--statcast-scope", choices=("regular", "postseason"), default="regular")
    ap.add_argument("--max-partitions", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        out = acquire(a.source, staging_root=Path(a.staging_root), start_year=a.start_year, end_year=a.end_year,
                      max_partitions=a.max_partitions, dry_run=a.dry_run, start_date=a.start_date,
                      end_date=a.end_date, statcast_scope=a.statcast_scope)
    except BronzeBoundaryError as exc:
        print(f"BRONZE BOUNDARY REFUSED: {exc}", file=sys.stderr)
        return 2
    import json
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
