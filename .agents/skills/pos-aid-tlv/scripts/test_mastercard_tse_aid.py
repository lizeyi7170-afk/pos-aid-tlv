#!/usr/bin/env python3
"""Tests for Mastercard TSE/M-TIP AID extraction and composition."""

from __future__ import annotations

import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Tuple

import aid_tlv
import mastercard_tse_aid as tse


ROWS = [
    ("Deployment country", "China"),
    ("Contact Interface - Brands (AID) supported", "Mastercard China AID, Mastercard"),
    ("Contactless Interface - Brands (AID) supported", "Mastercard China AID, Mastercard"),
    ("Contact Interface - Floor Limit = 0", "True"),
    ("Contact Interface - 9F33 Byte 1", "???00000b"),
    ("Contact Interface - 9F33 Byte 2", "11111000"),
    ("Contact Interface - 9F33 Byte 3", "11?01000"),
    ("Contact Interface - TAC Denial", "00 00 00 00 00"),
    ("Contact Interface - TAC Online", "FE 50 BC F8 00"),
    ("Contact Interface - TAC Default", "FE 50 BC A0 00"),
    ("Contactless Interface - Mastercard - Transaction Limit (CDCVM) value", "100000"),
    ("Contactless Interface - Mastercard - Transaction Limit (No CDCVM) value", "100000"),
    ("Contactless Interface - Mastercard - CVM Required Limit value", "30000"),
    ("Contactless Interface - Mastercard - Floor Limit value", "0"),
    ("Contactless Interface - Mastercard - Contactless Mag-Stripe mode supported", "False"),
    ("Contactless Interface - Mastercard - CDCVM supported", "True"),
    (
        "Contactless Interface - Relay Resistance Protocol (RRP) activated - [RA389 - RA446]",
        "Yes",
    ),
    (
        "Contactless Interface - Mastercard - CVM supported above CVM Required Limit",
        "Signature, Online PIN",
    ),
    ("Contactless Interface - Mastercard - TAC Denial", "00 00 00 00 00"),
    ("Contactless Interface - Mastercard - TAC Online", "F4 50 84 80 0C"),
    ("Contactless Interface - Mastercard - TAC Default", "F4 50 84 80 0C"),
    (
        "Contactless Interface - Mastercard China AID - Transaction Limit (No CDCVM) value",
        "100000",
    ),
    ("Contactless Interface - Mastercard China AID - CVM Required Limit value", "30000"),
    ("Contactless Interface - Mastercard China AID - Floor Limit value (Tag 9F1B)", "0"),
    (
        "Contactless Interface - Mastercard China AID - CVM supported above CVM Required Limit",
        "Signature, Online PIN",
    ),
]


def html_for(rows: List[Tuple[str, str]]) -> str:
    body = "".join(f"<tr><td>{label}</td><td>{value}</td></tr>" for label, value in rows)
    return f"<html><body><table>{body}</table></body></html>"


def tac_table(heading: str, rows: List[Tuple[str, str]]) -> str:
    body = "".join(f"<tr><td>{label}</td><td>{value}</td></tr>" for label, value in rows)
    return (
        "<table>"
        f"<tr><th>{heading}</th><th>Values (Hexadecimal)</th></tr>"
        f"{body}</table>"
    )


def values_by_tag(tlv_hex: str) -> Dict[str, str]:
    return {
        item.tag_hex: item.value.hex().upper()
        for item in aid_tlv.parse_tlv(bytes.fromhex(tlv_hex))
    }


class TseAidTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = tse.load_catalog(tse.default_catalog_path())

    def write_report(
        self, rows: List[Tuple[str, str]]
    ) -> Tuple[tempfile.TemporaryDirectory, Path]:
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name) / "report.html"
        path.write_text(html_for(rows), encoding="utf-8")
        return temp, path

    def write_html(self, html: str) -> Tuple[tempfile.TemporaryDirectory, Path]:
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name) / "report.html"
        path.write_text(html, encoding="utf-8")
        return temp, path

    def test_builds_mastercard_and_china_profiles(self) -> None:
        temp, path = self.write_report(ROWS)
        self.addCleanup(temp.cleanup)
        result = tse.build_report(path, self.catalog, "156")
        self.assertEqual(result["analysis"]["terminal_capabilities_9F33"], "E0F8C8")
        self.assertEqual(result["analysis"]["currency_5F2A"], "0156")
        self.assertEqual(len(result["aids"]), 2)

        profiles = {item["scheme"]: item for item in result["aids"]}
        china = values_by_tag(profiles["mastercard_china"]["tlv"])
        self.assertEqual(china["9F06"], "A0000000108888")
        self.assertEqual(china["DF810C"], "07")
        self.assertEqual(china["DF11"], "FE50BCA000")
        self.assertEqual(china["DF12"], "FE50BCF800")
        self.assertEqual(china["DF20"], "000000100000")
        self.assertEqual(china["DF21"], "000000030000")
        self.assertEqual(china["9F33"], "E0F8C8")
        self.assertEqual(china["9F66"], "3600C080")
        self.assertEqual(china["5F2A"], "0156")
        self.assertNotIn("5F36", china)
        self.assertNotIn("DF8A01", china)
        self.assertTrue(
            any(
                "DF8118=60 matches the SDK default" in notice
                for notice in profiles["mastercard_china"]["notices"]
            )
        )

        mastercard = values_by_tag(profiles["mastercard"]["tlv"])
        self.assertEqual(mastercard["9F06"], "A0000000041010")
        self.assertEqual(mastercard["DF810C"], "02")
        self.assertEqual(mastercard["9F1D"], "6C00800000000000")
        self.assertEqual(mastercard["DF19"], "000000000000")
        self.assertEqual(mastercard["DF20"], "000000100000")
        self.assertEqual(mastercard["DF21"], "000000030000")
        self.assertNotIn("5F36", mastercard)
        wrappers = aid_tlv.parse_tlv(bytes.fromhex(mastercard["DF8A01"]))
        contactless = next(item for item in wrappers if item.tag_hex == "DF8407")
        nested = values_by_tag(contactless.value.hex())
        self.assertEqual(nested["DF8120"], "F45084800C")
        self.assertEqual(nested["DF8121"], "0000000000")
        self.assertEqual(nested["DF8122"], "F45084800C")
        self.assertNotIn("DF8118", nested)
        self.assertNotIn("DF8119", nested)
        self.assertEqual(nested["DF811B"], "B0")
        self.assertTrue(
            any(
                "DF811B=B0 overrides SDK default 20" in notice
                for notice in profiles["mastercard"]["notices"]
            )
        )

    def test_non_default_cvm_capability_is_written(self) -> None:
        rows = [
            (
                label,
                "Online PIN"
                if label
                == "Contactless Interface - Mastercard - CVM supported above CVM Required Limit"
                else value,
            )
            for label, value in ROWS
        ]
        temp, path = self.write_report(rows)
        self.addCleanup(temp.cleanup)
        result = tse.build_report(path, self.catalog, "156")
        mastercard = next(
            item for item in result["aids"] if item["scheme"] == "mastercard"
        )
        top = values_by_tag(mastercard["tlv"])
        wrappers = aid_tlv.parse_tlv(bytes.fromhex(top["DF8A01"]))
        contactless = next(item for item in wrappers if item.tag_hex == "DF8407")
        nested = values_by_tag(contactless.value.hex())
        self.assertEqual(nested["DF8118"], "40")
        self.assertEqual(nested["DF8119"], "28")

    def test_sdk_default_kernel_configuration_is_omitted(self) -> None:
        rows = [
            (
                label,
                "True"
                if label
                == "Contactless Interface - Mastercard - Contactless Mag-Stripe mode supported"
                else "No"
                if label
                == "Contactless Interface - Relay Resistance Protocol (RRP) activated - [RA389 - RA446]"
                else value,
            )
            for label, value in ROWS
        ]
        temp, path = self.write_report(rows)
        self.addCleanup(temp.cleanup)
        result = tse.build_report(path, self.catalog, "156")
        mastercard = next(
            item for item in result["aids"] if item["scheme"] == "mastercard"
        )
        top = values_by_tag(mastercard["tlv"])
        wrappers = aid_tlv.parse_tlv(bytes.fromhex(top["DF8A01"]))
        contactless = next(item for item in wrappers if item.tag_hex == "DF8407")
        nested = values_by_tag(contactless.value.hex())
        self.assertNotIn("DF811B", nested)
        self.assertTrue(
            any(
                "DF811B=20 matches the SDK default" in notice
                for notice in mastercard["notices"]
            )
        )

    def test_mastercard_contactless_tac_mapping_is_fixed(self) -> None:
        self.assertEqual(
            tse.MASTERCARD_CONTACTLESS_TAC_TAGS,
            {
                "TAC Denial": "DF8121",
                "TAC Online": "DF8122",
                "TAC Default": "DF8120",
            },
        )

    def test_mastercard_tag_rules_are_loaded_from_registry(self) -> None:
        registry = tse.load_tag_registry(tse.default_tag_registry_path())
        tags = registry["tags"]
        self.assertEqual(
            tse.SDK_CONTACTLESS_DEFAULTS,
            {
                "DF8118": tags["DF8118"]["sdk_default"],
                "DF8119": tags["DF8119"]["sdk_default"],
                "DF811B": tags["DF811B"]["sdk_default"],
            },
        )
        self.assertEqual(tse.CVM_CAPABILITY_BITS["online pin"], 0x40)
        self.assertEqual(tags["DF8119"]["fallback_by_df8118"], {"40": "28"})
        self.assertEqual(
            tse.MASTERCARD_KERNEL_CONFIGURATION_BITS["rrp_supported"],
            0x10,
        )
        self.assertEqual(
            tags["DF840A"]["paths"]["traditional"], ["DF8A01", "DF8407"]
        )
        self.assertEqual(tags["DF840A"]["paths"]["smart"], ["DF8407"])
        self.assertEqual(tags["DF840A"]["transaction_type"], "20")
        self.assertEqual(tags["DF840A"]["report_table_heading_keyword"], "Refund")
        self.assertTrue(tags["DF840A"]["nested"])

    def test_contactless_refund_configuration_is_nested_and_validated(self) -> None:
        refund_parameters = "DF8120050000000000"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            aid_tlv.command_set_auto(
                argparse.Namespace(
                    tlv="9F0607A0000000041010",
                    tag="DF840A",
                    value=refund_parameters,
                    scope="auto",
                    require_existing=False,
                )
            )
        result_hex = stdout.getvalue().strip()
        top = values_by_tag(result_hex)
        wrappers = aid_tlv.parse_tlv(bytes.fromhex(top["DF8A01"]))
        contactless = next(item for item in wrappers if item.tag_hex == "DF8407")
        contactless_parameters = values_by_tag(contactless.value.hex())
        self.assertEqual(contactless_parameters["DF840A"], refund_parameters)
        refund_nested = values_by_tag(contactless_parameters["DF840A"])
        self.assertEqual(refund_nested["DF8120"], "0000000000")
        errors, warnings = aid_tlv.validate_items(
            aid_tlv.parse_tlv(bytes.fromhex(result_hex))
        )
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_tse_refund_tac_table_is_nested_under_df840a(self) -> None:
        contactless_tac_labels = {
            "Contactless Interface - Mastercard - TAC Denial",
            "Contactless Interface - Mastercard - TAC Online",
            "Contactless Interface - Mastercard - TAC Default",
        }
        base_rows = [
            (
                label,
                "Mastercard"
                if label.endswith("Brands (AID) supported")
                else value,
            )
            for label, value in ROWS
            if label not in contactless_tac_labels
            and not label.startswith("Contactless Interface - Mastercard China AID - ")
        ]
        purchase_rows = [
            ("Contactless Interface - Mastercard - TAC Denial", "00 00 00 00 00"),
            ("Contactless Interface - Mastercard - TAC Online", "F4 50 84 80 0C"),
            ("Contactless Interface - Mastercard - TAC Default", "F4 50 84 80 0C"),
        ]
        refund_rows = [
            ("Contactless Interface - Mastercard - TAC Denial", "FF FF FF FF FF"),
            ("Contactless Interface - Mastercard - TAC Online", "00 00 00 00 00"),
            ("Contactless Interface - Mastercard - TAC Default", "00 00 00 00 00"),
        ]
        html = html_for(base_rows).replace(
            "</body></html>",
            tac_table("Terminal Action Codes - Purchase Transaction", purchase_rows)
            + tac_table(
                "Terminal Action Codes - PAN Retrieval Transaction (Refund)",
                refund_rows,
            )
            + "</body></html>",
        )
        temp, path = self.write_html(html)
        self.addCleanup(temp.cleanup)
        result = tse.build_report(path, self.catalog, "156")
        self.assertEqual(
            [
                group["kind"]
                for group in result["analysis"]["contactless_tac_tables"]["Mastercard"]
            ],
            ["standard", "refund"],
        )
        mastercard_profile = result["aids"][0]
        self.assertEqual(mastercard_profile["byte_length"], 200)
        mastercard = values_by_tag(mastercard_profile["tlv"])
        wrappers = aid_tlv.parse_tlv(bytes.fromhex(mastercard["DF8A01"]))
        contactless = next(item for item in wrappers if item.tag_hex == "DF8407")
        normal = values_by_tag(contactless.value.hex())
        self.assertEqual(normal["DF8120"], "F45084800C")
        self.assertEqual(normal["DF8121"], "0000000000")
        self.assertEqual(normal["DF8122"], "F45084800C")
        refund = values_by_tag(normal["DF840A"])
        self.assertEqual(refund["DF8120"], "0000000000")
        self.assertEqual(refund["DF8121"], "FFFFFFFFFF")
        self.assertEqual(refund["DF8122"], "0000000000")
        self.assertTrue(
            any(
                "refund contactless TAC encoded under DF8A01 -> DF8407 -> DF840A"
                in notice
                for notice in mastercard_profile["notices"]
            )
        )

    def test_flat_conflicting_contactless_tac_values_remain_blocked(self) -> None:
        rows = list(ROWS)
        rows.extend(
            [
                ("Contactless Interface - Mastercard - TAC Denial", "FF FF FF FF FF"),
                ("Contactless Interface - Mastercard - TAC Online", "00 00 00 00 00"),
                ("Contactless Interface - Mastercard - TAC Default", "00 00 00 00 00"),
            ]
        )
        temp, path = self.write_report(rows)
        self.addCleanup(temp.cleanup)
        with self.assertRaisesRegex(
            tse.TseError,
            "Contactless Interface - Mastercard - TAC Default.*conflicting values",
        ):
            tse.build_report(path, self.catalog, "156")

    def test_malformed_contactless_refund_configuration_is_rejected(self) -> None:
        malformed = "9F0607A0000000041010DF8A0109DF840705DF840A01FF"
        errors, _ = aid_tlv.validate_items(
            aid_tlv.parse_tlv(bytes.fromhex(malformed))
        )
        self.assertTrue(
            any(
                "DF840A contains malformed nested TLV" in error
                for error in errors
            )
        )

    def test_cvm_capability_bits(self) -> None:
        self.assertEqual(tse.cvm_capability("Signature, Online PIN", "test"), "60")
        self.assertEqual(tse.cvm_capability("Online PIN", "test"), "40")
        self.assertEqual(tse.cvm_capability("No CVM required", "test"), "08")

    def test_mastercard_kernel_configuration_bits(self) -> None:
        fields = tse.index_rows(
            [
                tse.Row(
                    "Contactless Interface - Mastercard - Contactless Mag-Stripe mode supported",
                    "False",
                ),
                tse.Row("Contactless Interface - Mastercard - CDCVM supported", "True"),
                tse.Row(
                    "Contactless Interface - Relay Resistance Protocol (RRP) activated - [RA389 - RA446]",
                    "Yes",
                ),
            ]
        )
        self.assertEqual(
            tse.mastercard_kernel_configuration(
                fields, "Contactless Interface - Mastercard - "
            ),
            "B0",
        )

    def test_omitted_currency_code_is_silent(self) -> None:
        rows = [
            (label, "Atlantis" if label == "Deployment country" else value)
            for label, value in ROWS
        ]
        temp, path = self.write_report(rows)
        self.addCleanup(temp.cleanup)
        result = tse.analyze(path, self.catalog)
        self.assertNotIn("currency_5F2A", result)
        self.assertNotIn("currency_lookup_required", result)
        self.assertFalse(any("currency" in notice.casefold() for notice in result["notices"]))

    def test_build_without_currency_code_omits_5f2a_and_5f36(self) -> None:
        temp, path = self.write_report(ROWS)
        self.addCleanup(temp.cleanup)
        result = tse.build_report(path, self.catalog)
        self.assertNotIn("currency_5F2A", result["analysis"])
        self.assertNotIn("currency_exponent_5F36", result["analysis"])
        for profile in result["aids"]:
            values = values_by_tag(profile["tlv"])
            self.assertNotIn("5F2A", values)
            self.assertNotIn("5F36", values)

    def test_supplied_iso_code_is_bcd_normalized_and_exponent_is_omitted(self) -> None:
        rows = [
            (label, "Malaysia" if label == "Deployment country" else value)
            for label, value in ROWS
        ]
        temp, path = self.write_report(rows)
        self.addCleanup(temp.cleanup)
        result = tse.build_report(path, self.catalog, "458")
        self.assertEqual(result["analysis"]["currency_5F2A"], "0458")
        self.assertNotIn("currency_exponent_5F36", result["analysis"])
        self.assertFalse(
            any("5F36" in notice for notice in result["analysis"]["notices"])
        )
        for profile in result["aids"]:
            values = values_by_tag(profile["tlv"])
            self.assertEqual(values["5F2A"], "0458")
            self.assertNotIn("5F36", values)
        self.assertTrue(
            any(
                "included because the currency code was explicitly supplied" in notice
                for notice in result["analysis"]["notices"]
            )
        )

    def test_omitted_currency_exponent_is_not_reported(self) -> None:
        temp, path = self.write_report(ROWS)
        self.addCleanup(temp.cleanup)
        result = tse.analyze(path, self.catalog, currency_code="156")
        public_result = {
            key: value for key, value in result.items() if not key.startswith("_")
        }
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            tse.print_analysis(public_result)
        self.assertNotIn("5F36", stdout.getvalue())
        self.assertNotIn("currency_exponent_5F36", public_result)

    def test_currency_exponent_is_written_only_when_explicit(self) -> None:
        temp, path = self.write_report(ROWS)
        self.addCleanup(temp.cleanup)
        result = tse.build_report(path, self.catalog, "156", "3")
        self.assertEqual(result["analysis"]["currency_exponent_5F36"], "03")
        for profile in result["aids"]:
            self.assertEqual(values_by_tag(profile["tlv"])["5F36"], "03")

    def test_build_command_prints_complete_tlvs_before_analysis(self) -> None:
        temp, path = self.write_report(ROWS)
        self.addCleanup(temp.cleanup)
        expected = tse.build_report(path, self.catalog, "156")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            tse.command_build(
                argparse.Namespace(
                    report=str(path),
                    catalog=str(tse.default_catalog_path()),
                    currency_code="156",
                    currency_exponent=None,
                    json=False,
                )
            )
        lines = stdout.getvalue().splitlines()
        expected_tlvs = [item["tlv"] for item in expected["aids"]]
        self.assertEqual(lines[: len(expected_tlvs)], expected_tlvs)
        self.assertTrue(all(line and line == line.upper() for line in expected_tlvs))
        self.assertGreater(lines.index(f"Report: {path}"), len(expected_tlvs))

    def test_builds_maestro_with_mastercard_rules_and_maestro_values(self) -> None:
        rows = [
            (
                label,
                "Mastercard China AID, Maestro, Mastercard"
                if label.endswith("Brands (AID) supported")
                else value,
            )
            for label, value in ROWS
        ]
        rows.extend(
            [
                (
                    "Contactless Interface - Maestro - CVM supported above CVM Required Limit",
                    "Online PIN",
                ),
                ("Contactless Interface - Maestro - CDCVM supported", "True"),
                (
                    "Contactless Interface - Maestro - Transaction Limit (CDCVM) value",
                    "999999999999",
                ),
                (
                    "Contactless Interface - Maestro - Transaction Limit (No CDCVM) value",
                    "999999999999",
                ),
                (
                    "Contactless Interface - Maestro - CVM Required Limit value",
                    "000000100000",
                ),
                ("Contactless Interface - Maestro - Floor Limit value", "0"),
                ("Contactless Interface - Maestro - TAC Denial", "00 00 80 00 00"),
                ("Contactless Interface - Maestro - TAC Online", "F4 50 04 80 0C"),
                ("Contactless Interface - Maestro - TAC Default", "F4 50 04 80 0C"),
            ]
        )
        temp, path = self.write_report(rows)
        self.addCleanup(temp.cleanup)
        result = tse.build_report(path, self.catalog, "156")
        self.assertEqual(len(result["aids"]), 3)
        maestro_profile = next(
            item for item in result["aids"] if item["scheme"] == "maestro"
        )
        maestro = values_by_tag(maestro_profile["tlv"])
        self.assertEqual(maestro_profile["byte_length"], 179)
        self.assertEqual(maestro["9F06"], "A0000000043060")
        self.assertEqual(maestro["DF810C"], "02")
        self.assertEqual(maestro["9F1D"], "4C00800000000000")
        self.assertEqual(maestro["DF19"], "000000000000")
        self.assertEqual(maestro["DF20"], "999999999999")
        self.assertEqual(maestro["DF21"], "000000100000")
        wrappers = aid_tlv.parse_tlv(bytes.fromhex(maestro["DF8A01"]))
        contactless = next(item for item in wrappers if item.tag_hex == "DF8407")
        nested = values_by_tag(contactless.value.hex())
        self.assertEqual(nested["DF8120"], "F45004800C")
        self.assertEqual(nested["DF8121"], "0000800000")
        self.assertEqual(nested["DF8122"], "F45004800C")
        self.assertEqual(nested["DF8118"], "40")
        self.assertEqual(nested["DF8119"], "28")
        self.assertEqual(nested["DF811B"], "B0")
        self.assertTrue(
            any(
                "DF8119=28 overrides SDK default 08" in notice
                for notice in maestro_profile["notices"]
            )
        )

    def test_explicit_maestro_below_limit_cvm_overrides_profile(self) -> None:
        rows = [
            (
                label,
                "Mastercard China AID, Maestro, Mastercard"
                if label.endswith("Brands (AID) supported")
                else value,
            )
            for label, value in ROWS
        ]
        rows.extend(
            [
                (
                    "Contactless Interface - Maestro - CVM supported above CVM Required Limit",
                    "Online PIN",
                ),
                (
                    "Contactless Interface - Maestro - CVM supported when No CVM Required",
                    "No CVM required",
                ),
            ]
        )
        temp, path = self.write_report(rows)
        self.addCleanup(temp.cleanup)
        result = tse.build_report(path, self.catalog, "156")
        maestro_profile = next(
            item for item in result["aids"] if item["scheme"] == "maestro"
        )
        maestro = values_by_tag(maestro_profile["tlv"])
        wrappers = aid_tlv.parse_tlv(bytes.fromhex(maestro["DF8A01"]))
        contactless = next(item for item in wrappers if item.tag_hex == "DF8407")
        nested = values_by_tag(contactless.value.hex())
        self.assertNotIn("DF8119", nested)
        self.assertTrue(
            any(
                "DF8119=08 matches the SDK default" in notice
                for notice in maestro_profile["notices"]
            )
        )

    def test_new_aid_build_defaults_df01_to_partial_matching(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            aid_tlv.command_build(
                argparse.Namespace(pairs=["9F06=A0000000041010"])
            )
        values = values_by_tag(stdout.getvalue().strip())
        self.assertEqual(values["DF01"], "00")
        self.assertIn("partial application matching", stderr.getvalue())

    def test_smart_device_build_uses_df8408_and_top_level_df8407(self) -> None:
        temp, path = self.write_report(ROWS)
        self.addCleanup(temp.cleanup)
        result = tse.build_report(path, self.catalog, "156", device="smart")
        self.assertEqual(result["device_family"], "smart")

        profiles = {item["scheme"]: item for item in result["aids"]}
        mastercard = values_by_tag(profiles["mastercard"]["tlv"])
        self.assertEqual(mastercard["DF8408"], "02")
        self.assertNotIn("DF810C", mastercard)
        self.assertNotIn("DF8A01", mastercard)
        self.assertIn("DF8407", mastercard)
        nested = values_by_tag(mastercard["DF8407"])
        self.assertEqual(nested["DF8120"], "F45084800C")
        self.assertEqual(nested["DF8121"], "0000000000")
        self.assertEqual(nested["DF8122"], "F45084800C")

        china = values_by_tag(profiles["mastercard_china"]["tlv"])
        self.assertEqual(china["DF8408"], "07")
        self.assertNotIn("DF810C", china)
        self.assertNotIn("DF8A01", china)
        for profile in result["aids"]:
            self.assertEqual(profile["device_family"], "smart")
            self.assertEqual(profile["kernel_tag"], "DF8408")
            errors, warnings = aid_tlv.validate_items(
                aid_tlv.parse_tlv(bytes.fromhex(profile["tlv"])), "smart"
            )
            self.assertEqual(errors, [])
            self.assertEqual(warnings, [])

    def test_known_smart_models_are_case_insensitive_device_aliases(self) -> None:
        for model in ("MF919", "mf360", "Mf960", "m90", "SR800"):
            with self.subTest(model=model):
                self.assertEqual(aid_tlv.normalize_device_family(model), "smart")

        aid_args = aid_tlv.build_parser().parse_args(
            ["validate", "9F0607A0000000041010", "--device", "MF919"]
        )
        self.assertEqual(aid_args.device, "smart")

        tse_args = tse.build_parser().parse_args(
            ["build", "report.html", "--device", "sr800"]
        )
        self.assertEqual(tse_args.device, "smart")

    def test_device_conversion_preserves_logical_aid_values(self) -> None:
        temp, path = self.write_report(ROWS)
        self.addCleanup(temp.cleanup)
        traditional = tse.build_report(
            path, self.catalog, "156", device="traditional"
        )
        smart = tse.build_report(path, self.catalog, "156", device="smart")
        for traditional_profile, smart_profile in zip(
            traditional["aids"], smart["aids"]
        ):
            converted = aid_tlv.adapt_device_items(
                aid_tlv.parse_tlv(bytes.fromhex(smart_profile["tlv"])),
                "traditional",
            )
            self.assertEqual(
                aid_tlv.encode_items(converted).hex().upper(),
                traditional_profile["tlv"],
            )

    def test_smart_set_other_keeps_df8407_at_top_level(self) -> None:
        original = "9F0607A0000000041010DF84080102"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            aid_tlv.command_set_other(
                argparse.Namespace(
                    tlv=original,
                    scope="contactless",
                    tag="DF811B",
                    value="B0",
                    require_existing=False,
                    device="smart",
                )
            )
        top = values_by_tag(stdout.getvalue().strip())
        self.assertNotIn("DF8A01", top)
        self.assertEqual(
            values_by_tag(top["DF8407"])["DF811B"],
            "B0",
        )

    def test_device_specific_validation_rejects_opposite_envelope(self) -> None:
        traditional = aid_tlv.parse_tlv(
            bytes.fromhex(
                "9F0607A0000000041010DF810C0102"
                "DF8A0109DF840705DF811B01B0"
            )
        )
        smart_errors, _ = aid_tlv.validate_items(traditional, "smart")
        self.assertTrue(any("DF810C" in error for error in smart_errors))
        self.assertTrue(any("DF8A01" in error for error in smart_errors))

        smart = aid_tlv.adapt_device_items(traditional, "smart")
        traditional_errors, _ = aid_tlv.validate_items(smart, "traditional")
        self.assertTrue(any("DF8408" in error for error in traditional_errors))


if __name__ == "__main__":
    unittest.main()
