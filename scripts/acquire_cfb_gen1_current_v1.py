from __future__ import annotations

import argparse
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import dotenv_values


OUTPUT_ROOT = Path("outputs/cfb-gen1-current-v1")
API_ROOT = "https://api.collegefootballdata.com"
MAX_API_CALLS = 25
MAX_RESPONSE_BYTES = 50 * 1024 * 1024
USER_AGENT = "asp-model-studio-cfb-gen1-current-private-research/1.0"
DOCS = {
    "terms.html": "https://collegefootballdata.com/terms",
    "authentication.html": "https://apinext.collegefootballdata.com/authentication",
    "usage-and-access.html": "https://apinext.collegefootballdata.com/usage-and-access",
    "games-api.html": "https://apinext.collegefootballdata.com/api/games",
    "teams-api.html": "https://apinext.collegefootballdata.com/api/teams",
    "info-api.html": "https://apinext.collegefootballdata.com/api/info",
}
SAFE_HEADERS = {
    "content-type", "content-length", "date", "etag", "last-modified",
    "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def write_exact(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    if path.read_bytes() != value:
        raise RuntimeError(f"exact-byte replay failed for {path}")


def schema_profile(value: Any) -> Any:
    if isinstance(value, list):
        item_types = sorted({_type_name(item) for item in value})
        profile: dict[str, Any] = {"type": "array", "length": len(value), "itemTypes": item_types}
        dict_items = [item for item in value if isinstance(item, dict)]
        if dict_items:
            keys = sorted({key for item in dict_items for key in item})
            profile["itemFields"] = {
                key: sorted({_type_name(item.get(key)) for item in dict_items if key in item})
                for key in keys
            }
        return profile
    if isinstance(value, dict):
        return {"type": "object", "fields": {key: schema_profile(item) for key, item in sorted(value.items())}}
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def load_key(env_path: Path) -> str:
    value = dotenv_values(env_path).get("CFBD_API_KEY")
    if not value or not str(value).strip():
        raise RuntimeError(f"CFBD_API_KEY is absent from secure local environment {env_path.resolve()}")
    return str(value).strip()


class Intake:
    def __init__(self, output_root: Path, key: str) -> None:
        self.output_root = output_root
        self.key = key
        self.calls = 0
        self.api_bytes = 0
        self.ledger: list[dict[str, Any]] = []

    def _fetch(self, url: str, authenticated: bool) -> tuple[bytes, int, dict[str, str]]:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.key}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read()
                status = int(response.status)
                response_headers = {
                    key.casefold(): value for key, value in response.headers.items()
                    if key.casefold() in SAFE_HEADERS
                }
        except urllib.error.HTTPError as error:
            raw = error.read()
            status = int(error.code)
            response_headers = {
                key.casefold(): value for key, value in error.headers.items()
                if key.casefold() in SAFE_HEADERS
            }
        return raw, status, response_headers

    def api(self, label: str, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        if self.calls >= MAX_API_CALLS:
            raise RuntimeError("CFBD assignment call cap reached before request")
        query = urllib.parse.urlencode(params or {})
        url = f"{API_ROOT}{endpoint}" + (f"?{query}" if query else "")
        acquired_at = utc_now()
        raw, status, headers = self._fetch(url, authenticated=True)
        self.calls += 1
        self.api_bytes += len(raw)
        if self.api_bytes > MAX_RESPONSE_BYTES:
            raise RuntimeError("CFBD assignment response-byte cap exceeded")
        path = self.output_root / "private-sources" / "cfbd" / f"{label}.json"
        write_exact(path, raw)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"CFBD {endpoint} returned non-JSON status {status}") from exc
        self.ledger.append({
            "sequence": self.calls,
            "endpoint": endpoint,
            "parameters": params or {},
            "httpStatus": status,
            "responseHeaders": headers,
            "acquiredAt": acquired_at,
            "path": str(path.resolve()),
            "bytes": len(raw),
            "physicalSha256": sha256_bytes(raw),
            "rowCount": len(parsed) if isinstance(parsed, list) else 1,
            "schemaProfile": schema_profile(parsed),
        })
        if status != 200:
            raise RuntimeError(f"CFBD {endpoint} returned HTTP {status}; body retained privately")
        return parsed


def acquire(output_root: Path, env_path: Path) -> dict[str, Any]:
    key = load_key(env_path)
    intake = Intake(output_root, key)

    terms_evidence = []
    for name, url in DOCS.items():
        acquired_at = utc_now()
        raw, status, headers = intake._fetch(url, authenticated=False)
        if status != 200:
            raise RuntimeError(f"official documentation request failed: {url} status {status}")
        path = output_root / "terms-evidence" / name
        write_exact(path, raw)
        terms_evidence.append({
            "name": name, "url": url, "httpStatus": status, "responseHeaders": headers,
            "acquiredAt": acquired_at, "path": str(path.resolve()), "bytes": len(raw),
            "physicalSha256": sha256_bytes(raw),
        })

    before = intake.api("account-before", "/info")
    remaining_before = before.get("remainingCalls") if isinstance(before, dict) else None
    if remaining_before is not None and int(remaining_before) < 8:
        raise RuntimeError(f"CFBD remaining shared quota {remaining_before} is below bounded intake minimum 8")
    intake.api("shared-usage-before", "/info/usage", {"days": 31, "limit": 50, "api": "all"})
    teams = intake.api("fbs-teams-2026", "/teams/fbs", {"year": 2026})
    games = intake.api("games-2026", "/games", {"year": 2026})
    intake.api("calendar-2026", "/calendar", {"year": 2026})

    completed_regular_weeks = sorted({
        int(game["week"]) for game in games
        if game.get("completed") and game.get("seasonType") == "regular"
    })
    projected_total_calls = intake.calls + len(completed_regular_weeks) + 1
    if projected_total_calls > MAX_API_CALLS:
        raise RuntimeError(
            f"CFBD bounded intake would require {projected_total_calls} calls, above cap {MAX_API_CALLS}"
        )
    if remaining_before is not None and int(remaining_before) < projected_total_calls:
        raise RuntimeError(
            f"CFBD remaining shared quota {remaining_before} is below projected intake {projected_total_calls}"
        )
    for week in completed_regular_weeks:
        intake.api(
            f"team-game-stats-2026-regular-week-{week:02d}",
            "/games/teams",
            {"year": 2026, "week": week, "seasonType": "regular"},
        )
    after = intake.api("account-after", "/info")

    manifest = {
        "schemaVersion": "CFB_GEN1_CURRENT_CFBD_SOURCE_MANIFEST_V1",
        "createdAt": utc_now(),
        "provider": "CollegeFootballData",
        "baseUrl": API_ROOT,
        "season": 2026,
        "credentialSource": str(env_path.resolve()),
        "credentialRetained": False,
        "authorization": "Bearer header; never URL or serialized output",
        "limits": {"maximumCalls": MAX_API_CALLS, "maximumResponseBytes": MAX_RESPONSE_BYTES, "incrementalCostUsd": 0},
        "usage": {
            "calls": intake.calls,
            "responseBytes": intake.api_bytes,
            "incrementalCostUsd": 0,
            "remainingCallsBefore": remaining_before,
            "remainingCallsAfter": after.get("remainingCalls") if isinstance(after, dict) else None,
            "monthlyLimit": after.get("monthlyLimit") if isinstance(after, dict) else None,
            "sharedPool": after.get("sharedPool") if isinstance(after, dict) else None,
            "resetAt": after.get("resetAt") if isinstance(after, dict) else None,
        },
        "completedRegularWeeksRequested": completed_regular_weeks,
        "requests": intake.ledger,
        "termsEvidence": terms_evidence,
        "availabilityBoundary": "No per-record publication/revision timestamp is supplied; acquisition time is the availability boundary.",
        "rawResponsePolicy": "Private Model Studio source store only; excluded from exchange and source control.",
    }
    manifest_path = output_root / "cfbd-source-manifest.json"
    write_exact(manifest_path, json.dumps(manifest, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2).encode("utf-8"))
    locator = {
        "schemaVersion": "CFB_GEN1_CURRENT_CFBD_SOURCE_LOCATOR_V1",
        "path": str(manifest_path.resolve()),
        "bytes": manifest_path.stat().st_size,
        "physicalSha256": sha256_bytes(manifest_path.read_bytes()),
        "contentSha256": sha256_bytes(canonical_json(manifest)),
        "calls": intake.calls,
        "responseBytes": intake.api_bytes,
        "remainingCalls": manifest["usage"]["remainingCallsAfter"],
    }
    locator_path = output_root / "cfbd-source-manifest-locator.json"
    write_exact(locator_path, json.dumps(locator, sort_keys=True, indent=2).encode("utf-8"))
    return locator


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--env-file", type=Path, default=Path(".env.local"))
    args = parser.parse_args()
    result = acquire(args.output_root, args.env_file)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
