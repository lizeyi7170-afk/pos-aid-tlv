#!/usr/bin/env python3
"""Query, validate, and export complete CAPKs from the local catalog."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from aid_tlv import Tlv, encode_items, parse_tlv
from capk_tlv import validate_items


DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "references" / "capk-catalog.json"
SCHEME_ALIASES = {
    "visa": "visa",
    "vsdc": "visa",
    "mastercard": "mastercard",
    "master-card": "mastercard",
    "paypass": "mastercard",
    "american-express": "american-express",
    "americanexpress": "american-express",
    "amex": "american-express",
    "discover": "discover",
    "dpas": "discover",
    "jcb": "jcb",
    "unionpay": "unionpay",
    "china-unionpay": "unionpay",
    "cup": "unionpay",
    "upi": "unionpay",
    "银联": "unionpay",
    "wex": "wex",
    "interac": "interac",
}
TLV_FIELDS = (
    ("9F06", "rid"),
    ("9F22", "index"),
    ("DF02", "modulus"),
    ("DF04", "exponent"),
    ("DF03", "checksum"),
    ("DF05", "expiration"),
    ("DF06", "hash_algorithm"),
    ("DF07", "public_key_algorithm"),
)
REQUIRED_FIELDS = {
    "id",
    "scheme_id",
    "scheme",
    "rid",
    "index",
    "environment",
    "usage",
    "processor",
    "profile",
    "key_bits",
    "modulus",
    "exponent",
    "checksum",
    "computed_checksum",
    "checksum_verification",
    "expiration",
    "expiration_source",
    "hash_algorithm",
    "public_key_algorithm",
    "source_id",
}


class CatalogError(ValueError):
    pass


def load_catalog(path: Path) -> Dict[str, object]:
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"cannot load catalog {path}: {exc}") from exc
    if not isinstance(catalog, dict) or not isinstance(catalog.get("records"), list):
        raise CatalogError("catalog must contain a records array")
    return catalog


def canonical_scheme(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-").replace(" ", "-")
    return SCHEME_ALIASES.get(normalized, normalized)


def record_tlv(record: Dict[str, object]) -> str:
    if record.get("checksum_verification") != "verified":
        raise CatalogError(
            f"{record.get('rid')}/{record.get('index')}: source checksum is not "
            "verified; refusing to emit CAPK TLV"
        )
    items: List[Tlv] = []
    for tag_hex, field in TLV_FIELDS:
        value = str(record[field])
        items.append(Tlv(bytes.fromhex(tag_hex), bytes.fromhex(value), 0))
    return encode_items(items).hex().upper()


def validate_record(
    record: Dict[str, object],
    sources: Dict[str, object],
) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    missing = sorted(REQUIRED_FIELDS - set(record))
    if missing:
        return [f"missing catalog field {field}" for field in missing], warnings
    identity = f"{record['rid']}/{record['index']}"
    if record["environment"] == "test":
        if record["usage"] != "test-only":
            errors.append(f"{identity}: test record must use usage=test-only")
    elif record["environment"] == "production":
        if record["usage"] != "production":
            errors.append(f"{identity}: production record must use usage=production")
    else:
        errors.append(f"{identity}: unsupported environment {record['environment']}")
    if record["source_id"] not in sources:
        errors.append(f"{identity}: source_id {record['source_id']} is not declared")
    if record["expiration_source"] not in {"authoritative", "skill-default"}:
        errors.append(f"{identity}: unsupported expiration_source")
    try:
        expiration = datetime.strptime(str(record["expiration"]), "%Y%m%d").date()
        if expiration < date.today():
            warnings.append(f"{identity}: CAPK expired on {expiration.isoformat()}")
        if record["expiration_source"] == "skill-default":
            warnings.append(
                f"{identity}: expiration uses the skill default {record['expiration']}"
            )
    except ValueError:
        errors.append(f"{identity}: expiration must be a valid YYYYMMDD date")
    try:
        modulus = bytes.fromhex(str(record["modulus"]))
        if int(record["key_bits"]) != len(modulus) * 8:
            errors.append(f"{identity}: key_bits does not match modulus length")
        verification = record["checksum_verification"]
        if verification == "verified":
            if record["checksum"] != record["computed_checksum"]:
                errors.append(f"{identity}: verified checksum fields disagree")
            tlv = record_tlv(record)
            items = parse_tlv(bytes.fromhex(tlv))
            tlv_errors, tlv_warnings = validate_items(items)
            errors.extend(f"{identity}: {message}" for message in tlv_errors)
            warnings.extend(f"{identity}: {message}" for message in tlv_warnings)
        elif verification == "source-mismatch":
            if record["checksum"] == record["computed_checksum"]:
                errors.append(f"{identity}: source-mismatch fields unexpectedly agree")
            warnings.append(
                f"{identity}: source checksum mismatch; lookup will not emit a TLV"
            )
        else:
            errors.append(f"{identity}: unsupported checksum_verification")
    except (KeyError, ValueError) as exc:
        errors.append(f"{identity}: cannot build CAPK TLV: {exc}")
    return errors, warnings


def validate_catalog(catalog: Dict[str, object]) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    sources = catalog.get("sources")
    if not isinstance(sources, dict):
        return ["catalog must contain a sources object"], warnings
    records = catalog["records"]
    identities = set()
    ids = set()
    for raw_record in records:  # type: ignore[assignment]
        if not isinstance(raw_record, dict):
            errors.append("catalog records must be objects")
            continue
        record = raw_record
        record_errors, record_warnings = validate_record(record, sources)
        errors.extend(record_errors)
        warnings.extend(record_warnings)
        identity = (
            record.get("environment"),
            record.get("processor"),
            record.get("profile"),
            record.get("rid"),
            record.get("index"),
        )
        if identity in identities:
            errors.append(f"duplicate catalog identity {identity}")
        identities.add(identity)
        record_id = record.get("id")
        if record_id in ids:
            errors.append(f"duplicate catalog id {record_id}")
        ids.add(record_id)
    return errors, warnings


def select_records(
    catalog: Dict[str, object],
    scheme: Optional[str] = None,
    rid: Optional[str] = None,
    index: Optional[str] = None,
    environment: Optional[str] = None,
    processor: Optional[str] = None,
) -> List[Dict[str, object]]:
    scheme_id = canonical_scheme(scheme) if scheme else None
    rid_value = rid.replace(" ", "").upper() if rid else None
    index_value = index.replace("0x", "").replace("0X", "").upper() if index else None
    matches: List[Dict[str, object]] = []
    for record in catalog["records"]:  # type: ignore[assignment]
        if scheme_id and record["scheme_id"] != scheme_id:
            continue
        if rid_value and record["rid"] != rid_value:
            continue
        if index_value and record["index"] != index_value:
            continue
        if environment and record["environment"] != environment:
            continue
        if processor and record["processor"] != processor:
            continue
        matches.append(record)
    return matches


def validity_status(record: Dict[str, object]) -> str:
    if record["checksum_verification"] != "verified":
        return "source-inconsistent"
    expiration = datetime.strptime(str(record["expiration"]), "%Y%m%d").date()
    if expiration < date.today():
        return "expired"
    if record["expiration_source"] == "skill-default":
        return "unverified-expiration"
    return "valid"


def command_list(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.catalog)
    matches = select_records(
        catalog,
        scheme=args.scheme,
        environment=args.environment,
        processor=args.processor,
    )
    if args.json:
        print(json.dumps(matches, ensure_ascii=False, indent=2))
        return 0
    print("ENV   SCHEME             RID         INDEX  BITS  EXPIRES   STATUS")
    for record in matches:
        print(
            f"{record['environment']:<5} {record['scheme']:<18} {record['rid']}  "
            f"{record['index']:<5} {record['key_bits']:<5} {record['expiration']} "
            f"{validity_status(record)}"
        )
    print(f"{len(matches)} record(s)")
    return 0


def command_lookup(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.catalog)
    matches = select_records(
        catalog,
        scheme=args.scheme,
        rid=args.rid,
        index=args.index,
        environment=args.environment,
        processor=args.processor,
    )
    if not matches:
        raise CatalogError("no CAPK matched the requested scheme/RID, index, and environment")
    if len(matches) > 1:
        identities = ", ".join(
            f"{item['processor']}/{item['profile']}/{item['rid']}/{item['index']}"
            for item in matches
        )
        raise CatalogError(f"multiple CAPKs matched; refine the profile: {identities}")
    record = matches[0]
    if record["checksum_verification"] != "verified":
        matching = ", ".join(record.get("checksum_matching_indexes", [])) or "none"
        raise CatalogError(
            f"{record['rid']}/{record['index']}: Worldpay source checksum does not "
            f"match the stated index (checksum matches index: {matching}); "
            "record is retained for audit but no TLV will be emitted"
        )
    tlv = record_tlv(record)
    if args.tlv_only:
        print(tlv)
        return 0
    sources = catalog["sources"]
    source = sources[record["source_id"]]
    result = dict(record)
    result["validity_status"] = validity_status(record)
    result["tlv"] = tlv
    result["byte_length"] = len(bytes.fromhex(tlv))
    result["source"] = source
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(f"Scheme: {record['scheme']}")
    print(f"Identity: RID={record['rid']}, index={record['index']}")
    print(f"Environment: {record['environment']} ({record['usage']})")
    print(f"Expiration: {record['expiration']} ({record['expiration_source']})")
    print(f"Validity: {result['validity_status']}")
    print(f"Key size: {record['key_bits']} bits")
    print(
        f"Checksum: {record['checksum']} ({record['checksum_verification']})"
    )
    print(f"Source: {source['title']} - {source['url']}")
    print(f"TLV bytes: {result['byte_length']}")
    print(f"TLV: {tlv}")
    return 0


def command_validate(args: argparse.Namespace) -> int:
    catalog = load_catalog(args.catalog)
    errors, warnings = validate_catalog(catalog)
    if args.json:
        print(
            json.dumps(
                {
                    "valid": not errors,
                    "record_count": len(catalog["records"]),
                    "errors": errors,
                    "warnings": warnings,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for message in errors:
            print(f"ERROR: {message}")
        for message in warnings:
            print(f"WARNING: {message}")
        print(
            f"Catalog: {len(catalog['records'])} record(s), "
            f"{len(errors)} error(s), {len(warnings)} warning(s)"
        )
    return 1 if errors else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="list matching CAPKs")
    list_parser.add_argument("--scheme")
    list_parser.add_argument("--environment", default="test")
    list_parser.add_argument("--processor")
    list_parser.add_argument("--json", action="store_true")
    list_parser.set_defaults(func=command_list)

    lookup = sub.add_parser("lookup", help="return one complete CAPK and TLV")
    identity = lookup.add_mutually_exclusive_group(required=True)
    identity.add_argument("--scheme")
    identity.add_argument("--rid")
    lookup.add_argument("--index", required=True)
    lookup.add_argument("--environment", default="test")
    lookup.add_argument("--processor")
    lookup.add_argument("--json", action="store_true")
    lookup.add_argument("--tlv-only", action="store_true")
    lookup.set_defaults(func=command_lookup)

    validate = sub.add_parser("validate", help="validate every catalog record")
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(func=command_validate)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except CatalogError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
