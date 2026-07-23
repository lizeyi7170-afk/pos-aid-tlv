# SR600 SDK AID TLV reference

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
| `DF01` | 1 | `cASI_b_DF01` | Application selection indicator; normally `00` exact match or `01` partial match. |
| `9F09` | 2 | `szAppVer_b_9F09` | Terminal application version. Preferred tag. |
| `9F08` | 2 | same as `9F09` | Accepted alias; if both occur, `9F08` overwrites `9F09`. Do not include both. |
| `DF11` | 5 | `szTACDefault_b_DF11` | TAC Default. |
| `DF12` | 5 | `szTACOnline_b_DF12` | TAC Online. |
| `DF13` | 5 | `szTACRefuse_b_DF13` | TAC Denial. |
| `DF14` | 0–20 | `szDDOL_b_DF14` | Default DDOL; DOL format is repeated `tag + one-byte requested length`, not TLV. |
| `DF15` | 4 | `szRanhold_b_DF15` | Threshold value for biased random selection. |
| `DF16` | 1 | `cRanMaxPer_b_DF16` | Maximum target percentage; binary integer 0–100. |
| `DF17` | 1 | `cRanTarPer_b_DF17` | Target percentage; binary integer 0–100. |
| `DF18` | 1 | `cOnlinePinCap_b_DF18` | Parsed, then unconditionally forced to `01` by `MfSdkEmvSetAid`. |
| `DF19` | 6 | `sRf_OfflineLimit_DF19` | Contactless offline limit, 12-digit packed BCD in minor units. |
| `DF20` | 6 | `sRF_TxnLimit_DF20` | Contactless transaction limit, 12-digit packed BCD in minor units. |
| `DF21` | 6 | `sRf_CVMLimit_DF21` | Contactless CVM limit, 12-digit packed BCD in minor units. |
| `9F1B` | 4 | `szFloorLimit_b_9F1B` | Terminal floor limit, binary amount. |
| `5F2A` | 2 | `szCurCode_aid_5F2A` | ISO 4217 numeric transaction currency code in packed BCD. |
| `5F36` | 1 | `cCurExp_aid_5F36` | Transaction currency exponent. |
| `9F3C` | 2 | `szRefCurrCode_aid_9F3C` | Reference currency code. |
| `9F3D` | 1 | `cRefCurrExp_aid_9F3D` | Reference currency exponent. |
| `9F1D` | 0–8 | `cRiskManage_aid_9F1D` | Terminal risk-management data. |
| `9F33` | 3 | `cTerminalCap_9F33` | Terminal capabilities. |
| `9F66` | 4 | `cTTQ_9F66` | TTQ. Obtain the value from the acquirer/scheme profile. |
| `9F15` | 2 | `szMerCateCode_9F15` | Merchant category code in packed BCD. |
| `9F7B` | 6 | `sEcLimit_9F7B` | Electronic-cash terminal transaction limit, packed BCD. |
| `DF810C` | 1 | `cKernelID` | `02` Mastercard, `03` Visa, `04` Amex, `05` JCB, `06` Discover, `07` UnionPay, `09` Pure. |
| `DF8A01` | 0–255 | other-TLV record | Complete nested other-parameter TLV stream. |
| `DF8406` | 0–250 | contact other params | Alternative top-level contact wrapper; used only when `DF8A01` is absent. |
| `DF8407` | 0–250 | contactless other params | Alternative top-level contactless wrapper; used only when `DF8A01` is absent. |

Notably, tag `87` (priority) and `cAidFileType` exist in other SDK structures but are not mapped by `MfSdkEmvSetAid`; supplying them at the top level has no effect through this API.

## Other-parameter containers

Choose one representation:

- Put the already-encoded complete other-parameter stream inside `DF8A01`; or
- Put contact parameters inside `DF8406` and contactless parameters inside `DF8407`. The SDK re-encodes these wrappers into its stored other-parameter record.

If `DF8A01` exists, the SDK does not process `DF8406` or `DF8407`. Nested values must themselves be valid BER-TLV. The stored other-parameter stream has a one-byte length field, so keep its encoded size at or below 255 bytes.

Example with one Amex contactless parameter:

```text
DF8407099F6D01C09F6E02D8E0
```

This is only an encoding example. Scheme values must come from the applicable certified profile.

## Important implementation behavior

1. `MfSdkEmvSetAid` zero-initializes `ST_TERMAID`, scans only its hard-coded tag map, and then calls `Emv_AddAID(..., YES)`. Missing tags therefore remain zero; an unknown top-level tag is ignored.
2. Oversized mapped values are copied only up to the destination field size without returning an error. Validate before calling the SDK.
3. `DF18` is overwritten with `YES` after TLV parsing, regardless of the supplied value.
4. `DF8A01` is checked first. `DF8406` and `DF8407` are considered only when `DF8A01` has no value.
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
3. Change only the requested tags and validate the full result.
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
