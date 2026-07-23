# RTOS/Linux device SDK CAPK TLV reference

## Contents

- Public API and source of truth
- Supported CAPK tags
- Identity, checksum, and encoding rules
- Safe add/modify procedure
- C examples

## Public API and source of truth

The customer-facing CAPK APIs are declared in `inc/mfsdk_emv.h`:

```c
s32 MfSdkEmvSetCapk(u8 *CapkBuff, s32 BuffLen);
s32 MfSdkEmvDeleteOneCapk(u8 *RID, u8 PKIndex);
s32 MfSdkEmvDeleteAllCapk(void);
s32 MfSdkEmvGetCapkNum(void);
s32 MfSdkEmvGetCapkByIndex(MfSdkEmvCapkInfo_T *stCapk, s32 nRecNum);
```

Use `g_tagMapMemInfoCapk` and `MfSdkEmvSetCapk` in `src/mfsdk_emv.c` as the source of truth. `MfSdkEmvSetCapk` zero-initializes `ST_CAPK`, unpacks only mapped tags, normalizes the one-byte exponent `03`, and submits the full structure through `Emv_AddCAPK(..., YES)`.

## Supported CAPK tags

| Tag | Length | SDK field | Meaning / validation |
|---|---:|---|---|
| `9F06` | 5 | `szRID_b_9F06` | Registered Application Provider Identifier (RID). Required. |
| `9F22` | 1 | `cCAPKIndex_b_9F22` | CA public-key index. Required. |
| `DF05` | 4 | `szCAPKExpire_n_DF05` | Expiration date as packed-BCD `YYYYMMDD`. Required. Preserve a supplied profile value; default to `20301231` only when the source provides no expiration date. |
| `DF06` | 1 | `cCAPKHashFlag_b_DF06` | Hash algorithm indicator. `01` is SHA-1 in conventional EMV profiles. |
| `DF07` | 1 | `cCAPKFlag_b_DF07` | Public-key algorithm indicator. `01` is RSA in conventional EMV profiles. |
| `DF02` | 1–248 | `szCAPKMod_b_DF02` | RSA modulus. Long values use BER long-form length, for example `81F8` for 248 bytes. |
| `DF04` | 1 or 3 | `szCAPKExponent_b_DF04` | Public exponent. Common certified encodings are `03`, `000003`, and `010001`. |
| `DF03` | 20 | `szCAPKCheckSum_b_DF03` | SHA-1 CAPK checksum for `DF06=01`. |

All eight tags are required by this skill for add and update operations. Unknown top-level tags are not mapped by `MfSdkEmvSetCapk` and are ignored. The generic SDK unpacker silently truncates oversized mapped values to the destination field size, so validate before calling the API.

When an authoritative source omits the expiration date, add `DF05=20301231` and report that this is the skill default rather than a certified source value. Never replace a supplied `DF05` with the default unless the user explicitly requests that change. `capk_tlv.py build` applies this default automatically when the `DF05` pair is omitted.

## Identity, checksum, and encoding rules

The CAPK identity is:

```text
9F06 RID (exactly 5 bytes) + 9F22 public-key index (exactly 1 byte)
```

Using the same RID and index targets the same CAPK record. Changing either identifies a different CAPK; do not assume that adding the new identity removes the old one.

For conventional SHA-1 CAPKs (`DF06=01`), verify:

```text
DF03 = SHA-1(9F06 value || 9F22 value || DF02 value || normalized DF04 value)
```

Normalize `DF04` for checksum input by removing leading `00` bytes. The certified samples confirm that `03` and `000003` both use `03` in the checksum input. Run:

```bash
python3 scripts/capk_tlv.py checksum "<CAPK_TLV_HEX>"
python3 scripts/capk_tlv.py refresh-checksum "<CAPK_TLV_HEX>"
```

Do not recompute a failed checksum merely to force acceptance of an untrusted key. First compare RID, index, modulus, exponent, and checksum with the authoritative card-scheme/acquirer profile.

`MfSdkEmvSetCapk` has a special case for `DF04=03`: it stores the exponent buffer as `000003` while retaining a logical length of one byte. Preserve the certified TLV representation, but normalize leading zero bytes when calculating `DF03`.

## Safe add/modify procedure

For a new CAPK:

1. Obtain the complete record from an authoritative card-scheme/acquirer CAPK list.
2. Confirm all eight mapped tags are present. If the source omits the expiration date, add the skill default `DF05=20301231` and disclose that default.
3. Validate structure, field lengths, date, algorithms, and checksum with `capk_tlv.py validate --strict`.
4. Call `MfSdkEmvSetCapk` once and require return value `0`.
5. Do not clear all CAPKs before adding one record.

For an existing CAPK:

1. Start from the complete original TLV or reconstruct all fields from `MfSdkEmvGetCapkByIndex`.
2. Match the exact five-byte RID and one-byte index.
3. Change only requested fields. Keep the complete record because `MfSdkEmvSetCapk` starts from a zeroed structure.
4. Refresh `DF03` only when RID, index, modulus, or exponent changes.
5. Validate the complete final TLV and submit it with `MfSdkEmvSetCapk`.
6. Do not call `MfSdkEmvDeleteOneCapk` unless removal is explicitly requested.

## C examples

Add or replace one complete CAPK:

```c
static unsigned char capk_tlv[] = {
    /* complete validated CAPK TLV bytes */
};

s32 ret = MfSdkEmvSetCapk(capk_tlv, (s32)sizeof(capk_tlv));
if (ret != 0) {
    /* reject provisioning and report the SDK error */
}
```

Delete only the explicitly selected RID/index:

```c
static unsigned char rid[5] = { /* exact RID bytes */ };
s32 ret = MfSdkEmvDeleteOneCapk(rid, capk_index);
```

Never use `MfSdkEmvDeleteAllCapk` as part of a single-record add or update.
