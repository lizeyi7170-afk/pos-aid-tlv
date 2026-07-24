#!/usr/bin/env python3
"""Extract Mastercard TSE/M-TIP HTML and build complete RTOS/Linux SDK AID TLVs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import aid_tlv


class TseError(ValueError):
    pass


REQUIRED_REGISTRY_TAGS = {
    "DF8118",
    "DF8119",
    "DF811B",
    "DF840A",
    "DF8120",
    "DF8121",
    "DF8122",
}


def default_tag_registry_path() -> Path:
    return Path(__file__).resolve().parent.parent / "references" / "aid-tag-registry.json"


def load_tag_registry(path: Optional[Path] = None) -> Dict[str, object]:
    registry_path = path or default_tag_registry_path()
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TseError(f"cannot load AID tag registry {registry_path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise TseError("AID tag registry must be an object with schema_version=1")
    tags = data.get("tags")
    if not isinstance(tags, dict):
        raise TseError("AID tag registry is missing the tags object")
    missing = sorted(REQUIRED_REGISTRY_TAGS - set(tags))
    if missing:
        raise TseError("AID tag registry is missing required tags: " + ", ".join(missing))
    for tag_hex in REQUIRED_REGISTRY_TAGS:
        definition = tags[tag_hex]
        if not isinstance(definition, dict):
            raise TseError(f"AID tag registry definition for {tag_hex} must be an object")
        path_value = definition.get("path")
        if path_value != ["DF8A01", "DF8407"]:
            raise TseError(
                f"AID tag registry path for {tag_hex} must be DF8A01 -> DF8407"
            )
    encodings = data.get("encodings")
    if not isinstance(encodings, dict):
        raise TseError("AID tag registry is missing the encodings object")
    return data


TAG_REGISTRY = load_tag_registry()
TAG_DEFINITIONS = TAG_REGISTRY["tags"]
TAG_ENCODINGS = TAG_REGISTRY["encodings"]

MASTERCARD_CONTACTLESS_TAC_TAGS = {
    definition["source_field"]: tag_hex
    for tag_hex, definition in TAG_DEFINITIONS.items()
    if definition.get("report_group") == "mastercard-contactless-tac"
}

CVM_CAPABILITY_BITS = {
    alias.casefold(): int(bit_hex, 16)
    for bit_hex, aliases in TAG_ENCODINGS["mastercard-cvm-capability"]["bits"].items()
    for alias in aliases
}

SDK_CONTACTLESS_DEFAULTS = {
    tag_hex: definition["sdk_default"].upper()
    for tag_hex, definition in TAG_DEFINITIONS.items()
    if definition.get("omit_when_sdk_default")
}

REFUND_TAC_HEADING_KEYWORD = str(
    TAG_DEFINITIONS["DF840A"].get("report_table_heading_keyword", "Refund")
).casefold()

DF8119_FALLBACK_BY_DF8118 = {
    df8118.upper(): df8119.upper()
    for df8118, df8119 in TAG_DEFINITIONS["DF8119"]
    .get("fallback_by_df8118", {})
    .items()
}

MASTERCARD_KERNEL_CONFIGURATION_BITS = {
    name: int(bit_hex, 16)
    for name, bit_hex in TAG_ENCODINGS["mastercard-kernel-configuration"]["bits"].items()
}


@dataclass(frozen=True)
class Row:
    label: str
    value: str


class TseRowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: List[Row] = []
        self._in_row = False
        self._in_cell = False
        self._cells: List[str] = []
        self._parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            if self._in_row:
                self._finish_row()
            self._in_row = True
            self._cells = []
        elif tag in {"td", "th"} and self._in_row:
            if self._in_cell:
                self._finish_cell()
            self._in_cell = True
            self._parts = []
        elif tag == "br" and self._in_cell:
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._in_cell:
            self._finish_cell()
        elif tag == "tr" and self._in_row:
            if self._in_cell:
                self._finish_cell()
            self._finish_row()

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._parts.append(data)

    def close(self) -> None:
        super().close()
        if self._in_cell:
            self._finish_cell()
        if self._in_row:
            self._finish_row()

    def _finish_cell(self) -> None:
        self._cells.append(normalize_text("".join(self._parts)))
        self._parts = []
        self._in_cell = False

    def _finish_row(self) -> None:
        if len(self._cells) >= 2 and self._cells[0]:
            self.rows.append(Row(self._cells[0], " | ".join(self._cells[1:])))
        self._cells = []
        self._in_row = False


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def default_catalog_path() -> Path:
    return Path(__file__).resolve().parent.parent / "references" / "aid-profile-catalog.json"


def read_report(path: Path) -> List[Row]:
    parser = TseRowParser()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    if not parser.rows:
        raise TseError("the HTML report contains no two-column table rows")
    return parser.rows


def contactless_tac_groups(
    path: Path, report_names: Sequence[str]
) -> Dict[str, List[Dict[str, object]]]:
    html = path.read_text(encoding="utf-8")
    result: Dict[str, List[Dict[str, object]]] = {
        report_name: [] for report_name in report_names
    }
    for match in re.finditer(
        r"<table\b[^>]*>(.*?)</table\s*>", html, flags=re.IGNORECASE | re.DOTALL
    ):
        parser = TseRowParser()
        parser.feed("<table>" + match.group(1) + "</table>")
        parser.close()
        heading = next(
            (
                row.label
                for row in parser.rows
                if row.label.casefold().startswith("terminal action codes -")
            ),
            None,
        )
        if heading is None:
            continue
        for report_name in report_names:
            prefix = profile_prefix(report_name)
            updates: Dict[str, str] = {}
            for parameter_name, tag_hex in MASTERCARD_CONTACTLESS_TAC_TAGS.items():
                label = prefix + parameter_name
                values = [
                    row.value for row in parser.rows if row.label == label and row.value
                ]
                unique = list(dict.fromkeys(values))
                if len(unique) > 1:
                    raise TseError(
                        f"{heading} contains conflicting {report_name} {parameter_name} values"
                    )
                if unique:
                    updates[tag_hex] = clean_hex(
                        unique[0], f"{heading} {report_name} {parameter_name}", 5
                    )
            if not updates:
                continue
            if len(updates) != len(MASTERCARD_CONTACTLESS_TAC_TAGS):
                raise TseError(
                    f"{heading} has an incomplete {report_name} contactless TAC set"
                )
            result[report_name].append(
                {
                    "heading": heading,
                    "kind": (
                        "refund"
                        if REFUND_TAC_HEADING_KEYWORD in heading.casefold()
                        else "standard"
                    ),
                    "values": updates,
                }
            )
    return result


def index_rows(rows: Iterable[Row]) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    for row in rows:
        result.setdefault(row.label, []).append(row.value)
    return result


def get_value(fields: Dict[str, List[str]], label: str, required: bool = False) -> Optional[str]:
    values = [value for value in fields.get(label, []) if value != ""]
    unique = list(dict.fromkeys(values))
    if len(unique) > 1:
        raise TseError(f"field {label!r} has conflicting values: {unique}")
    if unique:
        return unique[0]
    if required:
        raise TseError(f"missing required report field: {label}")
    return None


def clean_hex(value: str, label: str, expected_bytes: Optional[int] = None) -> str:
    cleaned = re.sub(r"[\s:-]", "", value).upper()
    if not cleaned or re.search(r"[^0-9A-F]", cleaned):
        raise TseError(f"{label} is not hexadecimal: {value!r}")
    if len(cleaned) % 2:
        raise TseError(f"{label} has an odd number of hexadecimal digits")
    if expected_bytes is not None and len(cleaned) != expected_bytes * 2:
        raise TseError(f"{label} must be {expected_bytes} bytes, got {len(cleaned) // 2}")
    return cleaned


def amount_bcd(value: str, label: str) -> str:
    digits = re.sub(r"\s", "", value)
    if not re.fullmatch(r"\d+", digits):
        raise TseError(f"{label} must contain only decimal digits, got {value!r}")
    if len(digits) > 12:
        raise TseError(f"{label} exceeds the SDK 12-digit packed-BCD amount")
    return digits.zfill(12)


def amount_binary_4(value: str, label: str) -> str:
    digits = re.sub(r"\s", "", value)
    if not re.fullmatch(r"\d+", digits):
        raise TseError(f"{label} must be a non-negative decimal integer, got {value!r}")
    amount = int(digits, 10)
    if amount > 0xFFFFFFFF:
        raise TseError(f"{label} does not fit the SDK four-byte binary field")
    return amount.to_bytes(4, "big").hex().upper()


def cvm_capability(value: str, label: str) -> str:
    result = 0
    capabilities = [normalize_text(item) for item in value.split(",") if normalize_text(item)]
    if not capabilities:
        raise TseError(f"{label} contains no CVM capability")
    for capability in capabilities:
        bit = CVM_CAPABILITY_BITS.get(capability.casefold())
        if bit is None:
            raise TseError(f"{label} contains unsupported CVM capability {capability!r}")
        result |= bit
    return f"{result:02X}"


def boolean_value(value: str, label: str) -> bool:
    normalized = normalize_text(value).casefold()
    if normalized in {"true", "yes", "supported", "1"}:
        return True
    if normalized in {"false", "no", "not supported", "0"}:
        return False
    raise TseError(f"{label} must be a boolean value, got {value!r}")


def mastercard_kernel_configuration(
    fields: Dict[str, List[str]], prefix: str
) -> Optional[str]:
    labels = {
        "magstripe": prefix + "Contactless Mag-Stripe mode supported",
        "cdcvm": prefix + "CDCVM supported",
        "rrp": "Contactless Interface - Relay Resistance Protocol (RRP) activated - [RA389 - RA446]",
    }
    raw = {name: get_value(fields, label) for name, label in labels.items()}
    if all(value is None for value in raw.values()):
        return None
    missing = [labels[name] for name, value in raw.items() if value is None]
    if missing:
        raise TseError(
            "cannot derive DF811B because required TSE fields are missing: "
            + ", ".join(missing)
        )
    magstripe_supported = boolean_value(raw["magstripe"] or "", labels["magstripe"])
    cdcvm_supported = boolean_value(raw["cdcvm"] or "", labels["cdcvm"])
    rrp_supported = boolean_value(raw["rrp"] or "", labels["rrp"])
    result = 0
    if not magstripe_supported:
        result |= MASTERCARD_KERNEL_CONFIGURATION_BITS["magstripe_not_supported"]
    # Mastercard EMV contactless is in scope, so b7 ("EMV mode not supported") remains zero.
    if cdcvm_supported:
        result |= MASTERCARD_KERNEL_CONFIGURATION_BITS["cdcvm_supported"]
    if rrp_supported:
        result |= MASTERCARD_KERNEL_CONFIGURATION_BITS["rrp_supported"]
    return f"{result:02X}"


def parse_brand_list(value: str) -> List[str]:
    return [normalize_text(item) for item in value.split(",") if normalize_text(item)]


def report_brands(fields: Dict[str, List[str]]) -> List[str]:
    result: List[str] = []
    for label in (
        "Contact Interface - Brands (AID) supported",
        "Contactless Interface - Brands (AID) supported",
    ):
        value = get_value(fields, label)
        if value:
            for brand in parse_brand_list(value):
                if brand not in result:
                    result.append(brand)
    if not result:
        raise TseError("the report does not list any supported AID brands")
    return result


def load_catalog(path: Path) -> Dict[str, object]:
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if catalog.get("schema_version") != 1:
        raise TseError("unsupported AID profile catalog schema")
    if not isinstance(catalog.get("profiles"), list):
        raise TseError("AID profile catalog has no profiles array")
    return catalog


def profiles_by_report_name(catalog: Dict[str, object]) -> Dict[str, Dict[str, object]]:
    result: Dict[str, Dict[str, object]] = {}
    for raw in catalog["profiles"]:  # type: ignore[index]
        if not isinstance(raw, dict):
            raise TseError("catalog profile must be an object")
        name = raw.get("report_name")
        if not isinstance(name, str) or not name:
            raise TseError("catalog profile is missing report_name")
        if name in result:
            raise TseError(f"duplicate catalog report_name: {name}")
        result[name] = raw
    return result


def resolve_9f33(fields: Dict[str, List[str]], catalog: Dict[str, object]) -> Tuple[str, List[str]]:
    policy = catalog.get("tse_policy", {})
    defaults = policy.get("9f33_unknown_bit_defaults", {}) if isinstance(policy, dict) else {}
    values: List[int] = []
    notices: List[str] = []
    for index in range(1, 4):
        label = f"Contact Interface - 9F33 Byte {index}"
        raw = get_value(fields, label, required=True)
        assert raw is not None
        bits = re.sub(r"[^01?]", "", raw)
        if len(bits) != 8:
            raise TseError(f"{label} must contain eight binary bits or question marks, got {raw!r}")
        if "?" in bits:
            replacement = defaults.get(str(index)) if isinstance(defaults, dict) else None
            if replacement not in {"0", "1"}:
                raise TseError(f"{label} contains '?' but no catalog default is defined")
            notices.append(f"{label}: replaced '?' with {replacement}")
            bits = bits.replace("?", replacement)
        values.append(int(bits, 2))
    return bytes(values).hex().upper(), notices


def resolve_currency(
    fields: Dict[str, List[str]],
    currency_code: Optional[str],
    currency_exponent: Optional[str],
    required: bool,
) -> Tuple[Optional[str], Optional[str], List[str]]:
    deployment = get_value(fields, "Deployment country")
    country_text = deployment or "the report's deployment country"
    if currency_exponent is not None and currency_code is None:
        raise TseError("--currency-exponent requires --currency-code")
    if currency_code is None:
        message = (
            f"currency is unresolved: look up the authoritative ISO 4217 numeric "
            f"currency code for {country_text!r}, then rerun with --currency-code; "
            "no 0840 fallback is permitted"
        )
        if required:
            raise TseError(message)
        return None, None, [message]

    code_digits = re.sub(r"\s", "", currency_code)
    if not re.fullmatch(r"\d{3,4}", code_digits):
        raise TseError(
            "--currency-code must be a three-digit ISO 4217 numeric code or its "
            "four-digit packed-BCD form"
        )
    code = code_digits.zfill(4)
    notices = [
        f"5F2A={code} uses the supplied ISO 4217 numeric currency code for "
        f"deployment country {country_text}; confirm whether this transaction "
        "currency needs to be changed"
    ]

    exponent: Optional[str] = None
    if currency_exponent is None:
        notices.append(
            "5F36 omitted because the user did not explicitly specify a currency exponent"
        )
    else:
        exponent_digits = re.sub(r"\s", "", currency_exponent)
        if not re.fullmatch(r"\d{1,2}", exponent_digits):
            raise TseError(
                "--currency-exponent must be one or two decimal digits"
            )
        exponent = exponent_digits.zfill(2)
        notices.append(
            f"5F36={exponent} included because the currency exponent was explicitly supplied"
        )
    return code, exponent, notices


def set_top(items: Sequence[aid_tlv.Tlv], tag_hex: str, value_hex: str) -> List[aid_tlv.Tlv]:
    return aid_tlv.replace_tag(
        items,
        bytes.fromhex(tag_hex),
        bytes.fromhex(clean_hex(value_hex, f"value for {tag_hex}")),
        False,
    )


def set_contactless(
    items: Sequence[aid_tlv.Tlv],
    updates: Dict[str, str],
    removals: Sequence[str] = (),
) -> List[aid_tlv.Tlv]:
    grouped: Dict[str, List[aid_tlv.Tlv]] = {}
    for item in items:
        grouped.setdefault(item.tag_hex, []).append(item)
    if len(grouped.get("DF8A01", [])) > 1:
        raise TseError("base profile contains duplicate DF8A01 tags")
    if "DF8A01" in grouped and ("DF8406" in grouped or "DF8407" in grouped):
        raise TseError("base profile mixes DF8A01 with top-level DF8406/DF8407")
    if "DF8A01" in grouped:
        wrappers = aid_tlv.parse_tlv(grouped["DF8A01"][0].value)
    else:
        wrappers = [
            aid_tlv.Tlv(item.tag, item.value, 0)
            for item in items
            if item.tag_hex in {"DF8406", "DF8407"}
        ]
    if sum(wrapper.tag_hex == "DF8407" for wrapper in wrappers) > 1:
        raise TseError("base profile contains duplicate DF8407 wrappers")
    rf_indexes = [i for i, wrapper in enumerate(wrappers) if wrapper.tag_hex == "DF8407"]
    if rf_indexes:
        rf_index = rf_indexes[0]
        params = aid_tlv.parse_tlv(wrappers[rf_index].value)
    else:
        if not updates:
            return list(items)
        rf_index = len(wrappers)
        params = []
        wrappers.append(aid_tlv.Tlv(bytes.fromhex("DF8407"), b"", 0))
    removal_tags = {tag.upper() for tag in removals}
    params = [item for item in params if item.tag_hex not in removal_tags]
    for tag_hex, value_hex in updates.items():
        params = aid_tlv.replace_tag(
            params,
            bytes.fromhex(tag_hex),
            bytes.fromhex(clean_hex(value_hex, f"value for {tag_hex}")),
            False,
        )
    if params:
        wrappers[rf_index] = aid_tlv.Tlv(
            bytes.fromhex("DF8407"), aid_tlv.encode_items(params), wrappers[rf_index].offset
        )
    else:
        wrappers.pop(rf_index)
    other_value = aid_tlv.encode_items(wrappers)
    if len(other_value) > 255:
        raise TseError("generated DF8A01 exceeds the SDK 255-byte safe length")
    stripped = [
        item
        for item in items
        if item.tag_hex not in {"DF8A01", "DF8406", "DF8407"}
    ]
    if not other_value:
        return stripped
    return aid_tlv.replace_tag(stripped, bytes.fromhex("DF8A01"), other_value, False)


def contactless_tag_value(
    items: Sequence[aid_tlv.Tlv], tag_hex: str
) -> Optional[str]:
    grouped: Dict[str, List[aid_tlv.Tlv]] = {}
    for item in items:
        grouped.setdefault(item.tag_hex, []).append(item)
    if len(grouped.get("DF8A01", [])) > 1:
        raise TseError("profile contains duplicate DF8A01 tags")
    if "DF8A01" in grouped and ("DF8406" in grouped or "DF8407" in grouped):
        raise TseError("profile mixes DF8A01 with top-level DF8406/DF8407")
    if "DF8A01" in grouped:
        wrappers = aid_tlv.parse_tlv(grouped["DF8A01"][0].value)
    else:
        wrappers = grouped.get("DF8407", [])
    rf_wrappers = [wrapper for wrapper in wrappers if wrapper.tag_hex == "DF8407"]
    if len(rf_wrappers) > 1:
        raise TseError("profile contains duplicate DF8407 wrappers")
    if not rf_wrappers:
        return None
    params = aid_tlv.parse_tlv(rf_wrappers[0].value)
    matches = [
        item.value.hex().upper()
        for item in params
        if item.tag_hex == tag_hex.upper()
    ]
    if len(matches) > 1:
        raise TseError(f"profile contains duplicate contactless tag {tag_hex.upper()}")
    return matches[0] if matches else None


def apply_default_aware_contactless_value(
    items: Sequence[aid_tlv.Tlv],
    tag_hex: str,
    value_hex: str,
    notices: List[str],
    reason: str,
) -> List[aid_tlv.Tlv]:
    value = clean_hex(value_hex, f"value for {tag_hex}", 1)
    default = SDK_CONTACTLESS_DEFAULTS[tag_hex]
    if value == default:
        notices.append(
            f"{tag_hex}={value} matches the SDK default and was omitted ({reason})"
        )
        return set_contactless(items, {}, removals=(tag_hex,))
    notices.append(f"{tag_hex}={value} overrides SDK default {default} ({reason})")
    return set_contactless(items, {tag_hex: value})


def tag_value(items: Sequence[aid_tlv.Tlv], tag_hex: str) -> Optional[str]:
    matches = [item.value.hex().upper() for item in items if item.tag_hex == tag_hex]
    if len(matches) > 1:
        raise TseError(f"generated profile contains duplicate tag {tag_hex}")
    return matches[0] if matches else None


def report_tac(fields: Dict[str, List[str]]) -> Dict[str, str]:
    return {
        "DF11": clean_hex(
            get_value(fields, "Contact Interface - TAC Default", required=True) or "",
            "Contact TAC Default",
            5,
        ),
        "DF12": clean_hex(
            get_value(fields, "Contact Interface - TAC Online", required=True) or "",
            "Contact TAC Online",
            5,
        ),
        "DF13": clean_hex(
            get_value(fields, "Contact Interface - TAC Denial", required=True) or "",
            "Contact TAC Denial",
            5,
        ),
    }


def select_contactless_tac_group(
    groups: Sequence[Dict[str, object]],
    kind: str,
    report_name: str,
) -> Optional[Dict[str, str]]:
    candidates = [group for group in groups if group.get("kind") == kind]
    if not candidates:
        return None
    signatures: Dict[Tuple[Tuple[str, str], ...], List[str]] = {}
    for group in candidates:
        values = group.get("values")
        heading = str(group.get("heading", "unnamed TAC table"))
        if not isinstance(values, dict) or not all(
            isinstance(tag, str) and isinstance(value, str)
            for tag, value in values.items()
        ):
            raise TseError(f"{heading} has an invalid {report_name} TAC set")
        signature = tuple(sorted((str(tag), str(value)) for tag, value in values.items()))
        signatures.setdefault(signature, []).append(heading)
    if len(signatures) > 1:
        headings = [
            heading
            for duplicate_headings in signatures.values()
            for heading in duplicate_headings
        ]
        raise TseError(
            f"{report_name} has conflicting {kind} contactless TAC tables: "
            + ", ".join(headings)
        )
    signature = next(iter(signatures))
    return dict(signature)


def encode_contactless_tac_set(values: Dict[str, str]) -> str:
    order = ("DF8121", "DF8122", "DF8120")
    missing = [tag for tag in order if tag not in values]
    if missing:
        raise TseError("contactless TAC set is missing " + ", ".join(missing))
    items = [
        aid_tlv.Tlv(bytes.fromhex(tag), bytes.fromhex(values[tag]), 0)
        for tag in order
    ]
    return aid_tlv.encode_items(items).hex().upper()


def profile_prefix(report_name: str) -> str:
    return f"Contactless Interface - {report_name} - "


def build_one(
    profile: Dict[str, object],
    fields: Dict[str, List[str]],
    terminal_capabilities: str,
    currency_code: str,
    currency_exponent: Optional[str],
    transaction_tac_groups: Sequence[Dict[str, object]] = (),
) -> Dict[str, object]:
    base_tlv = profile.get("base_tlv")
    if not isinstance(base_tlv, str) or not base_tlv:
        raise TseError(
            f"{profile.get('report_name')} is in scope but profile {profile.get('id')} "
            "has no certified complete base_tlv"
        )
    data = aid_tlv.hex_to_bytes(base_tlv, f"base TLV for {profile.get('id')}")
    items = aid_tlv.parse_tlv(data)
    notices: List[str] = []

    expected_aid = str(profile.get("aid", "")).upper()
    expected_kernel = str(profile.get("kernel_id", "")).upper()
    if tag_value(items, "9F06") != expected_aid:
        raise TseError(f"profile {profile.get('id')} base TLV AID does not match catalog identity")
    if tag_value(items, "DF810C") != expected_kernel:
        raise TseError(f"profile {profile.get('id')} base TLV kernel ID does not match catalog")

    for tag_hex, value_hex in report_tac(fields).items():
        before = tag_value(items, tag_hex)
        items = set_top(items, tag_hex, value_hex)
        if before and before != value_hex:
            notices.append(f"{tag_hex} replaced from base {before} with report value {value_hex}")

    floor_zero = get_value(fields, "Contact Interface - Floor Limit = 0")
    if floor_zero and floor_zero.casefold() == "true":
        items = set_top(items, "9F1B", "00000000")

    items = set_top(items, "9F33", terminal_capabilities)
    items = set_top(items, "5F2A", currency_code)
    if currency_exponent is None:
        items = [item for item in items if item.tag_hex != "5F36"]
    else:
        items = set_top(items, "5F36", currency_exponent)

    fixed = profile.get("fixed_overrides", {})
    if not isinstance(fixed, dict):
        raise TseError(f"profile {profile.get('id')} fixed_overrides must be an object")
    for tag_hex, value_hex in fixed.items():
        if not isinstance(tag_hex, str) or not isinstance(value_hex, str):
            raise TseError(f"profile {profile.get('id')} has an invalid fixed override")
        items = set_top(items, tag_hex.upper(), value_hex.upper())

    report_name = str(profile.get("report_name"))
    prefix = profile_prefix(report_name)
    floor = get_value(fields, prefix + "Floor Limit value")
    if floor is None:
        floor = get_value(fields, prefix + "Floor Limit value (Tag 9F1B)")
        if floor is not None:
            items = set_top(items, "9F1B", amount_binary_4(floor, prefix + "Floor Limit"))
    else:
        items = set_top(items, "DF19", amount_bcd(floor, prefix + "Floor Limit"))

    no_cdcvm = get_value(fields, prefix + "Transaction Limit (No CDCVM) value")
    if no_cdcvm is not None:
        items = set_top(items, "DF20", amount_bcd(no_cdcvm, prefix + "Transaction Limit"))
    cvm_limit = get_value(fields, prefix + "CVM Required Limit value")
    if cvm_limit is not None:
        items = set_top(items, "DF21", amount_bcd(cvm_limit, prefix + "CVM Required Limit"))

    cdcvm = get_value(fields, prefix + "Transaction Limit (CDCVM) value")
    if cdcvm is not None and no_cdcvm is not None:
        cdcvm_bcd = amount_bcd(cdcvm, prefix + "Transaction Limit (CDCVM)")
        no_cdcvm_bcd = amount_bcd(no_cdcvm, prefix + "Transaction Limit (No CDCVM)")
        if cdcvm_bcd != no_cdcvm_bcd:
            items = set_contactless(
                items, {"DF8124": no_cdcvm_bcd, "DF8125": cdcvm_bcd}
            )
            notices.append("different CDCVM and No-CDCVM limits encoded as DF8125 and DF8124")

    df8118: Optional[str] = None
    cvm_required = get_value(fields, prefix + "CVM supported above CVM Required Limit")
    if cvm_required is not None:
        df8118 = cvm_capability(cvm_required, prefix + "CVM supported above CVM Required Limit")
        items = apply_default_aware_contactless_value(
            items,
            "DF8118",
            df8118,
            notices,
            f"derived from CVM capabilities: {cvm_required}",
        )

    no_cvm_labels = (
        prefix + "CVM supported when No CVM Required",
        prefix + "CVM supported below CVM Required Limit",
        prefix + "CVM supported at or below CVM Required Limit",
    )
    no_cvm_values = [get_value(fields, label) for label in no_cvm_labels]
    no_cvm_values = [value for value in no_cvm_values if value is not None]
    if len(set(no_cvm_values)) > 1:
        raise TseError(f"{report_name} has conflicting No-CVM capability fields")
    if no_cvm_values:
        df8119 = cvm_capability(no_cvm_values[0], no_cvm_labels[0])
        items = apply_default_aware_contactless_value(
            items,
            "DF8119",
            df8119,
            notices,
            f"derived from No-CVM capabilities: {no_cvm_values[0]}",
        )
    else:
        related_df8119 = DF8119_FALLBACK_BY_DF8118.get(df8118 or "")
        if related_df8119 is not None:
            items = apply_default_aware_contactless_value(
                items,
                "DF8119",
                related_df8119,
                notices,
                f"derived from DF8118={df8118} because the report omits "
                "below-limit CVM capability",
            )
        else:
            profile_df8119 = contactless_tag_value(items, "DF8119")
            if profile_df8119 is not None:
                notices.append(
                    f"DF8119={profile_df8119} retained from the confirmed profile "
                    "because the report omits below-limit CVM capability"
                )
            else:
                notices.append("DF8119 omitted; SDK default 08 is used")

    if report_name == "Mastercard":
        df811b = mastercard_kernel_configuration(fields, prefix)
        if df811b is not None:
            items = apply_default_aware_contactless_value(
                items,
                "DF811B",
                df811b,
                notices,
                "derived from Mastercard Mag-Stripe mode, CDCVM, and RRP settings",
            )

    contactless_updates = select_contactless_tac_group(
        transaction_tac_groups, "standard", report_name
    )
    refund_updates = select_contactless_tac_group(
        transaction_tac_groups, "refund", report_name
    )
    if transaction_tac_groups and contactless_updates is None:
        raise TseError(
            f"{report_name} has transaction-specific contactless TAC tables "
            "but no standard Purchase TAC table"
        )
    if contactless_updates is None:
        contactless_updates = {}
        for parameter_name, tag_hex in MASTERCARD_CONTACTLESS_TAC_TAGS.items():
            label = prefix + parameter_name
            value = get_value(fields, label)
            if value is not None:
                contactless_updates[tag_hex] = clean_hex(value, label, 5)
    if contactless_updates:
        if len(contactless_updates) != 3:
            raise TseError(f"{report_name} contactless TAC set is incomplete")
        items = set_contactless(items, contactless_updates)
    if refund_updates:
        refund_tlv = encode_contactless_tac_set(refund_updates)
        items = set_contactless(items, {"DF840A": refund_tlv})
        notices.append(
            "refund contactless TAC encoded under DF8A01 -> DF8407 -> DF840A"
        )

    required = {
        "9F06",
        "DF01",
        "9F09",
        "DF11",
        "DF12",
        "DF13",
        "DF14",
        "DF15",
        "DF16",
        "DF17",
        "DF18",
        "DF19",
        "DF20",
        "DF21",
        "9F1B",
        "9F33",
        "5F2A",
        "DF810C",
    }
    if profile.get("scheme") == "mastercard_china":
        required.add("9F66")
    missing = sorted(tag for tag in required if tag_value(items, tag) is None)
    if missing:
        raise TseError(f"profile {profile.get('id')} is missing required tags: {', '.join(missing)}")

    errors, warnings = aid_tlv.validate_items(items)
    if errors:
        raise TseError(f"profile {profile.get('id')} failed SDK validation: {'; '.join(errors)}")
    final = aid_tlv.encode_items(items)
    return {
        "profile_id": profile.get("id"),
        "scheme": profile.get("scheme"),
        "report_name": report_name,
        "aid": expected_aid,
        "kernel_id": expected_kernel,
        "byte_length": len(final),
        "tlv": final.hex().upper(),
        "notices": notices,
        "validation_warnings": warnings,
    }


def analyze(
    path: Path,
    catalog: Dict[str, object],
    currency_code: Optional[str] = None,
    currency_exponent: Optional[str] = None,
    require_currency: bool = False,
) -> Dict[str, object]:
    rows = read_report(path)
    fields = index_rows(rows)
    brands = report_brands(fields)
    tac_groups = contactless_tac_groups(path, brands)
    terminal_capabilities, cap_notices = resolve_9f33(fields, catalog)
    resolved_currency, resolved_exponent, currency_notices = resolve_currency(
        fields, currency_code, currency_exponent, require_currency
    )
    return {
        "report": str(path),
        "row_count": len(rows),
        "deployment_country": get_value(fields, "Deployment country"),
        "brands": brands,
        "terminal_capabilities_9F33": terminal_capabilities,
        "currency_5F2A": resolved_currency,
        "currency_exponent_5F36": resolved_exponent,
        "currency_lookup_required": resolved_currency is None,
        "contactless_tac_tables": {
            report_name: [
                {
                    "heading": group["heading"],
                    "kind": group["kind"],
                }
                for group in groups
            ]
            for report_name, groups in tac_groups.items()
            if groups
        },
        "notices": cap_notices + currency_notices,
        "_fields": fields,
        "_contactless_tac_groups": tac_groups,
    }


def build_report(
    path: Path,
    catalog: Dict[str, object],
    currency_code: Optional[str] = None,
    currency_exponent: Optional[str] = None,
) -> Dict[str, object]:
    analysis = analyze(
        path,
        catalog,
        currency_code=currency_code,
        currency_exponent=currency_exponent,
        require_currency=True,
    )
    profiles = profiles_by_report_name(catalog)
    results: List[Dict[str, object]] = []
    for brand in analysis["brands"]:  # type: ignore[index]
        profile = profiles.get(str(brand))
        if profile is None:
            raise TseError(f"no AID profile maps report brand {brand!r}")
        results.append(
            build_one(
                profile,
                analysis["_fields"],  # type: ignore[arg-type,index]
                str(analysis["terminal_capabilities_9F33"]),
                str(analysis["currency_5F2A"]),
                analysis["currency_exponent_5F36"],  # type: ignore[arg-type]
                analysis["_contactless_tac_groups"].get(str(brand), []),  # type: ignore[index,union-attr]
            )
        )
    public_analysis = {key: value for key, value in analysis.items() if not key.startswith("_")}
    return {"analysis": public_analysis, "aids": results}


def print_analysis(result: Dict[str, object]) -> None:
    print(f"Report: {result['report']}")
    print(f"Rows: {result['row_count']}")
    print(f"Brands: {', '.join(result['brands'])}")  # type: ignore[arg-type]
    print(f"9F33: {result['terminal_capabilities_9F33']}")
    currency = result["currency_5F2A"]
    exponent = result["currency_exponent_5F36"]
    if currency is None:
        print("Currency: unresolved; 5F36 omitted")
    else:
        exponent_text = str(exponent) if exponent is not None else "omitted"
        print(f"Currency: 5F2A={currency} 5F36={exponent_text}")
    tac_tables = result.get("contactless_tac_tables", {})
    if isinstance(tac_tables, dict):
        for report_name, groups in tac_tables.items():
            if isinstance(groups, list):
                headings = [
                    str(group.get("heading"))
                    for group in groups
                    if isinstance(group, dict)
                ]
                if headings:
                    print(f"{report_name} contactless TAC tables: {', '.join(headings)}")
    for notice in result["notices"]:  # type: ignore[index]
        print(f"NOTICE: {notice}")


def command_inspect(args: argparse.Namespace) -> int:
    catalog = load_catalog(Path(args.catalog))
    result = analyze(
        Path(args.report),
        catalog,
        currency_code=args.currency_code,
        currency_exponent=args.currency_exponent,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_analysis(result)
    return 0


def command_build(args: argparse.Namespace) -> int:
    catalog = load_catalog(Path(args.catalog))
    result = build_report(
        Path(args.report),
        catalog,
        currency_code=args.currency_code,
        currency_exponent=args.currency_exponent,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        for aid in result["aids"]:  # type: ignore[index]
            print(aid["tlv"])
        print()
        print_analysis(result["analysis"])  # type: ignore[arg-type]
        for index, aid in enumerate(result["aids"], start=1):  # type: ignore[index]
            print()
            print(f"[{index}] {aid['report_name']} ({aid['aid']})")
            print(f"Bytes: {aid['byte_length']}; Kernel: {aid['kernel_id']}")
            for notice in aid["notices"]:
                print(f"NOTICE: {notice}")
            for warning in aid["validation_warnings"]:
                print(f"WARNING: {warning}")
    return 0


def command_validate(args: argparse.Namespace) -> int:
    result = build_report(
        Path(args.report),
        load_catalog(Path(args.catalog)),
        currency_code=args.currency_code,
        currency_exponent=args.currency_exponent,
    )
    print(f"OK: generated and validated {len(result['aids'])} complete AID TLV(s).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, function in (
        ("inspect", command_inspect),
        ("build", command_build),
        ("validate", command_validate),
    ):
        child = sub.add_parser(name)
        child.add_argument("report", help="Mastercard TSE/M-TIP HTML report")
        child.add_argument(
            "--catalog",
            default=str(default_catalog_path()),
            help="AID profile catalog JSON",
        )
        child.add_argument(
            "--currency-code",
            help=(
                "authoritatively looked-up ISO 4217 numeric currency code "
                "(for example 458; encoded as 5F2A=0458)"
            ),
        )
        child.add_argument(
            "--currency-exponent",
            help=(
                "explicit currency exponent for 5F36; omit this option unless "
                "the user requested 5F36"
            ),
        )
        if name != "validate":
            child.add_argument("--json", action="store_true")
        child.set_defaults(func=function)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (OSError, json.JSONDecodeError, TseError, aid_tlv.TlvError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
