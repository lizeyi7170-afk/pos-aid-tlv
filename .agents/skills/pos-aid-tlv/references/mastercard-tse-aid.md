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

Use `scripts/mastercard_tse_aid.py` for Mastercard TSE/M-TIP L3 HTML reports. Generate one complete `MfSdkEmvSetAid` TLV for every AID brand listed under either the contact or contactless interface.

Apply values in this order:

1. Exact values and constraints in the current TSE report.
2. Explicit fixed overrides recorded in `aid-profile-catalog.json`.
3. The selected complete base profile.

Do not reuse a previous report's values merely because most fields are similar. Do not emit a final TLV when a listed brand has no complete base profile.

Maestro uses the complete catalog profile with `9F06=A0000000043060`,
`DF810C=02`, and fixed `9F1D=4C00800000000000`. Apply the same
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

- Put the standard Purchase TAC set directly under `DF8A01 -> DF8407`.
- When a table heading identifies Refund, encode its complete TAC set as the
  value of `DF840A` under `DF8A01 -> DF8407`.
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

Read `Deployment country`, then use an internet or connected authoritative lookup against the current ISO 4217 Maintenance Agency list to obtain the country's three-digit numeric transaction-currency code. Pass that value explicitly as `--currency-code`. The generator left-pads it to four decimal digits for the two-byte packed-BCD `5F2A` value; for example, Malaysia's ISO code `458` becomes `5F2A=0458`.

Never use `0840`, a catalog mapping, or a previous report as an unknown-country fallback. If the deployment country is missing, ambiguous, or has more than one plausible transaction currency, stop and obtain confirmation instead of choosing one.

Do not configure `5F36` by default. Omit it unless the user explicitly specifies a currency exponent, in which case pass `--currency-exponent`. Do not infer `5F36` from the ISO 4217 minor-unit column.

## Profile requirements

Every profile must declare:

- stable profile ID
- report brand name
- exact `9F06`
- `DF810C`
- complete base TLV
- environment and source
- any certified fixed overrides

The base TLV supplies fields the report normally omits, including `DF01`, `9F09`, `DF14`, `DF15`, `DF16`, `DF17`, and SDK-specific contactless parameters. This project interprets `DF01=00` as partial application matching and uses it as the normal new-AID default.

Current catalog status:

- Mastercard `A0000000041010`, kernel `02`: complete user-provided base profile.
- Mastercard China `A0000000108888`, kernel `07`: complete user-provided base profile.
- Maestro `A0000000043060`, kernel `02`: complete user-confirmed base profile using Mastercard mapping and nesting rules, Maestro-scoped report values, and fixed `9F1D=4C00800000000000`.

## Answer contract

Treat a request asking which AIDs should be configured, a request to generate
AIDs from a TSE report, or a supplied TSE report without a narrower question as
a request for every complete in-scope AID TLV. Do not stop after identifying
brands, `9F06`, or `DF810C`, and do not ask whether the user also wants the
complete records.

Put the complete validated TLVs first. Each TLV must be uppercase and contiguous
on one line in its own fenced `text` block. After all TLVs, map their order to
the report brands and give `9F06`, kernel, byte length, derivations, defaults,
validation results, and SDK caveats. State the `5F2A` currency used and ask the
user to confirm whether it should be changed. State that `5F36` was omitted
when the user did not explicitly request it. If a complete profile is unavailable,
state the blocker instead of returning a partial TLV.

## Validation and reporting

Run:

```bash
python3 scripts/mastercard_tse_aid.py inspect "<REPORT.html>"
python3 scripts/mastercard_tse_aid.py build "<REPORT.html>" --currency-code 458
python3 scripts/mastercard_tse_aid.py validate "<REPORT.html>" --currency-code 458
```

For each generated AID:

1. Verify the catalog identity and kernel ID.
2. Require a complete set of SDK AID tags.
3. Validate the final TLV through `aid_tlv.validate_items`.
4. Preserve unrelated base-profile parameters.
5. Report report-derived values, mask substitutions, authoritative currency lookup and confirmation request, explicit `5F36` inclusion or omission, base values replaced by the report, byte length, and validation warnings.

Never put `?`, `N/A`, `See ... Table`, or another placeholder into a generated hexadecimal TLV.
