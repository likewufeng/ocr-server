"""Merge verified incremental China IIN records from binlist-data CSV.

Existing project records are never replaced. The source contains many rows
without an issuer, so only usable 6/8-digit China debit/credit rows are added.
"""

import argparse
import csv
import json
import shutil
from pathlib import Path
from typing import Dict, Optional


BINLIST_SOURCE = "iannuttall/binlist-data"
BINLIST_URL = "https://github.com/iannuttall/binlist-data"
BINLIST_LICENSE = "CC BY 4.0"


def usable_record(row: Dict[str, str]) -> Optional[Dict[str, str]]:
    if row.get("alpha_2", "").strip().upper() != "CN":
        return None
    prefix = row.get("bin", "").strip()
    issuer = row.get("issuer", "").strip()
    card_type = row.get("type", "").strip().upper()
    if len(prefix) not in (6, 8) or not prefix.isdigit() or not issuer:
        return None
    if card_type not in {"DEBIT", "CREDIT"}:
        return None
    return {"prefix": prefix, "bank_name": issuer, "card_type": card_type}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge usable China IIN increments from binlist-data CSV"
    )
    parser.add_argument("--catalog", type=Path, required=True, help="existing IIN JSON")
    parser.add_argument("--csv", type=Path, required=True, help="binlist-data.csv")
    parser.add_argument("--output", type=Path, help="output JSON; defaults to catalog")
    args = parser.parse_args()

    output = args.output or args.catalog
    with args.catalog.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    records = payload.get("records")
    if not isinstance(records, list):
        raise SystemExit("catalog must contain a records list")

    by_prefix = {str(record.get("prefix", "")): record for record in records}
    added = 0
    with args.csv.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            record = usable_record(row)
            if record is None or record["prefix"] in by_prefix:
                continue
            record["source"] = BINLIST_SOURCE
            by_prefix[record["prefix"]] = record
            added += 1

    previous_sources = payload.get("sources")
    if not isinstance(previous_sources, list):
        previous_sources = [
            {
                "name": payload.get("source", "unknown"),
                "version": payload.get("source_version", "unknown"),
                "license": payload.get("source_license", "unknown"),
                "url": payload.get("source_url", ""),
            }
        ]
    if not any(item.get("name") == BINLIST_SOURCE for item in previous_sources):
        previous_sources.append(
            {
                "name": BINLIST_SOURCE,
                "version": "local snapshot",
                "license": BINLIST_LICENSE,
                "url": BINLIST_URL,
            }
        )

    result = {
        "schema_version": "2",
        "sources": previous_sources,
        "country_code": "CN",
        "records": [by_prefix[prefix] for prefix in sorted(by_prefix)],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.resolve() == args.catalog.resolve():
        backup = args.catalog.with_suffix(".json.bak")
        shutil.copy2(args.catalog, backup)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("merged_records={} total_records={} output={}".format(added, len(by_prefix), output))


if __name__ == "__main__":
    main()
