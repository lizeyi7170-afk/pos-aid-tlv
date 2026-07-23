#!/usr/bin/env python3
"""Import Worldpay EMV Network Keys test CAPKs from its tabular PDF."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pdfplumber


DEFAULT_EXPIRATION = "20301231"
SOURCE_ID = "worldpay-emv-network-keys-test4"
SCHEMES = {
    "A000000003": ("visa", "Visa"),
    "A000000004": ("mastercard", "Mastercard"),
    "A000000025": ("american-express", "American Express"),
    "A000000152": ("discover", "Discover"),
    "A000000065": ("jcb", "JCB"),
    "A000000333": ("unionpay", "China UnionPay"),
    "A000000768": ("wex", "WEX"),
    "A000000277": ("interac", "Interac"),
}
FIELD_NAMES = {
    "RID",
    "CAPK Index",
    "Expiry Date",
    "CAPK Modulus",
    "CAPK Exponent",
    "Hash Value",
}
REQUIRED_FIELDS = FIELD_NAMES
EXCLUDED_IDENTITIES = {
    ("A000000003", "10"),
}


def compact(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def normalize_expiration(value: str) -> tuple[str, str]:
    raw = compact(value)
    if raw == "TBD":
        return DEFAULT_EXPIRATION, "skill-default"
    if not re.fullmatch(r"\d{8}", raw):
        raise ValueError(f"unsupported expiration value {value!r}")
    month, day, year = int(raw[:2]), int(raw[2:4]), int(raw[4:])
    parsed = date(year, month, day)
    return parsed.strftime("%Y%m%d"), "authoritative"


def checksum(rid: str, index: str, modulus: str, exponent: str) -> str:
    exponent_bytes = bytes.fromhex(exponent).lstrip(b"\x00") or b"\x00"
    payload = bytes.fromhex(rid + index + modulus) + exponent_bytes
    return hashlib.sha1(payload).hexdigest().upper()


def extract_raw_records(pdf_path: Path) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    current: Optional[Dict[str, object]] = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages[4:], start=5):
            for table in page.extract_tables():
                for row in table:
                    if not row or len(row) < 2:
                        continue
                    label = " ".join((row[0] or "").split())
                    raw_value = row[1] or ""
                    if label == "RID":
                        if current is not None:
                            records.append(current)
                        current = {"_pages": set()}
                    if current is None:
                        continue
                    current["_pages"].add(page_number)  # type: ignore[union-attr]
                    if label in FIELD_NAMES:
                        current[label] = compact(raw_value)
                    elif label == "Note":
                        current["Note"] = " ".join(raw_value.split())

    if current is not None:
        records.append(current)
    return records


def normalize_record(raw: Dict[str, object]) -> Dict[str, object]:
    missing = sorted(field for field in REQUIRED_FIELDS if not raw.get(field))
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
    checksum_verified = supplied_checksum == expected_checksum
    matching_indexes: List[str] = []
    if not checksum_verified:
        matching_indexes = [
            f"{candidate:02X}"
            for candidate in range(256)
            if checksum(rid, f"{candidate:02X}", modulus, exponent)
            == supplied_checksum
        ]

    expiration, expiration_source = normalize_expiration(source_expiration)
    scheme_id, scheme = SCHEMES[rid]
    notes: List[str] = []
    if raw.get("Note"):
        notes.append(str(raw["Note"]))
    if not checksum_verified:
        detail = (
            f"Source checksum does not match its stated RID/index; computed checksum "
            f"is {expected_checksum}."
        )
        if matching_indexes:
            detail += (
                " The supplied checksum matches the same key material at index "
                + ", ".join(matching_indexes)
                + "."
            )
        notes.append(detail)
    if expiration_source == "skill-default":
        notes.append(
            f"Source expiration is {source_expiration}; DF05 defaults to {DEFAULT_EXPIRATION} "
            "under the pos-aid-tlv skill policy."
        )
    pages = sorted(raw["_pages"])  # type: ignore[arg-type]
    return {
        "id": f"worldpay-test-{rid.lower()}-{index.lower()}",
        "scheme_id": scheme_id,
        "scheme": scheme,
        "rid": rid,
        "index": index,
        "environment": "test",
        "usage": "test-only",
        "processor": "worldpay",
        "profile": "EMVNetworkKeys_Test4",
        "key_bits": len(modulus) // 2 * 8,
        "modulus": modulus,
        "exponent": exponent,
        "checksum": supplied_checksum,
        "computed_checksum": expected_checksum,
        "checksum_verification": "verified" if checksum_verified else "source-mismatch",
        "checksum_matching_indexes": matching_indexes,
        "expiration": expiration,
        "expiration_source": expiration_source,
        "source_expiration": source_expiration,
        "hash_algorithm": "01",
        "public_key_algorithm": "01",
        "source_id": SOURCE_ID,
        "source_pages": pages,
        "notes": notes,
    }


def build_catalog(pdf_path: Path, source_url: str, retrieved_at: str) -> Dict[str, object]:
    records = [
        record
        for record in (
            normalize_record(raw_record) for raw_record in extract_raw_records(pdf_path)
        )
        if (record["rid"], record["index"]) not in EXCLUDED_IDENTITIES
    ]
    identities = [(record["rid"], record["index"]) for record in records]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate RID/index identity in imported PDF")
    return {
        "schema_version": 1,
        "catalog_name": "Worldpay EMV Network Keys Test4 CAPK catalog",
        "environment": "test",
        "usage": "test-only",
        "sources": {
            SOURCE_ID: {
                "title": "EMV Network Keys: Test",
                "publisher": "Worldpay",
                "profile": "EMVNetworkKeys_Test4",
                "url": source_url,
                "retrieved_at": retrieved_at,
                "document_pages": 14,
            }
        },
        "records": records,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--source-url",
        default="https://docs.worldpay.com/assets/pdf/EMVNetworkKeys_Test4.pdf",
    )
    parser.add_argument("--retrieved-at", default=date.today().isoformat())
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    catalog = build_catalog(args.pdf, args.source_url, args.retrieved_at)
    output = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    print(
        f"Imported {len(catalog['records'])} test CAPK record(s).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
