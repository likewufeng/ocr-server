"""Import China BIN/IIN records from the MIT-licensed card-bin-db package archive."""

import argparse
import csv
import io
import json
import tarfile
from pathlib import Path
from typing import Dict, Iterable
from urllib.parse import unquote


ARCHIVE_MEMBER = "package/bindb/bincheck.csv"
SOURCE_NAME = "card-bin-db/bincheck.csv"
SOURCE_VERSION = "card-bin-db@1.0.2"
SOURCE_URL = "https://github.com/checkv4/card-bin-db"


def expand_prefixes(value: str) -> Iterable[str]:
    for item in value.split("/"):
        item = item.strip()
        if len(item) == 6 and item.isdigit():
            yield item
            continue
        if len(item) != 13 or item[6] != "-":
            continue
        start, end = item.split("-", 1)
        if not (start.isdigit() and end.isdigit() and len(start) == len(end) == 6):
            continue
        start_number, end_number = int(start), int(end)
        if start_number > end_number or end_number - start_number > 100_000:
            continue
        for number in range(start_number, end_number + 1):
            yield f"{number:06d}"


def card_type(value: str) -> str:
    value = value.strip().upper()
    return value if value in {"DEBIT", "CREDIT"} else ""


def build_records(archive_path: Path) -> Dict[str, Dict[str, str]]:
    records: Dict[str, Dict[str, str]] = {}
    with tarfile.open(archive_path, "r:gz") as archive:
        member = archive.extractfile(ARCHIVE_MEMBER)
        if member is None:
            raise RuntimeError(f"Missing {ARCHIVE_MEMBER} in {archive_path}")
        reader = csv.reader(io.TextIOWrapper(member, encoding="utf-8"))
        for row in reader:
            # The final fields are stable even where older source rows contain
            # unquoted commas in issuer names.
            if len(row) < 11 or row[-3].strip() != "CN":
                continue
            prefix_value = row[0].strip()
            issuer = unquote(row[4]).strip()
            if not issuer:
                continue
            for prefix in expand_prefixes(prefix_value):
                records.setdefault(
                    prefix,
                    {
                        "prefix": prefix,
                        "bank_name": issuer,
                        "card_type": card_type(row[2]),
                    },
                )
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path, help="card-bin-db .tgz package archive")
    parser.add_argument("output", type=Path, help="generated local IIN JSON file")
    args = parser.parse_args()

    records = build_records(args.archive)
    payload = {
        "schema_version": "1",
        "source": SOURCE_NAME,
        "source_version": SOURCE_VERSION,
        "source_license": "MIT package; verify upstream data terms before commercial redistribution",
        "source_url": SOURCE_URL,
        "country_code": "CN",
        "records": [records[prefix] for prefix in sorted(records)],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Imported {len(records)} China IIN records into {args.output}")


if __name__ == "__main__":
    main()
