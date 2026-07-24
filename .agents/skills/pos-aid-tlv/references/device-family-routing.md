# Device-family routing

Use one shared AID/CAPK knowledge base and select the final AID encoding by
device family.

## Terminology and aliases

| Canonical value | User-facing name | Recognized aliases |
|---|---|---|
| `traditional` | traditional device | RTOS, Linux, traditional, 传统设备 |
| `smart` | smart device | Android, smart, intelligent, 智能设备 |

## Model defaults and precedence

Treat these model names as smart devices, case-insensitively:

| Model | Default device family |
|---|---|
| MF919 | `smart` |
| MF360 | `smart` |
| MF960 | `smart` |
| M90 | `smart` |
| SR800 | `smart` |

Apply device routing in this order:

1. Use an explicitly stated device family when the user supplies one.
2. Otherwise, use the recognized model default above without asking the device
   family again.
3. Otherwise, ask whether the AID targets a smart device or a traditional
   device before emitting a final TLV.

For example, `MF919` selects `smart`, while an explicit request for
`MF919 traditional device` selects `traditional`. Do not ask for CAPK work
because CAPK TLVs are identical on both device families.

## AID encoding differences

All AID business values, Tag lengths, TAC mappings, limits, CVM rules, profile
values, and Mastercard TSE derivations are shared. Only these encoding rules
differ:

| Rule | Traditional device (RTOS/Linux) | Smart device (Android) |
|---|---|---|
| Kernel ID Tag | `DF810C` | `DF8408` |
| Contact parameter path | `DF8A01 -> DF8406` | top-level `DF8406` |
| Contactless parameter path | `DF8A01 -> DF8407` | top-level `DF8407` |
| Contactless refund path | `DF8A01 -> DF8407 -> DF840A` | `DF8407 -> DF840A` |

The Kernel ID value is unchanged. For example, Mastercard remains `02` and
Mastercard China remains `07`.

Never put `DF8A01` in a smart-device AID. Never put `DF810C` and `DF8408` in the
same AID.

## CAPK behavior

Use the same CAPK catalog, TLV structure, validation, and output for both
device families. Do not duplicate CAPK records or alter a CAPK merely because
the target is Android.

## Output and validation

Emit the complete contiguous AID TLV first, then identify the selected device
family. Validate these invariants:

- A smart-device AID uses `DF8408`, omits `DF810C`, omits `DF8A01`, and keeps
  `DF8406`/`DF8407` directly at the top level when present.
- A traditional-device AID uses `DF810C`, omits `DF8408`, and uses
  `DF8A01 -> DF8406/DF8407` for generated extra parameters.
- A device-family conversion changes only the platform envelope and Kernel ID
  Tag; it preserves all logical parameter values.
