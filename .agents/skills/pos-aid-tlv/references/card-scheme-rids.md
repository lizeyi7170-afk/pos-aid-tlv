# Card-scheme RID reference

Use this table when CAPK source material names the card scheme but omits the five-byte RID used by `9F06`.

Sources: [Worldpay EMV Network Keys: Test](https://docs.worldpay.com/assets/pdf/EMVNetworkKeys_Test4.pdf) and [Worldpay EMV Network Keys: Production](https://docs.worldpay.com/assets/pdf/EMVNetworkKeys_Production3.pdf), reviewed 2026-07-23. Use the RID mappings for identification, but continue to take the modulus, index, exponent, checksum, and supplied expiration date from the applicable certified test or production profile.

| Card scheme / accepted names | `9F06` RID |
|---|---|
| Visa, VSDC | `A000000003` |
| Mastercard, MasterCard, PayPass | `A000000004` |
| American Express, AMEX | `A000000025` |
| Discover, DPAS | `A000000152` |
| JCB | `A000000065` |
| China UnionPay, UnionPay, CUP, UPI, 银联 | `A000000333` |
| WEX | `A000000768` |
| Interac | `A000000277` |

## RID resolution rules

1. Preserve an explicit RID from authoritative source material.
2. If the RID is omitted and exactly one card scheme in the table matches, use that RID as `9F06`.
3. Verify the completed identity with `DF03 = SHA-1(RID || index || modulus || normalized exponent)` when `DF06=01`.
4. Treat a checksum mismatch as conflicting source data. Recheck the scheme, index, modulus, exponent, and checksum; do not cycle through possible RIDs to force a match.
5. Ask for authoritative clarification when the scheme is absent, unknown, or ambiguous.
