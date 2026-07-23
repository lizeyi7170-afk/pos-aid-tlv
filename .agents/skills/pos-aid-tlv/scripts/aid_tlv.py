#!/usr/bin/env python3
"""Inspect, validate, edit, and format RTOS/Linux MfSdkEmvSetAid TLV data."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Tlv:
    tag: bytes
    value: bytes
    offset: int

    @property
    def tag_hex(self) -> str:
        return self.tag.hex().upper()

    def encoded(self) -> bytes:
        return self.tag + encode_length(len(self.value)) + self.value


class TlvError(ValueError):
    pass


SPECS: Dict[str, Dict[str, object]] = {
    "9F06": {"name": "Terminal AID", "min": 5, "max": 16},
    "DF01": {"name": "Application selection indicator", "length": 1},
    "9F09": {"name": "Terminal application version", "length": 2},
    "9F08": {"name": "Application version alias", "length": 2},
    "DF11": {"name": "TAC Default", "length": 5},
    "DF12": {"name": "TAC Online", "length": 5},
    "DF13": {"name": "TAC Denial", "length": 5},
    "DF14": {"name": "Default DDOL", "min": 0, "max": 20},
    "DF15": {"name": "Random-selection threshold", "length": 4},
    "DF16": {"name": "Maximum target percentage", "length": 1, "bcd": True},
    "DF17": {"name": "Target percentage", "length": 1, "bcd": True},
    "DF18": {"name": "Online PIN capability", "length": 1},
    "DF19": {"name": "Contactless offline limit", "length": 6, "bcd": True},
    "DF20": {"name": "Contactless transaction limit", "length": 6, "bcd": True},
    "DF21": {"name": "Contactless CVM limit", "length": 6, "bcd": True},
    "9F1B": {"name": "Terminal floor limit", "length": 4},
    "5F2A": {"name": "Transaction currency code", "length": 2, "bcd": True},
    "5F36": {"name": "Transaction currency exponent", "length": 1},
    "9F3C": {"name": "Reference currency code", "length": 2, "bcd": True},
    "9F3D": {"name": "Reference currency exponent", "length": 1},
    "9F1D": {"name": "Terminal risk-management data", "min": 0, "max": 8},
    "9F33": {"name": "Terminal capabilities", "length": 3},
    "9F66": {"name": "TTQ", "length": 4},
    "9F15": {"name": "Merchant category code", "length": 2, "bcd": True},
    "9F7B": {"name": "Electronic-cash transaction limit", "length": 6, "bcd": True},
    "DF810C": {"name": "Kernel ID", "length": 1},
    "DF8A01": {"name": "Complete AID other-parameter TLV", "min": 0, "max": 255, "nested": True},
    "DF8406": {"name": "Contact other-parameter TLV", "min": 0, "max": 250, "nested": True},
    "DF8407": {"name": "Contactless other-parameter TLV", "min": 0, "max": 250, "nested": True},
}

NESTED_TAGS = {tag for tag, spec in SPECS.items() if spec.get("nested")}
BCD_TAGS = {tag for tag, spec in SPECS.items() if spec.get("bcd")}
KERNEL_IDS = {0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x09}
OTHER_WRAPPERS = {"contact": "DF8406", "contactless": "DF8407"}
DEFAULT_AID_LIMITS = {
    "DF19": bytes.fromhex("000000000000"),
    "DF20": bytes.fromhex("999999999999"),
    "DF21": bytes.fromhex("000000000000"),
}


def read_text_arg(raw: str) -> str:
    if raw == "-":
        return sys.stdin.read()
    if raw.startswith("@"):
        return Path(raw[1:]).read_text(encoding="utf-8")
    return raw


def hex_to_bytes(raw: str, label: str = "hex input") -> bytes:
    text = read_text_arg(raw).strip()
    if re.fullmatch(r"0[xX][0-9A-Fa-f]+", text):
        text = text[2:]
        if len(text) % 2:
            raise TlvError(f"{label} has an odd number of hex digits")
        return bytes.fromhex(text)
    escaped = re.findall(r"\\x([0-9A-Fa-f]{2})", text)
    if escaped:
        return bytes.fromhex("".join(escaped))
    c_array = re.findall(r"0[xX]([0-9A-Fa-f]{2})", text)
    if c_array:
        return bytes.fromhex("".join(c_array))
    cleaned = re.sub(r"[\s,:;_\-{}\[\]()\"']", "", text)
    if cleaned.lower().startswith("0x"):
        cleaned = cleaned[2:]
    if not cleaned:
        return b""
    if re.search(r"[^0-9A-Fa-f]", cleaned):
        raise TlvError(f"{label} contains non-hex characters")
    if len(cleaned) % 2:
        raise TlvError(f"{label} has an odd number of hex digits")
    return bytes.fromhex(cleaned)


def read_tag(data: bytes, offset: int) -> Tuple[bytes, int]:
    if offset >= len(data):
        raise TlvError(f"missing tag at byte offset {offset}")
    start = offset
    first = data[offset]
    offset += 1
    if first & 0x1F == 0x1F:
        count = 0
        while True:
            if offset >= len(data):
                raise TlvError(f"truncated multi-byte tag at byte offset {start}")
            current = data[offset]
            offset += 1
            count += 1
            if count > 4:
                raise TlvError(f"unsupported tag longer than 5 bytes at byte offset {start}")
            if current & 0x80 == 0:
                break
    return data[start:offset], offset


def read_length(data: bytes, offset: int) -> Tuple[int, int]:
    if offset >= len(data):
        raise TlvError(f"missing length at byte offset {offset}")
    first = data[offset]
    offset += 1
    if first < 0x80:
        return first, offset
    count = first & 0x7F
    if count == 0:
        raise TlvError(f"indefinite BER length is not supported at byte offset {offset - 1}")
    if count > 3:
        raise TlvError(f"length-of-length {count} is not supported at byte offset {offset - 1}")
    if offset + count > len(data):
        raise TlvError(f"truncated BER length at byte offset {offset - 1}")
    length_bytes = data[offset : offset + count]
    if length_bytes[0] == 0:
        raise TlvError(f"non-canonical BER length at byte offset {offset - 1}")
    length = int.from_bytes(length_bytes, "big")
    if length < 0x80:
        raise TlvError(f"non-canonical long-form BER length at byte offset {offset - 1}")
    return length, offset + count


def encode_length(length: int) -> bytes:
    if length < 0:
        raise TlvError("negative lengths are invalid")
    if length < 0x80:
        return bytes([length])
    raw = length.to_bytes((length.bit_length() + 7) // 8, "big")
    if len(raw) > 3:
        raise TlvError("value is too large to encode")
    return bytes([0x80 | len(raw)]) + raw


def parse_tlv(data: bytes) -> List[Tlv]:
    items: List[Tlv] = []
    offset = 0
    while offset < len(data):
        start = offset
        tag, offset = read_tag(data, offset)
        length, offset = read_length(data, offset)
        end = offset + length
        if end > len(data):
            raise TlvError(
                f"tag {tag.hex().upper()} at byte offset {start} declares {length} value bytes, "
                f"but only {len(data) - offset} remain"
            )
        items.append(Tlv(tag=tag, value=data[offset:end], offset=start))
        offset = end
    return items


def parse_tag_arg(raw: str) -> bytes:
    tag = hex_to_bytes(raw, "tag")
    parsed, end = read_tag(tag, 0)
    if end != len(tag):
        raise TlvError("tag argument must contain exactly one BER tag")
    return parsed


def is_packed_bcd(value: bytes) -> bool:
    return all((byte >> 4) <= 9 and (byte & 0x0F) <= 9 for byte in value)


def validate_dol(value: bytes) -> Optional[str]:
    offset = 0
    try:
        while offset < len(value):
            _, offset = read_tag(value, offset)
            if offset >= len(value):
                return "DDOL ends after a tag without its requested-length byte"
            offset += 1
    except TlvError as exc:
        return f"invalid DDOL: {exc}"
    return None


def validate_items(items: Sequence[Tlv]) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    grouped: Dict[str, List[Tlv]] = {}
    for item in items:
        grouped.setdefault(item.tag_hex, []).append(item)

    if "9F06" not in grouped:
        errors.append("missing required terminal AID tag 9F06")

    for tag, occurrences in grouped.items():
        if len(occurrences) > 1:
            errors.append(f"duplicate top-level tag {tag}; SDK lookup behavior is ambiguous")
        spec = SPECS.get(tag)
        if spec is None:
            warnings.append(f"top-level tag {tag} is not mapped by MfSdkEmvSetAid and will be ignored")
            continue
        item = occurrences[0]
        length = len(item.value)
        if "length" in spec and length != spec["length"]:
            errors.append(f"tag {tag} ({spec['name']}) must be {spec['length']} bytes, got {length}")
        if "min" in spec and length < spec["min"]:
            errors.append(f"tag {tag} ({spec['name']}) must be at least {spec['min']} bytes, got {length}")
        if "max" in spec and length > spec["max"]:
            errors.append(f"tag {tag} ({spec['name']}) must be at most {spec['max']} bytes, got {length}")
        if tag in BCD_TAGS and not is_packed_bcd(item.value):
            errors.append(f"tag {tag} ({spec['name']}) contains a non-decimal packed-BCD nibble")
        if tag in NESTED_TAGS and item.value:
            try:
                children = parse_tlv(item.value)
                if tag == "DF8A01":
                    child_tags = [child.tag_hex for child in children]
                    for wrapper in ("DF8406", "DF8407"):
                        if child_tags.count(wrapper) > 1:
                            errors.append(f"tag DF8A01 contains duplicate nested wrapper {wrapper}")
                    for child in children:
                        if child.tag_hex in {"DF8406", "DF8407"} and child.value:
                            try:
                                parse_tlv(child.value)
                            except TlvError as exc:
                                errors.append(
                                    f"tag DF8A01 child {child.tag_hex} contains malformed nested TLV: {exc}"
                                )
            except TlvError as exc:
                errors.append(f"tag {tag} contains malformed nested TLV: {exc}")

    if "9F09" in grouped and "9F08" in grouped:
        errors.append("9F09 and 9F08 map to the same field; keep only 9F09")
    if "DF8A01" in grouped and ("DF8406" in grouped or "DF8407" in grouped):
        warnings.append("DF8A01 takes precedence; SDK will ignore top-level DF8406/DF8407")
    if "DF8A01" not in grouped and ("DF8406" in grouped or "DF8407" in grouped):
        warnings.append(
            "top-level DF8406/DF8407 is accepted and re-wrapped by this SDK; "
            "prefer canonical DF8A01 nesting for generated data"
        )
    if "DF18" in grouped:
        warnings.append("MfSdkEmvSetAid forces DF18 to 01 after parsing; the supplied value is not authoritative")

    wrappers = [item for item in items if item.tag_hex in {"DF8406", "DF8407"}]
    if "DF8A01" not in grouped and sum(len(item.encoded()) for item in wrappers) > 255:
        errors.append("encoded DF8406/DF8407 other-parameter record exceeds the safe 255-byte stored length")

    if "DF01" in grouped and len(grouped["DF01"][0].value) == 1:
        if grouped["DF01"][0].value[0] not in (0, 1):
            warnings.append("DF01 is normally 00 (exact match) or 01 (partial match); verify this profile")
    if "DF810C" in grouped and len(grouped["DF810C"][0].value) == 1:
        if grouped["DF810C"][0].value[0] not in KERNEL_IDS:
            errors.append("DF810C kernel ID is not one of 02, 03, 04, 05, 06, 07, or 09")
    if "DF14" in grouped:
        dol_error = validate_dol(grouped["DF14"][0].value)
        if dol_error:
            errors.append(dol_error)

    return errors, warnings


def item_dict(item: Tlv, include_children: bool = True) -> Dict[str, object]:
    spec = SPECS.get(item.tag_hex, {})
    result: Dict[str, object] = {
        "offset": item.offset,
        "tag": item.tag_hex,
        "name": spec.get("name", "Unknown / SDK-unmapped top-level tag"),
        "length": len(item.value),
        "value": item.value.hex().upper(),
    }
    if include_children and item.tag_hex in NESTED_TAGS and item.value:
        try:
            result["children"] = [item_dict(child, child.tag_hex in NESTED_TAGS) for child in parse_tlv(item.value)]
        except TlvError as exc:
            result["nested_error"] = str(exc)
    return result


def print_nested_items(items: Sequence[Tlv], indent: str) -> None:
    for item in items:
        value = item.value.hex().upper()
        shown = value if len(value) <= 26 else value[:23] + "..."
        print(f"{indent}-> {item.tag_hex:<8} {len(item.value):4d}  {shown}")
        if item.tag_hex in NESTED_TAGS and item.value:
            try:
                print_nested_items(parse_tlv(item.value), indent + "   ")
            except TlvError as exc:
                print(f"{indent}   !! malformed nested TLV: {exc}")


def print_items(items: Sequence[Tlv], indent: str = "") -> None:
    print(f"{indent}{'OFFSET':>6}  {'TAG':<8} {'LEN':>4}  {'VALUE':<30} NAME")
    for item in items:
        spec = SPECS.get(item.tag_hex, {})
        value = item.value.hex().upper()
        shown = value if len(value) <= 30 else value[:27] + "..."
        print(f"{indent}{item.offset:6d}  {item.tag_hex:<8} {len(item.value):4d}  {shown:<30} {spec.get('name', 'SDK-unmapped')}")
        if item.tag_hex in NESTED_TAGS and item.value:
            try:
                print_nested_items(parse_tlv(item.value), indent + "        ")
            except TlvError as exc:
                print(f"{indent}        !! malformed nested TLV: {exc}")


def emit_validation(items: Sequence[Tlv], as_json: bool, strict: bool) -> int:
    errors, warnings = validate_items(items)
    if as_json:
        print(json.dumps({"valid": not errors, "errors": errors, "warnings": warnings}, indent=2, ensure_ascii=False))
    else:
        for message in errors:
            print(f"ERROR: {message}")
        for message in warnings:
            print(f"WARNING: {message}")
        if not errors and not warnings:
            print("OK: TLV is structurally valid and matches the SDK AID map.")
        else:
            print(f"Summary: {len(errors)} error(s), {len(warnings)} warning(s).")
    if errors:
        return 1
    if strict and warnings:
        return 2
    return 0


def replace_tag(items: Sequence[Tlv], tag: bytes, value: bytes, require_existing: bool) -> List[Tlv]:
    matches = [index for index, item in enumerate(items) if item.tag == tag]
    tag_hex = tag.hex().upper()
    if len(matches) > 1:
        raise TlvError(f"cannot safely set duplicate tag {tag_hex}")
    result = list(items)
    if matches:
        index = matches[0]
        result[index] = Tlv(tag=tag, value=value, offset=result[index].offset)
    elif require_existing:
        raise TlvError(f"tag {tag_hex} does not exist")
    else:
        result.append(Tlv(tag=tag, value=value, offset=sum(len(item.encoded()) for item in result)))
    return result


def encode_items(items: Iterable[Tlv]) -> bytes:
    return b"".join(item.encoded() for item in items)


def command_inspect(args: argparse.Namespace) -> int:
    data = hex_to_bytes(args.tlv)
    items = parse_tlv(data)
    if args.json:
        print(json.dumps({"byte_length": len(data), "items": [item_dict(item) for item in items]}, indent=2, ensure_ascii=False))
    else:
        print_items(items)
        print(f"Total: {len(items)} top-level tag(s), {len(data)} byte(s)")
    return 0


def command_validate(args: argparse.Namespace) -> int:
    return emit_validation(parse_tlv(hex_to_bytes(args.tlv)), args.json, args.strict)


def command_set(args: argparse.Namespace) -> int:
    items = parse_tlv(hex_to_bytes(args.tlv))
    tag = parse_tag_arg(args.tag)
    value = hex_to_bytes(args.value, "value")
    print(encode_items(replace_tag(items, tag, value, args.require_existing)).hex().upper())
    return 0


def command_set_auto(args: argparse.Namespace) -> int:
    tag = parse_tag_arg(args.tag)
    tag_hex = tag.hex().upper()
    scope = args.scope
    if scope == "auto":
        scope = "top-level" if tag_hex in SPECS else "contactless"

    if scope == "top-level":
        items = parse_tlv(hex_to_bytes(args.tlv))
        value = hex_to_bytes(args.value, "value")
        print(encode_items(replace_tag(items, tag, value, args.require_existing)).hex().upper())
        return 0

    return command_set_other(
        argparse.Namespace(
            tlv=args.tlv,
            scope=scope,
            tag=args.tag,
            value=args.value,
            require_existing=args.require_existing,
        )
    )


def command_set_other(args: argparse.Namespace) -> int:
    items = parse_tlv(hex_to_bytes(args.tlv))
    parameter_tag = parse_tag_arg(args.tag)
    parameter_value = hex_to_bytes(args.value, "value")
    wrapper_tag = bytes.fromhex(OTHER_WRAPPERS[args.scope])

    grouped: Dict[str, List[Tlv]] = {}
    for item in items:
        grouped.setdefault(item.tag_hex, []).append(item)
    for tag in ("DF8A01", "DF8406", "DF8407"):
        if len(grouped.get(tag, [])) > 1:
            raise TlvError(f"cannot safely edit duplicate top-level tag {tag}")
    if "DF8A01" in grouped and ("DF8406" in grouped or "DF8407" in grouped):
        raise TlvError("DF8A01 cannot be safely combined with top-level DF8406/DF8407")

    if "DF8A01" in grouped:
        other_items = parse_tlv(grouped["DF8A01"][0].value)
    else:
        other_items = [
            Tlv(tag=item.tag, value=item.value, offset=0)
            for item in items
            if item.tag_hex in {"DF8406", "DF8407"}
        ]

    for other_wrapper in (bytes.fromhex("DF8406"), bytes.fromhex("DF8407")):
        if sum(item.tag == other_wrapper for item in other_items) > 1:
            raise TlvError(
                f"cannot safely edit duplicate nested wrapper {other_wrapper.hex().upper()}"
            )
    wrapper_matches = [index for index, item in enumerate(other_items) if item.tag == wrapper_tag]
    if wrapper_matches:
        wrapper_index = wrapper_matches[0]
        parameters = parse_tlv(other_items[wrapper_index].value)
        updated_parameters = replace_tag(parameters, parameter_tag, parameter_value, args.require_existing)
        other_items[wrapper_index] = Tlv(
            tag=wrapper_tag,
            value=encode_items(updated_parameters),
            offset=other_items[wrapper_index].offset,
        )
    else:
        if args.require_existing:
            raise TlvError(
                f"tag {parameter_tag.hex().upper()} does not exist in {wrapper_tag.hex().upper()}"
            )
        other_items.append(
            Tlv(
                tag=wrapper_tag,
                value=Tlv(tag=parameter_tag, value=parameter_value, offset=0).encoded(),
                offset=0,
            )
        )

    other_value = encode_items(other_items)
    if len(other_value) > 255:
        raise TlvError("canonical DF8A01 value exceeds the SDK's safe 255-byte stored length")

    stripped_items = [item for item in items if item.tag_hex not in {"DF8A01", "DF8406", "DF8407"}]
    final_items = replace_tag(stripped_items, bytes.fromhex("DF8A01"), other_value, False)
    print(encode_items(final_items).hex().upper())
    return 0


def command_remove(args: argparse.Namespace) -> int:
    items = parse_tlv(hex_to_bytes(args.tlv))
    tag = parse_tag_arg(args.tag)
    matches = [item for item in items if item.tag == tag]
    if not matches:
        raise TlvError(f"tag {tag.hex().upper()} does not exist")
    if len(matches) > 1:
        raise TlvError(f"cannot safely remove duplicate tag {tag.hex().upper()}")
    print(encode_items(item for item in items if item.tag != tag).hex().upper())
    return 0


def command_build(args: argparse.Namespace) -> int:
    items: List[Tlv] = []
    offset = 0
    for pair in args.pairs:
        if "=" not in pair:
            raise TlvError(f"expected TAG=VALUE, got {pair!r}")
        raw_tag, raw_value = pair.split("=", 1)
        tag = parse_tag_arg(raw_tag)
        value = hex_to_bytes(raw_value, f"value for {raw_tag}")
        item = Tlv(tag=tag, value=value, offset=offset)
        items.append(item)
        offset += len(item.encoded())
    present_tags = {item.tag_hex for item in items}
    applied_defaults: List[str] = []
    for tag_hex, value in DEFAULT_AID_LIMITS.items():
        if tag_hex in present_tags:
            continue
        item = Tlv(tag=bytes.fromhex(tag_hex), value=value, offset=offset)
        items.append(item)
        offset += len(item.encoded())
        applied_defaults.append(f"{tag_hex}={value.hex().upper()}")
    if applied_defaults:
        print(
            "NOTICE: contactless limits were not specified; applied defaults: "
            + ", ".join(applied_defaults),
            file=sys.stderr,
        )
    print(encode_items(items).hex().upper())
    return 0


def command_format_c(args: argparse.Namespace) -> int:
    data = hex_to_bytes(args.tlv)
    parse_tlv(data)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.name):
        raise TlvError("C variable name is invalid")
    print(f"static unsigned char {args.name}[] = {{")
    for start in range(0, len(data), 12):
        chunk = data[start : start + 12]
        print("    " + ", ".join(f"0x{byte:02X}" for byte in chunk) + ",")
    print("};")
    print()
    print(f"s32 ret = MfSdkEmvSetAid({args.name}, (s32)sizeof({args.name}));")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_parser = sub.add_parser("inspect", help="decode a TLV stream")
    inspect_parser.add_argument("tlv", help="hex, @file, or - for stdin")
    inspect_parser.add_argument("--json", action="store_true")
    inspect_parser.set_defaults(func=command_inspect)

    validate_parser = sub.add_parser(
        "validate", help="validate against the RTOS/Linux device SDK AID map"
    )
    validate_parser.add_argument("tlv", help="hex, @file, or - for stdin")
    validate_parser.add_argument("--strict", action="store_true", help="return exit code 2 when warnings exist")
    validate_parser.add_argument("--json", action="store_true")
    validate_parser.set_defaults(func=command_validate)

    set_parser = sub.add_parser("set", help="replace a tag or append it when absent")
    set_parser.add_argument("tlv")
    set_parser.add_argument("tag")
    set_parser.add_argument("value")
    set_parser.add_argument("--require-existing", action="store_true")
    set_parser.set_defaults(func=command_set)

    set_auto_parser = sub.add_parser(
        "set-auto",
        help="set a mapped tag at top level; default an unmapped tag to contactless extras",
    )
    set_auto_parser.add_argument("tlv")
    set_auto_parser.add_argument("tag")
    set_auto_parser.add_argument("value")
    set_auto_parser.add_argument(
        "--scope",
        choices=("auto", "top-level", "contact", "contactless"),
        default="auto",
        help="override automatic placement (default: auto)",
    )
    set_auto_parser.add_argument("--require-existing", action="store_true")
    set_auto_parser.set_defaults(func=command_set_auto)

    set_other_parser = sub.add_parser(
        "set-other",
        help="set a contact/contactless extra parameter using canonical DF8A01 nesting",
    )
    set_other_parser.add_argument("tlv")
    set_other_parser.add_argument("scope", choices=sorted(OTHER_WRAPPERS))
    set_other_parser.add_argument("tag")
    set_other_parser.add_argument("value")
    set_other_parser.add_argument("--require-existing", action="store_true")
    set_other_parser.set_defaults(func=command_set_other)

    remove_parser = sub.add_parser("remove", help="remove exactly one occurrence of a tag")
    remove_parser.add_argument("tlv")
    remove_parser.add_argument("tag")
    remove_parser.set_defaults(func=command_remove)

    build = sub.add_parser(
        "build",
        help="build from TAG=VALUE pairs and default missing DF19/DF20/DF21 limits",
    )
    build.add_argument("pairs", nargs="+")
    build.set_defaults(func=command_build)

    c_parser = sub.add_parser("format-c", help="format a TLV stream as C code")
    c_parser.add_argument("tlv")
    c_parser.add_argument("--name", default="aid_tlv")
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
