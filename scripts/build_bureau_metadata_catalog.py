"""Build one exact restricted bureau-metadata catalog outside the repository.

The canonical PDF, CSV staging file, optional parser configuration, and output
root are all explicit absolute paths.  The command prints only aggregate build
metadata; source-derived definitions remain in the restricted external output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.bureau_metadata.catalog_builder import (  # noqa: E402
    CatalogBuildConfig,
    build_catalog,
)
from server.bureau_metadata.csv_parser import CsvParserConfig  # noqa: E402
from server.bureau_metadata.pdf_parser import PdfParserConfig  # noqa: E402
from server.bureau_metadata.source_reader import (  # noqa: E402
    inspect_external_source,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True, help="Exact canonical PDF path.")
    parser.add_argument("--csv", type=Path, required=True, help="Exact CSV staging path.")
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help=(
            "External restricted root. The immutable catalog is published at "
            "catalogs/<catalog-key-digest>/<catalog-checksum>/ beneath this root."
        ),
    )
    parser.add_argument("--provider", required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--edition", required=True)
    parser.add_argument("--dictionary-version", required=True)
    parser.add_argument("--policy-id", required=True)
    parser.add_argument("--policy-version", required=True)
    parser.add_argument("--built-by", required=True)
    parser.add_argument("--source-control-commit", required=True)
    parser.add_argument("--catalog-id")
    parser.add_argument(
        "--built-at",
        help=(
            "Optional explicit RFC-3339 timestamp; omitted timestamps are "
            "generated once per build."
        ),
    )
    parser.add_argument(
        "--parser-config",
        type=Path,
        help="Optional external JSON containing `csv`, `pdf`, or `special_value_pattern` settings.",
    )
    return parser


def _safe_error(error_type: str) -> str:
    return json.dumps(
        {
            "ok": False,
            "error_type": error_type,
            "error": "catalog build did not complete; consult restricted diagnostics",
        },
        sort_keys=True,
    )


def _read_parser_config(path: Path | None) -> Mapping[str, Any]:
    if path is None:
        return {}
    descriptor = inspect_external_source(
        path,
        role="parser configuration",
        expected_suffixes=(".json",),
    )
    try:
        payload = json.loads(descriptor.path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("parser configuration is unavailable or malformed") from exc
    if not isinstance(payload, dict):
        raise ValueError("parser configuration must be a JSON object")
    allowed = {"csv", "pdf", "special_value_pattern"}
    if set(payload) - allowed:
        raise ValueError("parser configuration contains unsupported sections")
    return payload


def _mapping_section(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    section = payload.get(key, {})
    if not isinstance(section, dict):
        raise ValueError(f"parser configuration section '{key}' must be an object")
    return dict(section)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        parser_payload = _read_parser_config(args.parser_config)
        csv_config = CsvParserConfig(**_mapping_section(parser_payload, "csv"))
        pdf_config = PdfParserConfig(**_mapping_section(parser_payload, "pdf"))
        special_pattern = parser_payload.get("special_value_pattern")
        config_options: dict[str, Any] = {
            "provider": args.provider,
            "product": args.product,
            "edition": args.edition,
            "dictionary_version": args.dictionary_version,
            "policy_id": args.policy_id,
            "policy_version": args.policy_version,
            "built_by": args.built_by,
            "source_control_commit": args.source_control_commit,
            "catalog_id": args.catalog_id,
            "built_at": args.built_at,
            "csv_parser": csv_config,
            "pdf_parser": pdf_config,
        }
        if special_pattern is not None:
            if not isinstance(special_pattern, str):
                raise ValueError("special_value_pattern must be a string")
            config_options["special_value_pattern"] = special_pattern
        result = build_catalog(
            pdf_path=args.pdf,
            csv_path=args.csv,
            output_directory=args.output_root,
            config=CatalogBuildConfig(**config_options),
        )
    except Exception as exc:
        # Never render exception text: PDF/CSV/config parser exceptions can
        # carry fragments from a restricted source.
        print(_safe_error(type(exc).__name__))
        return 2
    print(json.dumps(result.public_summary(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
