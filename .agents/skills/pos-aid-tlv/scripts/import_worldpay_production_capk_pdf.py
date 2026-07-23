#!/usr/bin/env python3
"""Import Worldpay EMV Network Keys Production3 CAPKs from its tabular PDF."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pdfplumber

from import_worldpay_capk_pdf import SCHEMES, checksum, compact, normalize_expiration


SOURCE_ID = "worldpay-emv-network-keys-production3"
PROFILE = "EMVNetworkKeys_Production3"
SOURCE_URL = "https://docs.worldpay.com/assets/pdf/EMVNetworkKeys_Production3.pdf"
FIELD_NAMES = {
    "RID",
    "CAPK Index",
    "Expiry Date",
    "CAPK Modulus",
    "CAPK Exponent",
    "Hash Value",
}


def extract_raw_records(pdf_path: Path) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    current: Optional[Dict[str, object]] = None

    with pdfplumber.open(pdf_path) as pdf:
        if len(pdf.pages) != 8:
            raise ValueError(f"expected 8 PDF pages, got {len(pdf.pages)}")
        for page_number, page in enumerate(pdf.pages[3:], start=4):
            for table in page.extract_tables():
                for row in table:
                    if not row or len(row) < 2:
                        continue
                    label = " ".join((row[0] or "").split())
                    value = row[1] or ""
                    if label == "RID":
                        if current is not None:
                            records.append(current)
                        current = {"_pages": set()}
                    if current is None:
                        continue
                    current["_pages"].add(page_number)  # type: ignore[union-attr]
                    if label in FIELD_NAMES:
                        current[label] = compact(value)

    if current is not None:
        records.append(current)
    return records


def normalize_record(raw: Dict[str, object]) -> Dict[str, object]:
    missing = sorted(field for field in FIELD_NAMES if not raw.get(field))
    if missing:
        raise ValueError(f"incomplete PDF CAPK record: missing {', '.join(missing)}")

    rid = str(raw["RID"])
    index = str(raw["CAPK Index"])
    source_expiration = str(raw["Expiry Date"])
    modulus = str(raw["CAPK Modulus"])
    exponent = str(raw["CAPK Exponent"])
    supplied_checksum = str(raw["Hash Value"])
    if rid not in SCHEMES:
        raise ValueError(f"unmapped Worldpay RID {rid}")
    for name, value in {
        "RID": rid,
        "index": index,
        "modulus": modulus,
        "exponent": exponent,
        "checksum": supplied_checksum,
    }.items():
        if len(value) % 2 or not re.fullmatch(r"[0-9A-F]+", value):
            raise ValueError(f"{name} is not even-length hexadecimal")
    if len(rid) != 10 or len(index) != 2:
        raise ValueError(f"invalid CAPK identity RID={rid}, index={index}")
    if not 1 <= len(modulus) // 2 <= 248:
        raise ValueError(f"invalid modulus length for RID={rid}, index={index}")
    if exponent not in {"03", "000003", "010001"}:
        raise ValueError(f"unexpected exponent {exponent} for RID={rid}, index={index}")

    expected_checksum = checksum(rid, index, modulus, exponent)
    if supplied_checksum != expected_checksum:
        raise ValueError(
            f"source checksum mismatch for RID={rid}, index={index}: "
            f"supplied {supplied_checksum}, computed {expected_checksum}"
        )
    expiration, expiration_source = normalize_expiration(source_expiration)
    if expiration_source != "authoritative":
        raise ValueError(f"production expiration is not authoritative for RID={rid}, index={index}")

    scheme_id, scheme = SCHEMES[rid]
    notes: List[str] = []
    if rid == "A000000003" and index == "10":
        notes.append(
            "This key must only be used for Urban Mobility & Transport Transaction (MTT)."
        )
    return {
        "id": f"worldpay-production-{rid.lower()}-{index.lower()}",
        "scheme_id": scheme_id,
        "scheme": scheme,
        "rid": rid,
        "index": index,
        "environment": "production",
        "usage": "production",
        "processor": "worldpay",
        "profile": PROFILE,
        "key_bits": len(modulus) // 2 * 8,
        "modulus": modulus,
        "exponent": exponent,
        "checksum": supplied_checksum,
        "computed_checksum": expected_checksum,
        "checksum_verification": "verified",
        "checksum_matching_indexes": [],
        "expiration": expiration,
        "expiration_source": expiration_source,
        "source_expiration": source_expiration,
        "hash_algorithm": "01",
        "public_key_algorithm": "01",
        "source_id": SOURCE_ID,
        "source_pages": sorted(raw["_pages"]),  # type: ignore[arg-type]
        "notes": notes,
    }


def build_import(pdf_path: Path, source_url: str, retrieved_at: str) -> Dict[str, object]:
    records = [normalize_record(record) for record in extract_raw_records(pdf_path)]
    identities = [(record["rid"], record["index"]) for record in records]
    if len(records) != 10:
        raise ValueError(f"expected 10 production CAPKs, got {len(records)}")
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate RID/index identity in imported PDF")
    return {
        "source": {
            "id": SOURCE_ID,
            "title": "EMV Network Keys: Production",
            "publisher": "Worldpay",
            "profile": PROFILE,
            "url": source_url,
            "retrieved_at": retrieved_at,
            "document_pages": 8,
        },
        "records": records,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--retrieved-at", default=date.today().isoformat())
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    imported = build_import(args.pdf, args.source_url, args.retrieved_at)
    output = json.dumps(imported, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    print(f"Imported {len(imported['records'])} production CAPK record(s).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
