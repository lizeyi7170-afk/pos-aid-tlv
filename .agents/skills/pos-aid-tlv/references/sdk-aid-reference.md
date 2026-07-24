# RTOS/Linux device SDK AID TLV reference

This file documents the traditional-device implementation. Read
`device-family-routing.md` before producing an Android/smart-device AID; smart
devices share the same parameter values but use `DF8408` for Kernel ID and
top-level `DF8406`/`DF8407` without `DF8A01`.

## Contents

- Public API and source of truth
- Supported top-level tags
- Other-parameter containers
- Important implementation behavior
- Safe add/modify procedure
- C example

## Public API and source of truth

The customer-facing TLV entry point is declared in `inc/mfsdk_emv.h`:

```c
s32 MfSdkEmvSetAid(u8 *AidBuff, s32 BuffLen);
s32 MfSdkEmvDeleteOneAid(u8 *Aid, u8 aidLength);
void MfSdkEmvClearAllAid(void);
s32 MfSdkEmvGetAidNum(void);
void *MfSdkEmvGetAidsInit(void);
s32 MfSdkEmvGetAid(void *pTerminalApps, s32 index,
                   u8 *outAidsTlv, s32 outAidsTlvLength);
void MfSdkEmvGetAidsFree(void *pTerminalApps);
```

Use `g_tagMapMemInfo` in `src/mfsdk_emv.c` as the definitive input-tag map for `MfSdkEmvSetAid`. The older `APPLICATIONPARAMS` structure contains fields that are not necessarily accepted by this TLV API.

## Supported top-level tags

Lengths are bytes. Fixed-length fields are silently truncated by the current implementation when oversized, so the skill validator treats a wrong length as an error.

| Tag | Length | SDK field | Meaning / notes |
|---|---:|---|---|
| `9F06` | 5–16 | `szAID_b_9F06` | Terminal AID. Required by this skill for every add/update. |
| `DF01` | 1 | `cASI_b_DF01` | Application selection indicator. Project convention uses `00` for partial matching, and `00` is the normal default for a new AID when the source omits this field. |
| `9F09` | 2 | `szAppVer_b_9F09` | Terminal application version. Preferred tag. |
| `9F08` | 2 | same as `9F09` | Accepted alias; if both occur, `9F08` overwrites `9F09`. Do not include both. |
| `DF11` | 5 | `szTACDefault_b_DF11` | TAC Default. |
| `DF12` | 5 | `szTACOnline_b_DF12` | TAC Online. |
| `DF13` | 5 | `szTACRefuse_b_DF13` | TAC Denial. |
| `DF14` | 0–20 | `szDDOL_b_DF14` | Default DDOL; DOL format is repeated `tag + one-byte requested length`, not TLV. |
| `DF15` | 4 | `szRanhold_b_DF15` | Threshold value for biased random selection. |
| `DF16` | 1 | `cRanMaxPer_b_DF16` | Maximum target percentage; project convention uses one-byte packed decimal, so decimal 99 is encoded as `99`. |
| `DF17` | 1 | `cRanTarPer_b_DF17` | Target percentage; project convention uses one-byte packed decimal, so decimal 99 is encoded as `99`. |
| `DF18` | 1 | `cOnlinePinCap_b_DF18` | Parsed, then unconditionally forced to `01` by `MfSdkEmvSetAid`. |
| `DF19` | 6 | `sRf_OfflineLimit_DF19` | Contactless offline limit, 12-digit packed BCD in minor units. |
| `DF20` | 6 | `sRF_TxnLimit_DF20` | Contactless transaction limit, 12-digit packed BCD in minor units. |
| `DF21` | 6 | `sRf_CVMLimit_DF21` | Contactless CVM limit, 12-digit packed BCD in minor units. |
| `9F1B` | 4 | `szFloorLimit_b_9F1B` | Terminal floor limit, binary amount. |
| `5F2A` | 2 | `szCurCode_aid_5F2A` | ISO 4217 numeric transaction currency code in packed BCD. Omit unless the user explicitly requests it; do not infer it from deployment country. |
| `5F36` | 1 | `cCurExp_aid_5F36` | Transaction currency exponent. Omit unless the user explicitly specifies it; do not default it to `02`. |
| `9F3C` | 2 | `szRefCurrCode_aid_9F3C` | Reference currency code. |
| `9F3D` | 1 | `cRefCurrExp_aid_9F3D` | Reference currency exponent. |
| `9F1D` | 0–8 | `cRiskManage_aid_9F1D` | Terminal risk-management data. |
| `9F33` | 3 | `cTerminalCap_9F33` | Terminal capabilities. |
| `9F66` | 4 | `cTTQ_9F66` | TTQ. Obtain the value from the acquirer/scheme profile. |
| `9F15` | 2 | `szMerCateCode_9F15` | Merchant category code in packed BCD. |
| `9F7B` | 6 | `sEcLimit_9F7B` | Electronic-cash terminal transaction limit, packed BCD. |
| `DF810C` | 1 | `cKernelID` | `02` Mastercard, `03` Visa, `04` Amex, `05` JCB, `06` Discover, `07` UnionPay, `09` Pure. |
| `DF8A01` | 0–255 | other-TLV record | Preferred complete nested other-parameter stream. Its value normally contains `DF8406` and/or `DF8407`. |
| `DF8406` | 0–250 | contact other params | SDK-compatible top-level shorthand; used only when `DF8A01` is absent and wrapped internally before storage. |
| `DF8407` | 0–250 | contactless other params | SDK-compatible top-level shorthand; used only when `DF8A01` is absent and wrapped internally before storage. |

Notably, tag `87` (priority) and `cAidFileType` exist in other SDK structures but are not mapped by `MfSdkEmvSetAid`; supplying them at the top level has no effect through this API.

`9F66` and `DF810C` may be omitted when the source profile does not require them. Omit `5F2A` and `5F36` unless the user explicitly requests those fields. For a newly generated AID, default a missing application selection indicator to `DF01=00` for partial matching. Default missing contactless limits to `DF19=000000000000`, `DF20=999999999999`, and `DF21=000000000000`. Disclose every value supplied by the skill rather than the source profile.

## Other-parameter containers

Use the complete representation by default:

```text
DF8A01 <length>
  DF8406 <length> <contact parameter TLVs>
  DF8407 <length> <contactless parameter TLVs>
    DF840A <length> <contactless refund parameter TLVs>
```

`MfSdkEmvSetAid` also accepts `DF8406` and `DF8407` directly at the top level when `DF8A01` is absent. That is a shorthand: the SDK extracts their values, reconstructs the wrapper TLVs, and stores the resulting complete other-parameter stream. Prefer `DF8A01` when generating new data because it represents the stored hierarchy explicitly and is less dependent on this SDK convenience path.

If `DF8A01` exists, the SDK copies its value directly and does not process top-level `DF8406` or `DF8407`. Do not mix the two representations. Every nested value must be valid BER-TLV. The stored other-parameter length is one byte, so keep the value of `DF8A01` at or below 255 bytes.

### Default placement for a requested tag

1. If the tag appears in the supported top-level table above, add or replace it at the top level.
2. If the tag does not appear in that table, put it in contactless extra parameters by default: `DF8A01 -> DF8407 -> tag`.
3. Use `DF8406` instead only when the user or certified profile explicitly identifies the tag as contact data.
4. Do not place an unmapped tag at the top level; `MfSdkEmvSetAid` ignores it there.
5. Apply this routing only to the requested tag. Preserve unrelated unknown tags already present in the source TLV and report their warnings.

Use `scripts/aid_tlv.py set-auto` to apply this rule deterministically.

Example: `DF811B` is absent from the SDK top-level map, so adding `DF811B=02` produces:

```text
parameter:    DF811B 01 02
RF wrapper:   DF8407 05 DF811B0102
full input:   DF8A01 09 DF840705DF811B0102
encoded:      DF8A0109DF840705DF811B0102
```

Example: add the three-byte tag `DF8803` with length `03` and value `730000` to contactless extra parameters:

```text
parameter:    DF8803 03 730000
RF wrapper:   DF8407 07 DF880303730000
full input:   DF8A01 0B DF840707DF880303730000
encoded:      DF8A010BDF840707DF880303730000
```

This is only an encoding example. Scheme values must come from the applicable certified profile.

### Contactless refund parameters

Use `DF840A` as a nested container for the parameter stream that applies to a
contactless refund:

```text
DF8A01
  DF8407
    <normal contactless parameter TLVs>
    DF840A
      <contactless refund parameter TLVs>
```

`SaveEmvAidOtherParamListData_ex` removes `DF840A` from the normal contactless
parameter list and, when transaction type is `0x20`, loads the TLV stream in its
value as the refund configuration. Consequently:

- Put `DF840A` inside `DF8407`, normally under top-level `DF8A01`.
- Encode the value of `DF840A` as a complete BER-TLV stream, not as an opaque
  flag or a single transaction-type byte.
- Keep ordinary `DF8407` children as the normal contactless configuration.
- Do not put `DF840A` at the AID top level, where `MfSdkEmvSetAid` does not map
  it.
- Respect the enclosing `DF8407` and `DF8A01` size limits even though the
  refund handler's local buffer accepts up to 256 value bytes.

Use `set-auto` or `set-other ... contactless` with Tag `DF840A`; both produce
the required `DF8A01 -> DF8407 -> DF840A` placement. Validate the completed AID
so the nested refund value is checked as TLV.

### Mastercard contactless parameters

Read `mastercard-contactless-tags.md` for the interpretation of Mastercard
contactless TAC, CVM capability, and Kernel Configuration. Use
`aid-tag-registry.json` as the machine-readable source for their placement,
length, encoding, report-field mapping, and SDK-default omission.

## Important implementation behavior

1. `MfSdkEmvSetAid` zero-initializes `ST_TERMAID`, scans only its hard-coded tag map, and then calls `Emv_AddAID(..., YES)`. Missing tags therefore remain zero; an unknown top-level tag is ignored.
2. Oversized mapped values are copied only up to the destination field size without returning an error. Validate before calling the SDK.
3. `DF18` is overwritten with `YES` after TLV parsing, regardless of the supplied value.
4. `DF8A01` is checked first. When present, its value is copied directly to `ST_AIDOTHERTLV.szOtherTLV`. Top-level `DF8406` and `DF8407` are considered only when `DF8A01` has no value; the SDK then reconstructs those wrapper TLVs in `szOtherTLV`.
5. `MfSdkEmvGetAid` requires an output buffer of at least 1024 bytes and uses a zero-based index.
6. `MfSdkEmvGetAid` is not a lossless round trip: its output map omits the stored other-parameter record. Do not reconstruct a production AID solely from this output if other parameters may exist.
7. `EMV_PrmGetAIDPrm` also does not populate the `szOtherTLV` fields used by the TLV getter path.

## Safe add/modify procedure

For a new AID:

1. Obtain a certified parameter profile from the acquirer or card scheme.
2. Build a complete flat TLV stream with `9F06` and every required scheme/terminal parameter.
3. Validate it with `scripts/aid_tlv.py validate ... --strict`.
4. Call `MfSdkEmvSetAid` once and check for return value `0`.

For an existing AID:

1. Start from the complete source TLV previously used to provision it, including other parameters.
2. Identify the record by the full `9F06` value. Do not modify another AID with the same RID prefix.
3. Change only the requested tags. Use `scripts/aid_tlv.py set-auto` for normal additions and modifications. Use `set-other` when the contact/contactless scope is explicitly supplied.
4. Re-submit the complete TLV. Do not send only `9F06` plus the changed tag.
5. Read back the normal fields when possible, while remembering that other parameters are omitted by the getter.

If the complete original TLV is unavailable, stop and request it or an authoritative replacement profile. A partial reconstruction can silently reset security and risk parameters.

## C example

```c
static unsigned char aid_tlv[] = {
    /* complete validated TLV bytes */
};

s32 ret = MfSdkEmvSetAid(aid_tlv, (s32)sizeof(aid_tlv));
if (ret != 0) {
    /* handle provisioning failure */
}
```

Do not call `MfSdkEmvClearAllAid` as part of a single-AID modification unless replacing the entire certified AID set is explicitly intended.
