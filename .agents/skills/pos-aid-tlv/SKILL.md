---
name: pos-aid-tlv
description: Inspect, extract, explain, validate, build, and modify BER-TLV AID and CAPK parameters for RTOS/Linux POS device SDKs and their MfSdkEmvSetAid and MfSdkEmvSetCapk APIs. Use when a user provides an AID parameter screenshot, image, PDF, or table; mentions AID configuration, EMV application parameters, TLV hex, TAC, TTQ, contact/contactless limits, kernel ID, CAPK, CA public keys, RID, public-key index, modulus, exponent, checksum, or expiration date; or asks for C code that adds or updates an AID or CAPK.
---

# POS AID and CAPK TLV

Use the SDK implementation—not generic EMV assumptions—as the source of truth.

## AID parameter image/table workflow

1. Read `references/sdk-aid-reference.md`, then inspect the image, PDF, or table at sufficient resolution. Transcribe every AID, parameter value, number base, unit, interface, and regional restriction. Do not guess unclear characters.
2. Separate the result into confirmed source values, deterministic conversions, defaults, and unresolved values. For `DF16` and `DF17`, preserve the project percentage encoding: a source value of decimal `99` is encoded as the one-byte value `99`, not binary `63`.
3. Map common table labels to the SDK input tags:
   - AID -> `9F06`
   - application selection indicator -> `DF01`
   - application version -> `9F09`
   - TAC Default/Online/Denial -> `DF11`/`DF12`/`DF13`
   - DDOL -> `DF14`
   - biased-random threshold/maximum percentage/target percentage -> `DF15`/`DF16`/`DF17`
   - online PIN capability -> `DF18`
   - terminal floor limit -> `9F1B`
4. Do not silently equate an "Application Priority Indicator" with `DF01`. If the table means exact/partial application selection, use `DF01`; if it means EMV tag `87`, report that `MfSdkEmvSetAid` does not map tag `87` and request the intended device configuration path.
5. Treat DDOL as DOL bytes (`tag + requested length`), not as nested TLV. Omit parameters marked `N/A`; do not encode an empty value unless the source explicitly requires one.
6. When a table lists multiple AIDs, generate and validate one complete TLV per AID. Apply shared parameters only when the table clearly scopes them to every listed AID, and preserve regional restrictions in the report.
7. Determine whether the profile is contact, contactless, or both. Omit `9F66` and `DF810C` when the source does not require them. When `DF19`, `DF20`, or `DF21` is not specified for a new AID, apply `DF19=000000000000`, `DF20=999999999999`, and `DF21=000000000000` for the missing fields, then state that the contactless limits were defaulted because the source did not provide them. Never infer missing currency, exponent, terminal capabilities, or other scheme values.

## AID workflow

1. Read `references/sdk-aid-reference.md` before changing or generating AID data. Read `references/sdk-capk-reference.md` instead for CAPK work.
2. Find the complete original TLV for the target AID. Do not treat a partial update as safe: `MfSdkEmvSetAid` starts from a zeroed structure, so omitted fields become zero.
3. Never invent the AID, TAC values, currency, application version, or other business/acquirer/card-scheme values. Omit unspecified `9F66` and `DF810C`; apply only the documented `DF19`/`DF20`/`DF21` defaults when those limits are absent.
4. Use an available Python 3.8+ interpreter (`python3`, `py -3`, or the Agent's configured runtime). Inspect and validate the original data:

   ```bash
   python3 scripts/aid_tlv.py inspect "<TLV_HEX>"
   python3 scripts/aid_tlv.py validate "<TLV_HEX>" --strict
   ```

5. Apply only the requested tag changes. Use `set-auto` by default: it writes SDK-mapped main-structure tags at the top level and routes unmapped tags to contactless extra parameters under `DF8A01 -> DF8407`. Use `set` or `set-other` only to override that routing explicitly:

   ```bash
   python3 scripts/aid_tlv.py set-auto "<TLV_HEX>" DF20 000000100000
   python3 scripts/aid_tlv.py set-auto "<TLV_HEX>" DF811B 02
   python3 scripts/aid_tlv.py set-other "<TLV_HEX>" contactless DF8803 730000
   python3 scripts/aid_tlv.py remove "<TLV_HEX>" 9F7B
   ```

6. Validate the final TLV with `--strict`. Resolve every error; explain any warning that must remain.
7. If C code is requested, generate a byte array and call `MfSdkEmvSetAid` with the byte count:

   ```bash
   python3 scripts/aid_tlv.py format-c "<TLV_HEX>" --name aid_tlv
   ```

8. Report the target AID, before/after values, final TLV, byte length, validation result, and any SDK-specific caveat.

## CAPK workflow

1. Read `references/sdk-capk-reference.md`, `references/card-scheme-rids.md`, and `references/capk-catalog.json`.
2. For a CAPK lookup, query the local catalog first. Always filter by environment and identify the record by scheme or exact 5-byte RID plus 1-byte public-key index:

   ```bash
   python3 scripts/capk_catalog.py lookup --scheme unionpay --index 0B --environment test
   python3 scripts/capk_catalog.py lookup --rid A000000333 --index 0B --environment test
   python3 scripts/capk_catalog.py lookup --rid A000000003 --index 09 --environment production --processor worldpay
   ```

3. Treat catalog records with `checksum_verification=source-mismatch` as audit evidence only. Report the discrepancy and do not emit a TLV from them. Report `environment` as a normal result field without adding a separate warning banner for test records.
4. If no catalog record matches, obtain the complete certified CAPK record. Identify it by the exact `9F06 + 9F22` identity. When the source names a known card scheme but omits the RID, resolve `9F06` from `card-scheme-rids.md` and use `DF03` only to verify the resolved identity; do not brute-force candidate RIDs.
5. Never invent a modulus, exponent, checksum, or algorithm indicator. Use the card-scheme/acquirer CAPK profile. Use its expiration date when supplied; when no expiration date is available, set `DF05=20301231` and report that the skill default was applied.
6. Inspect and validate the complete original TLV:

   ```bash
   python3 scripts/capk_tlv.py inspect "<CAPK_TLV_HEX>"
   python3 scripts/capk_tlv.py validate "<CAPK_TLV_HEX>" --strict
   ```

7. Change only requested fields while keeping the full record. If `9F06`, `9F22`, `DF02`, or `DF04` changes, refresh `DF03`:

   ```bash
   python3 scripts/capk_tlv.py set "<CAPK_TLV_HEX>" DF05 20301231
   python3 scripts/capk_tlv.py set "<CAPK_TLV_HEX>" DF04 010001 --refresh-checksum
   ```

8. Validate the final TLV and report RID, index, environment, changed fields, final byte length, checksum result, and SDK caveats.
9. If C code is requested, use `capk_tlv.py format-c`; call `MfSdkEmvSetCapk` once and require return value `0`.

## Tools

`scripts/aid_tlv.py` accepts contiguous hex, spaced hex, `0xNN` arrays, C `\xNN` strings, `@path` to read a file, or `-` to read stdin. It has these commands:

- `inspect`: decode tags, lengths, values, and known nested other-parameter TLVs.
- `validate`: check BER-TLV structure, SDK-supported tags, field lengths, duplicates, required `9F06`, common value constraints, and SDK traps.
- `set-auto`: set an SDK-mapped tag at the top level; otherwise default it to canonical contactless extra parameters.
- `set`: replace a tag in place or append it if absent.
- `set-other`: add or replace a contact/contactless extra parameter using canonical `DF8A01` nesting.
- `remove`: remove one tag.
- `build`: assemble a TLV from ordered `TAG=VALUE` pairs and add the documented `DF19`/`DF20`/`DF21` defaults when those fields are omitted.
- `format-c`: generate a C byte array and `MfSdkEmvSetAid` call.

`scripts/capk_tlv.py` accepts the same input forms. It provides `inspect`, `validate`, `set`, `build`, `checksum`, `refresh-checksum`, and `format-c`.

`scripts/capk_catalog.py` queries and validates the reusable CAPK catalog:

- `list --environment <test|production>`: list catalog records and their status.
- `lookup --scheme <name> --index <hex> --environment <test|production>`: return one verified record and its complete TLV.
- `validate`: verify catalog structure, source declarations, key lengths, expiration dates, checksums, and generated TLVs.

`scripts/import_worldpay_capk_pdf.py` reproducibly rebuilds the Worldpay Test4 records from the source PDF. `scripts/import_worldpay_production_capk_pdf.py` extracts and checksum-verifies the Worldpay Production3 records for merging into the mixed-environment catalog. Keep source-specific import logic separate from the generic catalog query tool.

When extending `capk-catalog.json`, preserve all existing sources and records. Add a stable `source_id`, retain the source's original expiration text, set `environment` and `usage` explicitly, compute `computed_checksum`, and set `checksum_verification` only after comparison with the supplied checksum. Run `capk_catalog.py validate` after every addition.

## AID safety rules

- Prefer `9F09` over its accepted alias `9F08`; never include both.
- Before adding a tag, check the SDK top-level map. If the tag is absent, default it to contactless extra parameters with `set-auto`; do not append it at the top level, where `MfSdkEmvSetAid` would ignore it. Route it to contact parameters only when the user or certified profile explicitly says it is contact data.
- Do not automatically relocate unrelated unknown tags already present in the original TLV.
- Prefer the complete other-parameter representation: top-level `DF8A01`, containing `DF8406` for contact parameters and/or `DF8407` for contactless parameters. Put the business parameter TLV inside the applicable wrapper.
- Accept top-level `DF8406`/`DF8407` only as an SDK-compatible shorthand when `DF8A01` is absent; `MfSdkEmvSetAid` re-encodes those wrappers before storage.
- Never combine `DF8A01` with top-level `DF8406` or `DF8407`; `DF8A01` takes precedence and the top-level wrappers are ignored.
- Do not promise that `DF18` changes online PIN capability: this SDK forces it to `01` inside `MfSdkEmvSetAid`.
- Encode `DF16` and `DF17` using the project percentage convention; decimal `99` is the one-byte value `99`, not binary `63`.
- Allow `9F66` and `DF810C` to remain absent when the source profile does not specify them.
- For a newly built AID, default any missing contactless limits to `DF19=000000000000`, `DF20=999999999999`, and `DF21=000000000000`. Explicitly report that these defaults were applied because the source did not specify the limits.
- Do not use `MfSdkEmvGetAid` as a lossless backup of other parameters; it does not return the stored `DF8A01`/`DF8406`/`DF8407` content.
- Preserve the original tag order unless there is a concrete reason to change it.
- When editing repository code, locate the actual configuration call site before changing files and keep unrelated AIDs untouched.

## CAPK safety rules

- Treat every `MfSdkEmvSetCapk` call as a complete-record submission; omitted fields remain zero because the SDK zero-initializes `ST_CAPK`.
- Require all eight mapped tags: `9F06`, `9F22`, `DF05`, `DF06`, `DF07`, `DF02`, `DF04`, and `DF03`.
- Preserve an authoritative `DF05` value when one is supplied. If the source has no expiration date, add `DF05=20301231` and explicitly label it as the skill default.
- Resolve an omitted `9F06` from `references/card-scheme-rids.md` when the card scheme is unambiguous. Stop for clarification when the scheme is unknown or ambiguous; do not reverse-search RID candidates from `DF03`.
- Treat `9F06 + 9F22` as the CAPK identity. Changing either identifies a different CAPK; do not delete the old record unless explicitly requested.
- Recompute and verify `DF03` whenever RID, index, modulus, or exponent changes. Do not alter a supplied certified key merely to make an unexpected checksum pass.
- Never substitute a test CAPK for a production CAPK. Preserve `environment`, `usage`, `processor`, `profile`, and source metadata when adding catalog entries.
- Allow the same RID/index under different environments or profiles, but require the lookup to resolve to exactly one record before returning a TLV.
- Do not emit a CAPK TLV from a catalog record whose source checksum does not verify against its stated RID, index, modulus, and exponent.
- Never clear all CAPKs when adding or modifying one record.
- Keep unrelated CAPKs untouched when editing repository code or provisioning data.
