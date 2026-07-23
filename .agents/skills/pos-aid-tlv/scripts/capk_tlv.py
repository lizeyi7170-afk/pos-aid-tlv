#!/usr/bin/env python3
"""Inspect, validate, build, and modify RTOS/Linux MfSdkEmvSetCapk TLV data."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from aid_tlv import (
    Tlv,
    TlvError,
    encode_items,
    hex_to_bytes,
    parse_tag_arg,
    parse_tlv,
    replace_tag,
)


CAPK_SPECS: Dict[str, Dict[str, object]] = {
    "9F06": {"name": "RID", "length": 5},
    "9F22": {"name": "CA public-key index", "length": 1},
    "DF05": {"name": "Expiration date (YYYYMMDD)", "length": 4},
    "DF06": {"name": "Hash algorithm indicator", "length": 1},
    "DF07": {"name": "Public-key algorithm indicator", "length": 1},
    "DF02": {"name": "Public-key modulus", "min": 1, "max": 248},
    "DF04": {"name": "Public exponent", "lengths": (1, 3)},
    "DF03": {"name": "CAPK checksum", "length": 20},
}

REQUIRED_TAGS = ("9F06", "9F22", "DF05", "DF06", "DF07", "DF02", "DF04", "DF03")
CHECKSUM_INPUT_TAGS = ("9F06", "9F22", "DF02", "DF04")
IDENTITY_TAGS = {"9F06", "9F22"}
DEFAULT_EXPIRATION = bytes.fromhex("20301231")


def group_items(items: Sequence[Tlv]) -> Dict[str, List[Tlv]]:
    grouped: Dict[str, List[Tlv]] = {}
    for item in items:
        grouped.setdefault(item.tag_hex, []).append(item)
    return grouped


def one_value(grouped: Dict[str, List[Tlv]], tag: str) -> bytes:
    occurrences = grouped.get(tag, [])
    if len(occurrences) != 1:
        if not occurrences:
            raise TlvError(f"missing required CAPK tag {tag}")
        raise TlvError(f"duplicate CAPK tag {tag}")
    return occurrences[0].value


def sha1_checksum(items: Sequence[Tlv]) -> bytes:
    grouped = group_items(items)
    exponent = one_value(grouped, "DF04").lstrip(b"\x00") or b"\x00"
    payload = (
        one_value(grouped, "9F06")
        + one_value(grouped, "9F22")
        + one_value(grouped, "DF02")
        + exponent
    )
    return hashlib.sha1(payload).digest()


def refresh_checksum(items: Sequence[Tlv]) -> List[Tlv]:
    grouped = group_items(items)
    hash_indicator = one_value(grouped, "DF06")
    if hash_indicator != b"\x01":
        raise TlvError(
            "automatic checksum refresh supports only DF06=01 (SHA-1); "
            "use the authoritative profile for other algorithms"
        )
    checksum = sha1_checksum(items)
    return replace_tag(items, bytes.fromhex("DF03"), checksum, False)


def validate_expiration(value: bytes) -> Optional[str]:
    text = value.hex().upper()
    if any(character not in "0123456789" for character in text):
        return "DF05 must contain packed-BCD YYYYMMDD digits"
    try:
        date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
    except ValueError as exc:
        return f"DF05 is not a valid YYYYMMDD date: {exc}"
    return None


def validate_items(items: Sequence[Tlv]) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    grouped = group_items(items)

    for tag in REQUIRED_TAGS:
        if tag not in grouped:
            errors.append(f"missing required CAPK tag {tag}")

    for tag, occurrences in grouped.items():
        if len(occurrences) > 1:
            errors.append(f"duplicate CAPK tag {tag}")
        spec = CAPK_SPECS.get(tag)
        if spec is None:
            warnings.append(f"tag {tag} is not mapped by MfSdkEmvSetCapk and will be ignored")
            continue
        value = occurrences[0].value
        length = len(value)
        if "length" in spec and length != spec["length"]:
            errors.append(f"tag {tag} ({spec['name']}) must be {spec['length']} bytes, got {length}")
        if "lengths" in spec and length not in spec["lengths"]:
            allowed = " or ".join(str(item) for item in spec["lengths"])
            errors.append(f"tag {tag} ({spec['name']}) must be {allowed} bytes, got {length}")
        if "min" in spec and length < spec["min"]:
            errors.append(f"tag {tag} ({spec['name']}) must be at least {spec['min']} byte, got {length}")
        if "max" in spec and length > spec["max"]:
            errors.append(f"tag {tag} ({spec['name']}) must be at most {spec['max']} bytes, got {length}")

    if "DF05" in grouped and len(grouped["DF05"]) == 1 and len(grouped["DF05"][0].value) == 4:
        expiration_error = validate_expiration(grouped["DF05"][0].value)
        if expiration_error:
            errors.append(expiration_error)

    if "DF04" in grouped and len(grouped["DF04"]) == 1:
        exponent_bytes = grouped["DF04"][0].value
        if len(exponent_bytes) in (1, 3):
            exponent = int.from_bytes(exponent_bytes, "big")
            if exponent <= 1 or exponent % 2 == 0:
                errors.append("DF04 public exponent must be an odd integer greater than one")
            elif exponent not in (3, 65537):
                warnings.append(
                    f"DF04 exponent is {exponent}; verify this uncommon value against the certified profile"
                )

    if "DF06" in grouped and len(grouped["DF06"]) == 1 and grouped["DF06"][0].value != b"\x01":
        warnings.append("DF06 is not 01; automatic SHA-1 checksum verification is unavailable")
    if "DF07" in grouped and len(grouped["DF07"]) == 1 and grouped["DF07"][0].value != b"\x01":
        warnings.append("DF07 is not the conventional RSA indicator 01; verify the certified profile")

    checksum_ready = all(
        tag in grouped and len(grouped[tag]) == 1 for tag in (*CHECKSUM_INPUT_TAGS, "DF06", "DF03")
    )
    if checksum_ready:
        hash_indicator = grouped["DF06"][0].value
        supplied = grouped["DF03"][0].value
        if hash_indicator == b"\x01" and len(supplied) == 20:
            expected = sha1_checksum(items)
            if supplied != expected:
                errors.append(
                    f"DF03 checksum mismatch: supplied {supplied.hex().upper()}, "
                    f"expected {expected.hex().upper()}"
                )

    return errors, warnings


def emit_validation(items: Sequence[Tlv], as_json: bool, strict: bool) -> int:
    errors, warnings = validate_items(items)
    if as_json:
        print(json.dumps({"valid": not errors, "errors": errors, "warnings": warnings}, indent=2))
    else:
        for message in errors:
            print(f"ERROR: {message}")
        for message in warnings:
            print(f"WARNING: {message}")
        if not errors and not warnings:
            print("OK: CAPK TLV is structurally valid and its SHA-1 checksum matches.")
        else:
            print(f"Summary: {len(errors)} error(s), {len(warnings)} warning(s).")
    if errors:
        return 1
    if strict and warnings:
        return 2
    return 0


def print_items(items: Sequence[Tlv]) -> None:
    print(f"{'OFFSET':>6}  {'TAG':<6} {'LEN':>4}  {'VALUE':<34} NAME")
    for item in items:
        value = item.value.hex().upper()
        shown = value if len(value) <= 34 else value[:31] + "..."
        name = CAPK_SPECS.get(item.tag_hex, {}).get("name", "SDK-unmapped")
        print(f"{item.offset:6d}  {item.tag_hex:<6} {len(item.value):4d}  {shown:<34} {name}")


def command_inspect(args: argparse.Namespace) -> int:
    data = hex_to_bytes(args.tlv)
    items = parse_tlv(data)
    errors, warnings = validate_items(items)
    grouped = group_items(items)
    result = {
        "byte_length": len(data),
        "rid": grouped.get("9F06", [None])[0].value.hex().upper() if len(grouped.get("9F06", [])) == 1 else None,
        "index": grouped.get("9F22", [None])[0].value.hex().upper() if len(grouped.get("9F22", [])) == 1 else None,
        "items": [
            {
                "offset": item.offset,
                "tag": item.tag_hex,
                "name": CAPK_SPECS.get(item.tag_hex, {}).get("name", "SDK-unmapped"),
                "length": len(item.value),
                "value": item.value.hex().upper(),
            }
            for item in items
        ],
        "errors": errors,
        "warnings": warnings,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_items(items)
        print(f"Identity: RID={result['rid'] or 'missing'}, index={result['index'] or 'missing'}")
        print(f"Total: {len(items)} tag(s), {len(data)} byte(s)")
        if not errors and grouped.get("DF06", [None])[0].value == b"\x01":
            print(f"SHA-1 checksum: {sha1_checksum(items).hex().upper()} (matches DF03)")
        elif errors or warnings:
            print(f"Validation: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 0


def command_validate(args: argparse.Namespace) -> int:
    return emit_validation(parse_tlv(hex_to_bytes(args.tlv)), args.json, args.strict)


def command_set(args: argparse.Namespace) -> int:
    items = parse_tlv(hex_to_bytes(args.tlv))
    tag = parse_tag_arg(args.tag)
    tag_hex = tag.hex().upper()
    if tag_hex not in CAPK_SPECS:
        raise TlvError(f"tag {tag_hex} is not mapped by MfSdkEmvSetCapk")
    value = hex_to_bytes(args.value, "value")
    grouped = group_items(items)
    if tag_hex in IDENTITY_TAGS and tag_hex in grouped and grouped[tag_hex][0].value != value:
        if not args.allow_identity_change:
            raise TlvError(
                f"changing {tag_hex} changes CAPK identity; pass --allow-identity-change "
                "only when intentionally creating a different RID/index record"
            )
    updated = replace_tag(items, tag, value, args.require_existing)
    if args.refresh_checksum:
        updated = refresh_checksum(updated)
    elif tag_hex in CHECKSUM_INPUT_TAGS:
        print("WARNING: DF03 must be refreshed after changing this field", file=sys.stderr)
    print(encode_items(updated).hex().upper())
    return 0


def command_checksum(args: argparse.Namespace) -> int:
    items = parse_tlv(hex_to_bytes(args.tlv))
    print(sha1_checksum(items).hex().upper())
    return 0


def command_refresh_checksum(args: argparse.Namespace) -> int:
    items = parse_tlv(hex_to_bytes(args.tlv))
    print(encode_items(refresh_checksum(items)).hex().upper())
    return 0


def command_build(args: argparse.Namespace) -> int:
    items: List[Tlv] = []
    seen = set()
    offset = 0
    for pair in args.pairs:
        if "=" not in pair:
            raise TlvError(f"expected TAG=VALUE, got {pair!r}")
        raw_tag, raw_value = pair.split("=", 1)
        tag = parse_tag_arg(raw_tag)
        tag_hex = tag.hex().upper()
        if tag_hex not in CAPK_SPECS:
            raise TlvError(f"tag {tag_hex} is not mapped by MfSdkEmvSetCapk")
        if tag_hex in seen:
            raise TlvError(f"duplicate CAPK tag {tag_hex}")
        seen.add(tag_hex)
        item = Tlv(tag=tag, value=hex_to_bytes(raw_value, f"value for {raw_tag}"), offset=offset)
        items.append(item)
        offset += len(item.encoded())
    if "DF05" not in seen:
        default_item = Tlv(tag=bytes.fromhex("DF05"), value=DEFAULT_EXPIRATION, offset=offset)
        items.append(default_item)
        print(
            "WARNING: DF05 was omitted; defaulting to 20301231 per skill policy",
            file=sys.stderr,
        )
    if args.refresh_checksum:
        items = refresh_checksum(items)
    print(encode_items(items).hex().upper())
    return 0


def command_format_c(args: argparse.Namespace) -> int:
    data = hex_to_bytes(args.tlv)
    parse_tlv(data)
    if not args.name or not (args.name[0].isalpha() or args.name[0] == "_"):
        raise TlvError("C variable name is invalid")
    if not all(character.isalnum() or character == "_" for character in args.name):
        raise TlvError("C variable name is invalid")
    print(f"static unsigned char {args.name}[] = {{")
    for start in range(0, len(data), 12):
        chunk = data[start : start + 12]
        print("    " + ", ".join(f"0x{byte:02X}" for byte in chunk) + ",")
    print("};")
    print()
    print(f"s32 ret = MfSdkEmvSetCapk({args.name}, (s32)sizeof({args.name}));")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_parser = sub.add_parser("inspect", help="decode and summarize a CAPK TLV")
    inspect_parser.add_argument("tlv")
    inspect_parser.add_argument("--json", action="store_true")
    inspect_parser.set_defaults(func=command_inspect)

    validate_parser = sub.add_parser("validate", help="validate a complete CAPK TLV")
    validate_parser.add_argument("tlv")
    validate_parser.add_argument("--strict", action="store_true")
    validate_parser.add_argument("--json", action="store_true")
    validate_parser.set_defaults(func=command_validate)

    set_parser = sub.add_parser("set", help="replace or append one mapped CAPK tag")
    set_parser.add_argument("tlv")
    set_parser.add_argument("tag")
    set_parser.add_argument("value")
    set_parser.add_argument("--require-existing", action="store_true")
    set_parser.add_argument("--refresh-checksum", action="store_true")
    set_parser.add_argument("--allow-identity-change", action="store_true")
    set_parser.set_defaults(func=command_set)

    checksum_parser = sub.add_parser("checksum", help="calculate SHA-1 over RID, index, modulus, exponent")
    checksum_parser.add_argument("tlv")
    checksum_parser.set_defaults(func=command_checksum)

    refresh_parser = sub.add_parser("refresh-checksum", help="replace or append DF03 with the calculated SHA-1")
    refresh_parser.add_argument("tlv")
    refresh_parser.set_defaults(func=command_refresh_checksum)

    build = sub.add_parser("build", help="build CAPK TLV from ordered TAG=VALUE pairs")
    build.add_argument("pairs", nargs="+")
    build.add_argument("--refresh-checksum", action="store_true")
    build.set_defaults(func=command_build)

    c_parser = sub.add_parser("format-c", help="format CAPK TLV as C code")
    c_parser.add_argument("tlv")
    c_parser.add_argument("--name", default="capk_tlv")
    c_parser.set_defaults(func=command_format_c)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, TlvError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
