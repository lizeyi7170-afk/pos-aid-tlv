---
name: pos-aid-tlv
description: Inspect, extract, explain, validate, build, and modify BER-TLV AID and CAPK parameters for RTOS/Linux POS device SDKs and their MfSdkEmvSetAid and MfSdkEmvSetCapk APIs. Use when a user asks which AIDs should be configured; provides an AID parameter screenshot, image, PDF, table, Mastercard TSE/M-TIP L3 HTML report, or certification profile; mentions AID configuration, EMV application parameters, TLV hex, TAC, TTQ, contact/contactless limits, kernel ID, CAPK, CA public keys, RID, public-key index, modulus, exponent, checksum, or expiration date; or asks for C code that adds or updates an AID or CAPK. For AID configuration requests, produce complete validated AID TLVs before explaining individual Tags such as 9F06.
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

1. Read `references/sdk-aid-reference.md` and `references/aid-tag-registry.json` before changing or generating AID data. For Mastercard contactless Tags, also read `references/mastercard-contactless-tags.md`. Read `references/sdk-capk-reference.md` instead for CAPK work.
2. Find the complete original TLV for the target AID. Do not treat a partial update as safe: `MfSdkEmvSetAid` starts from a zeroed structure, so omitted fields become zero.
3. Never invent the AID, TAC values, currency, application version, or other business/acquirer/card-scheme values. For a new AID whose source omits the selection indicator, apply the project default `DF01=00` for partial application matching and report the default. Omit unspecified `9F66` and `DF810C`; apply only the documented `DF19`/`DF20`/`DF21` defaults when those limits are absent.
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

## AID output contract

1. Treat "which AIDs should I configure?", "what AID configuration is required?", a request to generate AIDs from a TSE/L3 report, or a TSE/L3 report supplied without a narrower question as a request for the complete validated `MfSdkEmvSetAid` TLV for every in-scope AID. Do not interpret "AID" as a request for only Tag `9F06`.
2. When complete records can be generated, begin the final answer with the AID TLVs. Put each complete uppercase TLV on exactly one continuous line in its own fenced `text` code block. Do not insert spaces, line breaks, separators, comments, Tag labels, or ellipses inside a TLV.
3. After all requested TLVs, explain their order and report brand, `9F06`, `DF810C`, byte length, derived/defaulted values, validation result, and necessary SDK caveats. State the ISO 4217 numeric currency encoded in `5F2A` and ask the user to confirm whether it needs to change. Do not lead with a brand/`9F06` table and do not ask whether the user wants the complete TLVs.
4. If the user explicitly requests only one brand, output only that brand's complete TLV. If a complete record cannot be generated safely, explain the exact blocker instead of returning a partial TLV or presenting a `9F06` list as the configuration result.
5. Provide C arrays or `MfSdkEmvSetAid` calls only when requested; the default deliverable is the complete TLV.

## Mastercard TSE/M-TIP L3 report workflow

1. Read `references/mastercard-tse-aid.md`, `references/mastercard-contactless-tags.md`, `references/aid-tag-registry.json`, `references/aid-profile-catalog.json`, and `references/sdk-aid-reference.md`.
2. Inspect the report before building. Parse the ordered union of contact and contactless brand lists; generate every listed supported brand, including Maestro when present:

   ```bash
   python3 scripts/mastercard_tse_aid.py inspect "<REPORT.html>"
   ```

3. Treat exact report values as overrides of the complete base profile. Convert binary masks and decimal amounts only with the documented deterministic rules. Never encode `?`, `N/A`, an external-table pointer, or another placeholder.
4. Resolve `9F33` binary masks byte by byte: default `?` to `1` in byte 1 and to `0` in byte 3; require an explicit policy for any other unresolved bit.
5. Read the deployment country, then look up its current ISO 4217 numeric transaction-currency code from the authoritative ISO 4217 Maintenance Agency source. Pass the looked-up code with `--currency-code`; never use `0840` or another code as an unknown-country fallback. ISO codes are three decimal digits, while `5F2A` is two-byte packed BCD, so the generator left-pads the value (for example, Malaysia `458` becomes `5F2A=0458`). In the answer, state the `5F2A` value used and ask the user to confirm whether the transaction currency should be changed. Do not configure `5F36` unless the user explicitly specifies a currency exponent; only then pass `--currency-exponent`.
6. Keep contact TAC at the top level and use the registry mapping for Mastercard/Maestro contactless TAC under `DF8A01 -> DF8407`. Preserve each contactless TAC table heading: apply the standard Purchase set to normal `DF8407`, and encode a table whose heading identifies Refund under `DF8407 -> DF840A`. Do not merge same-named TAC rows across transaction tables or report them as conflicts when their headings distinguish Purchase from Refund. Follow the SDK mapping even when a base template has Default and Online values swapped, and report the correction.
7. Stop for any listed brand that still lacks a complete base profile. Maestro uses the catalog profile `9F06=A0000000043060`, `DF810C=02`, the Mastercard field-mapping and nesting rules, Maestro-scoped TSE values, and the fixed `9F1D=4C00800000000000`; do not substitute Mastercard-scoped TAC, limit, or CVM values when Maestro-specific values are present.
8. Build and validate every result:

   ```bash
   python3 scripts/mastercard_tse_aid.py build "<REPORT.html>" --currency-code 458
   python3 scripts/mastercard_tse_aid.py validate "<REPORT.html>" --currency-code 458
   ```

9. Follow the AID output contract. Emit every complete generated TLV before report analysis or Tag explanations; a list of brands, `9F06` values, or kernel IDs is supplemental context, not the requested configuration.
10. Do not add the original report to the skill or repository because it can contain personal and acquirer information. Use sanitized HTML snippets for tests.

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

8. Validate the final TLV. When a valid CAPK TLV can be emitted, make it the first item in the final answer. Put the entire uppercase hexadecimal TLV on exactly one line in a fenced `text` code block. Keep it contiguous: do not insert line breaks, spaces, separators, comments, tag labels, or ellipses inside the TLV.
9. After the complete TLV, report RID, index, environment, expiration date, changed or defaulted fields, final byte length, checksum result, and SDK caveats.
10. If C code is requested, use `capk_tlv.py format-c`; call `MfSdkEmvSetCapk` once and require return value `0`.

## Tools

`scripts/aid_tlv.py` accepts contiguous hex, spaced hex, `0xNN` arrays, C `\xNN` strings, `@path` to read a file, or `-` to read stdin. It has these commands:

- `inspect`: decode tags, lengths, values, and known nested other-parameter TLVs.
- `validate`: check BER-TLV structure, SDK-supported tags, field lengths, duplicates, required `9F06`, common value constraints, and SDK traps.
- `set-auto`: set an SDK-mapped tag at the top level; otherwise default it to canonical contactless extra parameters.
- `set`: replace a tag in place or append it if absent.
- `set-other`: add or replace a contact/contactless extra parameter using canonical `DF8A01` nesting.
- `remove`: remove one tag.
- `build`: assemble a TLV from ordered `TAG=VALUE` pairs and add the documented `DF01`/`DF19`/`DF20`/`DF21` defaults when those fields are omitted.
- `format-c`: generate a C byte array and `MfSdkEmvSetAid` call.

`scripts/capk_tlv.py` accepts the same input forms. It provides `inspect`, `validate`, `set`, `build`, `checksum`, `refresh-checksum`, and `format-c`.

`scripts/capk_catalog.py` queries and validates the reusable CAPK catalog:

- `list --environment <test|production>`: list catalog records and their status.
- `lookup --scheme <name> --index <hex> --environment <test|production>`: return one verified record and its complete TLV.
- `validate`: verify catalog structure, source declarations, key lengths, expiration dates, checksums, and generated TLVs.

`scripts/mastercard_tse_aid.py` parses Mastercard TSE/M-TIP L3 HTML reports:

- `inspect`: list report brands, deployment country, and deterministically resolved `9F33`; without `--currency-code`, report that an authoritative currency lookup is still required.
- `build`: overlay report TAC, limits, capabilities, and the explicitly supplied regional currency onto complete catalog profiles and emit one validated TLV per listed AID.
- `validate`: require every listed brand to have a complete profile and validate every generated TLV.

`references/aid-tag-registry.json` is the machine-readable source for migrated AID Tag length, placement, nesting, encoding, report-field mapping, and SDK-default omission rules. Put detailed Mastercard bit semantics in `references/mastercard-contactless-tags.md`; do not duplicate them in `SKILL.md`.

`scripts/import_worldpay_capk_pdf.py` reproducibly rebuilds the Worldpay Test4 records from the source PDF. `scripts/import_worldpay_production_capk_pdf.py` extracts and checksum-verifies the Worldpay Production3 records for merging into the mixed-environment catalog. Keep source-specific import logic separate from the generic catalog query tool.

When extending `capk-catalog.json`, preserve all existing sources and records. Add a stable `source_id`, retain the source's original expiration text, set `environment` and `usage` explicitly, compute `computed_checksum`, and set `checksum_verification` only after comparison with the supplied checksum. Run `capk_catalog.py validate` after every addition.

## AID safety rules

- Prefer `9F09` over its accepted alias `9F08`; never include both.
- Interpret `DF01=00` as partial application matching in this project. For a new AID whose source omits `DF01`, default it to `00` and disclose the default.
- Before adding a tag, check the SDK top-level map. If the tag is absent, default it to contactless extra parameters with `set-auto`; do not append it at the top level, where `MfSdkEmvSetAid` would ignore it. Route it to contact parameters only when the user or certified profile explicitly says it is contact data.
- Do not automatically relocate unrelated unknown tags already present in the original TLV.
- Prefer the complete other-parameter representation: top-level `DF8A01`, containing `DF8406` for contact parameters and/or `DF8407` for contactless parameters. Put the business parameter TLV inside the applicable wrapper.
- Treat `DF840A` as the contactless refund-configuration container. Put it under `DF8A01 -> DF8407 -> DF840A`; its value must be a complete BER-TLV stream containing the parameters to apply when transaction type `0x20` selects a contactless refund. Never put `DF840A` at the AID top level.
- For Mastercard contactless `DF8118`, `DF8119`, `DF811B`, `DF8120`, `DF8121`, and `DF8122`, use `references/aid-tag-registry.json` as the machine-readable source and `references/mastercard-contactless-tags.md` for interpretation. Do not maintain duplicate bit maps, TAC mappings, or SDK defaults here.
- Accept top-level `DF8406`/`DF8407` only as an SDK-compatible shorthand when `DF8A01` is absent; `MfSdkEmvSetAid` re-encodes those wrappers before storage.
- Never combine `DF8A01` with top-level `DF8406` or `DF8407`; `DF8A01` takes precedence and the top-level wrappers are ignored.
- Do not promise that `DF18` changes online PIN capability: this SDK forces it to `01` inside `MfSdkEmvSetAid`.
- Encode `DF16` and `DF17` using the project percentage convention; decimal `99` is the one-byte value `99`, not binary `63`.
- Allow `9F66` and `DF810C` to remain absent when the source profile does not specify them.
- For a newly built AID, default any missing contactless limits to `DF19=000000000000`, `DF20=999999999999`, and `DF21=000000000000`. Explicitly report that these defaults were applied because the source did not specify the limits.
- For a Mastercard TSE/M-TIP report, use the report's exact limits instead of the generic new-AID defaults. Left-pad decimal contactless amounts to 12 digits before packed-BCD encoding.
- Keep TSE base profiles in `references/aid-profile-catalog.json`. Do not generate a listed brand whose complete base TLV is absent.
- Never answer an AID-configuration or TSE-report request with only brand names, `9F06`, or `DF810C`. Return complete validated AID TLVs first whenever they can be generated safely.
- Treat TSE `9F33` question marks as constrained mask bits, not hexadecimal input. Apply only the documented byte-specific substitutions and report them.
- Resolve TSE currency by looking up the deployment country's current numeric code from the authoritative ISO 4217 Maintenance Agency source. Supply that code explicitly to the generator, encode its three digits as four packed-BCD digits in `5F2A`, and never use `0840` as an unknown-country fallback. Tell the user which `5F2A` was used and ask whether it should change.
- Omit `5F36` unless the user explicitly specifies a currency exponent. Do not infer or default `5F36=02` from the ISO minor-unit column or from a prior profile.
- Do not use `MfSdkEmvGetAid` as a lossless backup of other parameters; it does not return the stored `DF8A01`/`DF8406`/`DF8407` content.
- Preserve the original tag order unless there is a concrete reason to change it.
- When editing repository code, locate the actual configuration call site before changing files and keep unrelated AIDs untouched.

## CAPK safety rules

- For a successfully generated CAPK, output no prose before the complete TLV. Never split a CAPK TLV for readability, regardless of its length.
- If required data is missing, ambiguous, or fails checksum verification, explain the blocker instead of emitting a fabricated, partial, or unverified TLV.
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
