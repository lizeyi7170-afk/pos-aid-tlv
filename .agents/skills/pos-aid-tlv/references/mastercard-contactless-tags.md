# Mastercard contactless AID tags

Use this reference for Mastercard contactless Tag interpretation. Treat
`aid-tag-registry.json` as the machine-readable source for Tag length, placement,
SDK defaults, TSE field names, and encoding identifiers.

## Contents

- Placement
- DF8118 and DF8119
- DF811B
- DF8120, DF8121, and DF8122
- SDK-default omission
- Adding future Tags

## Placement

Put all Tags covered here under:

```text
DF8A01 -> DF8407 -> parameter
```

Do not put these Tags at the AID top level; `MfSdkEmvSetAid` does not map them
there.

## DF8118 and DF8119

- `DF8118` describes terminal and reader CVM capability when the transaction
  amount is greater than the Reader CVM Required Limit.
- `DF8119` describes capability when the amount is less than or equal to that
  limit.

Use the same one-byte bitmap for both:

| Capability | Bit/value |
|---|---:|
| Plaintext PIN for ICC verification | b8 / `80` |
| Enciphered PIN for online verification / Online PIN | b7 / `40` |
| Signature | b6 / `20` |
| Enciphered PIN for offline verification | b5 / `10` |
| No CVM required | b4 / `08` |

Combine every supported capability with bitwise OR. For example, Signature plus
Online PIN is `20 | 40 = 60`.

For a Mastercard TSE report:

- Derive `DF8118` from `CVM supported above CVM Required Limit`.
- Derive `DF8119` only from an explicit below-limit or No-CVM capability field,
  or from a confirmed certified profile value. Never copy the above-limit field
  into `DF8119`.

## DF811B

`DF811B` is the one-byte Mastercard Kernel Configuration bitmap:

| Bit | Value | Meaning and TSE rule |
|---|---:|---|
| b8 | `80` | Set when contactless Mag-Stripe mode is not supported. |
| b7 | `40` | Set when EMV-mode contactless transactions are not supported. Keep clear when Mastercard EMV contactless is in scope. |
| b6 | `20` | Set when on-device cardholder verification/CDCVM is supported. |
| b5 | `10` | Set when Relay Resistance Protocol is supported. |
| b4 | `08` | Reserved for the payment system; leave clear unless an authoritative profile sets it. |
| b3 | `04` | Read all records without CDA; leave clear unless an authoritative profile sets it. |

Therefore Mag-Stripe=`False`, Mastercard EMV mode in scope, CDCVM=`True`, and
RRP=`Yes` produces `80 | 20 | 10 = B0`.

## DF8120, DF8121, and DF8122

Map Mastercard contactless TAC values exactly as follows:

| TSE parameter | Tag |
|---|---|
| TAC Default | `DF8120` |
| TAC Denial | `DF8121` |
| TAC Online | `DF8122` |

Keep contact TAC values separate at the top level:

- TAC Default -> `DF11`
- TAC Online -> `DF12`
- TAC Denial -> `DF13`

Do not swap Default and Online to follow the visual order of a source table or a
legacy template.

## SDK-default omission

The current SDK initializes these values before applying AID extra parameters:

| Tag | SDK default |
|---|---:|
| `DF8118` | `60` |
| `DF8119` | `08` |
| `DF811B` | `20` |

When a derived value equals the registry's `sdk_default` and
`omit_when_sdk_default` is true, omit the Tag from the generated extra
parameters. Emit the Tag only when its derived value must override the SDK.

When a TSE report has no explicit below-limit CVM capability field, omit
`DF8119` and rely on SDK default `08`.

## Adding future Tags

Add stable machine facts to `aid-tag-registry.json`. Put detailed bit semantics
and report interpretation in this file when the Tag is Mastercard contactless.
Update the generator and its tests to consume the registry; do not duplicate
the same default or mapping in `SKILL.md`.
