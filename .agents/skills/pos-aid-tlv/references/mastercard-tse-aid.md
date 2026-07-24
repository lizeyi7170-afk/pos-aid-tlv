# Mastercard TSE/M-TIP AID generation

## Contents

- Scope and source precedence
- Report extraction
- SDK tag mapping
- Amount, mask, and currency conversions
- Profile requirements
- Answer contract
- Validation and reporting

## Scope and source precedence

Use `scripts/mastercard_tse_aid.py` for Mastercard TSE/M-TIP L3 HTML reports.
Generate one complete device-specific AID TLV for every AID brand listed under
either the contact or contactless interface. Read `device-family-routing.md`
and select `--device traditional` or `--device smart`.

Apply values in this order:

1. Exact values and constraints in the current TSE report.
2. Explicit fixed overrides recorded in `aid-profile-catalog.json`.
3. The selected complete base profile.

Do not reuse a previous report's values merely because most fields are similar. Do not emit a final TLV when a listed brand has no complete base profile.

Maestro uses the complete catalog profile with `9F06=A0000000043060`,
logical Kernel ID `02`, and fixed `9F1D=4C00800000000000`. Encode the Kernel
ID as `DF810C` for traditional devices or `DF8408` for smart devices. Apply the same
Mastercard tag placement, conversion, default-omission, and nesting rules, but
take TAC, limits, CVM, and other scheme-scoped values from the Maestro rows in
the current report whenever they are present. When the report has
`DF8118=40` from Online PIN above the CVM limit but omits the below-limit
capability, derive and emit `DF8119=28` for Signature plus No CVM.

## Report extraction

Treat the HTML as a label/value table collection. The export can contain malformed table nesting, so parse closed `tr` rows and their `td` or `th` cells without relying on strict DOM hierarchy.

Preserve the first-column heading of every contactless TAC table. Repeated
labels such as `TAC Default`, `TAC Online`, and `TAC Denial` belong to distinct
transaction profiles when their table headings differ; do not flatten them
into one label/value map before classifying the table.

Use both brand fields:

- `Contact Interface - Brands (AID) supported`
- `Contactless Interface - Brands (AID) supported`

Take their ordered union. A report can include Mastercard, Mastercard China AID, Maestro, or a subset. Do not assume Maestro is always present or absent.

Do not copy the original report into the skill or repository. Reports can contain acquirer names, addresses, contact names, and email addresses. Use sanitized inline HTML for automated tests.

## SDK tag mapping

Map contact values to the SDK top-level AID fields:

| TSE field | SDK tag |
|---|---|
| Contact TAC Default | `DF11` |
| Contact TAC Online | `DF12` |
| Contact TAC Denial | `DF13` |
| Contact floor limit | `9F1B` |
| Contact terminal capabilities | `9F33` |

Map contactless Mastercard or Maestro values as follows:

| TSE field | SDK location |
|---|---|
| Floor Limit | top-level `DF19` |
| Transaction Limit (No CDCVM) | top-level `DF20` |
| CVM Required Limit | top-level `DF21` |

For Mastercard contactless TAC, CVM capability, and Kernel Configuration Tags,
read `mastercard-contactless-tags.md`. Use `aid-tag-registry.json` as the
machine-readable source for placement, length, report-field mapping, encoding,
and SDK-default omission. The generator loads these rules directly.

When CDCVM and No-CDCVM transaction limits differ, encode the No-CDCVM limit as nested `DF8124` and the CDCVM limit as nested `DF8125`, while retaining `DF20` as the No-CDCVM value.

For Mastercard China, honor an explicit report label such as `Floor Limit value (Tag 9F1B)` as `9F1B`. Apply the catalog's certified kernel ID and TTQ.

The SDK source defines `DF11` as TAC Default and `DF12` as TAC Online. If a base template contains the report's online value in `DF11` or default value in `DF12`, replace them according to the SDK mapping and report the change.

For transaction-specific contactless TAC tables:

- Put the standard Purchase TAC set under the registry path:
  `DF8A01 -> DF8407` for traditional devices or top-level `DF8407` for smart
  devices.
- When a table heading identifies Refund, encode its complete TAC set as the
  value of `DF840A` under the selected device family's `DF8407`.
- Keep `DF8120` as Default, `DF8121` as Denial, and `DF8122` as Online inside
  both sets.
- If multiple non-refund transaction tables contain different TAC sets and no
  SDK transaction container is defined for them, stop instead of choosing one.

## Amount, mask, and currency conversions

Convert contactless `DF19`, `DF20`, and `DF21` amounts to 12 decimal digits by left-padding with zeroes, then encode them as six packed-BCD bytes:

```text
100000 -> 000000100000
30000  -> 000000030000
0      -> 000000000000
```

Convert `9F1B` from a non-negative decimal report value to a four-byte big-endian binary value.

The TSE expresses `9F33` bytes as binary masks. Resolve each byte independently:

- Byte 1: replace every `?` with `1`.
- Byte 2: require all bits to be explicit unless a future catalog policy defines a default.
- Byte 3: replace every `?` with `0`.

Example:

```text
???00000 11111000 11?01000 -> 11100000 11111000 11001000 -> E0F8C8
```

Do not configure `5F2A` or `5F36` from the report's deployment country. Omit
both Tags silently unless the user explicitly requests them.

When the user explicitly requests `5F2A`, accept a confirmed three-digit ISO
4217 numeric code through `--currency-code`; the generator left-pads it to four
packed-BCD digits, for example `458` becomes `5F2A=0458`. If the user requests
the Tag but supplies only a country or currency name, use the current official
ISO 4217 Maintenance Agency list to resolve the code. Stop for ambiguity rather
than choosing a fallback.

Configure `5F36` only when the user explicitly requests an exponent and pass
it with `--currency-exponent`. Require `--currency-code` with it. Do not infer
either Tag from a catalog profile, previous report, deployment country, or ISO
minor-unit column, and do not mention omitted currency Tags.

## Profile requirements

Every profile must declare:

- stable profile ID
- report brand name
- exact `9F06`
- logical Kernel ID
- complete base TLV
- environment and source
- any certified fixed overrides

The base TLV supplies fields the report normally omits, including `DF01`, `9F09`, `DF14`, `DF15`, `DF16`, `DF17`, and SDK-specific contactless parameters. This project interprets `DF01=00` as partial application matching and uses it as the normal new-AID default.

The catalog stores complete base TLVs in traditional-device form. The generator
applies TSE values to that shared logical profile, then renders the final
device-specific envelope without changing business parameter values.

Current catalog status:

- Mastercard `A0000000041010`, kernel `02`: complete user-provided base profile.
- Mastercard China `A0000000108888`, kernel `07`: complete user-provided base profile.
- Maestro `A0000000043060`, kernel `02`: complete user-confirmed base profile using Mastercard mapping and nesting rules, Maestro-scoped report values, and fixed `9F1D=4C00800000000000`.

## Answer contract

Treat a request asking which AIDs should be configured, a request to generate
AIDs from a TSE report, or a supplied TSE report without a narrower question as
a request for every complete in-scope AID TLV. Do not stop after identifying
brands, `9F06`, or a Kernel ID Tag, and do not ask whether the user also wants the
complete records.

Put the complete validated TLVs first. Each TLV must be uppercase and contiguous
on one line in its own fenced `text` block. After all TLVs, map their order to
the report brands and give `9F06`, kernel, byte length, derivations, defaults,
validation results, and SDK caveats. Mention `5F2A` or `5F36` only when it was
explicitly requested and included. If a complete profile is unavailable,
state the blocker instead of returning a partial TLV.

## Validation and reporting

Run:

```bash
python3 scripts/mastercard_tse_aid.py inspect "<REPORT.html>"
python3 scripts/mastercard_tse_aid.py build "<REPORT.html>" --device smart
python3 scripts/mastercard_tse_aid.py validate "<REPORT.html>" --device smart
```

For each generated AID:

1. Verify the catalog identity, Kernel ID value, and device-specific Kernel ID Tag.
2. Require a complete set of SDK AID tags.
3. Validate the final TLV through `aid_tlv.validate_items` with the selected device family.
4. Preserve unrelated base-profile parameters.
5. Report report-derived values, mask substitutions, explicitly requested currency fields, base values replaced by the report, byte length, and validation warnings. Do not mention omitted `5F2A` or `5F36`.

Never put `?`, `N/A`, `See ... Table`, or another placeholder into a generated hexadecimal TLV.
