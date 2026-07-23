---
name: pos-aid-tlv
description: Inspect, explain, validate, build, and modify BER-TLV AID parameters for the SR600 POS SDK and its MfSdkEmvSetAid API. Use when a user mentions AID configuration, EMV application parameters, TLV hex, TAC, TTQ, contact/contactless limits, kernel ID, adding or updating an AID, or asks for C code that calls MfSdkEmvSetAid.
---

# POS AID TLV

Use the SDK implementation—not generic EMV assumptions—as the source of truth.

## Required workflow

1. Read `references/sdk-aid-reference.md` before changing or generating AID data.
2. Find the complete original TLV for the target AID. Do not treat a partial update as safe: `MfSdkEmvSetAid` starts from a zeroed structure, so omitted fields become zero.
3. Never invent the AID, TAC values, TTQ, currency, limits, application version, or kernel ID. Ask for missing business/acquirer/card-scheme values.
4. Use an available Python 3.8+ interpreter (`python3`, `py -3`, or the Agent's configured runtime). Inspect and validate the original data:

   ```bash
   python3 scripts/aid_tlv.py inspect "<TLV_HEX>"
   python3 scripts/aid_tlv.py validate "<TLV_HEX>" --strict
   ```

5. Apply only the requested tag changes. Run one `set` per change, feeding each result into the next command:

   ```bash
   python3 scripts/aid_tlv.py set "<TLV_HEX>" DF20 000000100000
   python3 scripts/aid_tlv.py remove "<TLV_HEX>" 9F7B
   ```

6. Validate the final TLV with `--strict`. Resolve every error; explain any warning that must remain.
7. If C code is requested, generate a byte array and call `MfSdkEmvSetAid` with the byte count:

   ```bash
   python3 scripts/aid_tlv.py format-c "<TLV_HEX>" --name aid_tlv
   ```

8. Report the target AID, before/after values, final TLV, byte length, validation result, and any SDK-specific caveat.

## Tool input

`scripts/aid_tlv.py` accepts contiguous hex, spaced hex, `0xNN` arrays, C `\xNN` strings, `@path` to read a file, or `-` to read stdin. It has these commands:

- `inspect`: decode tags, lengths, values, and known nested other-parameter TLVs.
- `validate`: check BER-TLV structure, SDK-supported tags, field lengths, duplicates, required `9F06`, common value constraints, and SDK traps.
- `set`: replace a tag in place or append it if absent.
- `remove`: remove one tag.
- `build`: assemble a TLV from ordered `TAG=VALUE` pairs.
- `format-c`: generate a C byte array and `MfSdkEmvSetAid` call.

## Safety rules

- Prefer `9F09` over its accepted alias `9F08`; never include both.
- Treat unknown top-level tags as ignored by `MfSdkEmvSetAid`, even if they are valid EMV tags.
- Treat `DF8A01` as taking precedence over top-level `DF8406` and `DF8407`.
- Do not promise that `DF18` changes online PIN capability: this SDK forces it to `01` inside `MfSdkEmvSetAid`.
- Do not use `MfSdkEmvGetAid` as a lossless backup of other parameters; it does not return the stored `DF8A01`/`DF8406`/`DF8407` content.
- Preserve the original tag order unless there is a concrete reason to change it.
- When editing repository code, locate the actual configuration call site before changing files and keep unrelated AIDs untouched.
