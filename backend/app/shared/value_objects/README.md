# shared/value_objects

Framework-agnostic value objects and reference data shared across modules. This
package is **pure** (standard library only; it imports nothing else from `app`,
per the `shared-is-pure` import contract) and is the **single source of truth for
monetary precision** in the platform.

Public surface is `__init__.py`.

---

## Currency Registry

`currency.py` defines a version-controlled registry of the assets the platform can
hold, move, and settle. It is the only place precision is defined.

- `CURRENCY_REGISTRY` — the process-wide singleton (immutable).
- `REGISTRY_VERSION` — semantic version of the seeded data (currently `1.1.0`).
- `CurrencyRegistry` — an immutable, version-tagged collection keyed by `asset_code`
  (`get` / `require` / `has` / `codes` / `all`, plus `in`, iteration, `len`).
- `CurrencyAsset` — one immutable entry (a frozen dataclass).
- `AssetType` — `FIAT` / `CRYPTO` / `STABLECOIN`.
- `CurrencyNotRegisteredError` — raised by `require()` for an unknown asset.

### Supported assets (v1.1.0)

| asset_code | asset_type | precision | minor_unit_name |
|------------|------------|-----------|-----------------|
| USD        | FIAT       | 2         | cent            |
| INR        | FIAT       | 2         | paisa           |
| USDC       | STABLECOIN | 6         | micro-USDC      |

Other assets are **supported by the model** and can be added as data without any
schema change (see below).

### Registry format

Each entry carries exactly four fields:

```python
CurrencyAsset(
    asset_code="USD",        # uppercase symbol; NOT length-limited (fits "USDC")
    asset_type=AssetType.FIAT,
    precision=2,             # number of decimal places (minor-unit scale); 0 is valid (JPY)
    minor_unit_name="cent",  # display/documentation only; never used for arithmetic
)
```

The registry is **asset-agnostic**: the record shape is the same for a fiat
currency, a stablecoin, or any future digital asset. Precision is a per-asset
integer, so USD (2), a 0-dp currency, and a 6-dp stablecoin all flow through
identical code. Adding an asset is a new *row*, never a schema change.

---

## Conversion helpers

`conversion.py` — the only place amounts are converted or validated. All functions
accept an optional `registry=` argument (defaulting to `CURRENCY_REGISTRY`) so a
different revision can be injected without code changes.

| Function | Purpose |
|----------|---------|
| `get_currency(code)` | Resolve an `asset_code` to its `CurrencyAsset`; rejects unsupported currencies. |
| `validate_precision(amount, code)` | Return the amount as `Decimal`; **reject** more decimal places than the asset allows (`ExcessPrecisionError`). No rounding. |
| `to_minor_units(amount, code)` | Exact `Decimal → int` minor units (e.g. USD `10250.75 → 1025075`). Rejects excess precision. |
| `to_decimal(minor_units, code)` | Exact `int → Decimal` at the asset's precision (e.g. USD `1025075 → 10250.75`). |
| `round_to_minor_units(amount, code)` | `Decimal → int` **with** banker's rounding — the one function that rounds. |
| `round_to_asset_precision(amount, code)` | `round_to_minor_units` expressed back as a `Decimal`. |

Errors: `ExcessPrecisionError` (too many decimals), `InvalidAmountError`
(float/NaN/junk — floats are rejected because they can't represent money exactly),
`CurrencyNotRegisteredError` (unknown asset).

`CurrencyNotRegisteredError` maps to **`422 UNSUPPORTED_CURRENCY`** on every route,
via `currency_not_registered_handler` registered in `main.py`. Services may catch it
first for a friendlier message (ledger and FX do) but must use the same error code.

---

## On-chain translation layer

`translation.py` + `adapters/` — the **single, only** place external on-chain amount
formats (Circle payloads / raw chain values) are turned into internal integer minor
units. It is asset-agnostic: it contains no USDC, Circle, or blockchain business
logic — precision always comes from the registry.

Flow: `asset_code → registered adapter → canonical Decimal → to_minor_units → int`.
Fiat has no adapter and goes straight to the conversion layer.

| Piece | Role |
|-------|------|
| `TranslationAdapter` | Interface for one asset's external format ↔ canonical Decimal. Handed the registry entry, so scale is never hardcoded. |
| `TranslationRegistry` | `asset_code → adapter` map; `load(config)` registers declaratively. |
| `TranslationDispatcher` | Looks up the adapter by `asset_code` and bridges to the conversion layer. Has no per-asset branches. |
| `translate_to_internal` / `translate_from_internal` | Front doors over the process-wide dispatcher. |
| `adapters/config.py` (`ADAPTER_CONFIG`) | Declarative `asset_code → adapter` — the one place adapters are enabled. |
| `adapters/usdc.py` (`UsdcTranslationAdapter`) | Parses Circle/on-chain USDC formats (decimal, base units, `{"amount", "currency"}`). |

Callers translate on-chain amounts **only** via `translate_to_internal` (see
`settlement`); no module parses an on-chain format itself.

---

## Adding a new currency

1. Add one `CurrencyAsset(...)` row to `_SEED` in `currency.py` (e.g.
   `CurrencyAsset("USDC", AssetType.STABLECOIN, 6, "micro-USDC")`).
2. Bump `REGISTRY_VERSION` and add a CHANGELOG line in the module docstring.

No application code changes — services read precision from the registry at runtime.

Storage notes: currency/`asset_code` columns were widened to `VARCHAR(8)` in migration
`b1c2d3e4f5a6`, and the ledger's own columns to `VARCHAR(16)` when it was rebuilt in
`c1a2b3c4d5e1`, leaving headroom for longer token symbols. Money columns are `BIGINT`
integer minor units (Rule 1) — **not** `NUMERIC` — so precision is a property of the
asset in the registry, not of the column. A new asset at any precision needs no schema
change; a 6-dp asset simply stores a larger integer than a 2-dp one.

## Adding a new on-chain asset (USDT, DAI, BTC, a CBDC, …)

1. Add its `CurrencyAsset(...)` row to `_SEED` (asset_code, type, precision, minor
   unit) and bump `REGISTRY_VERSION` — as for any currency above.
2. Write a `TranslationAdapter` for its external format under `adapters/` (or reuse
   an existing one if the format matches).
3. Add one line to `ADAPTER_CONFIG` mapping its `asset_code` → that adapter.
4. Ledger accounts use an existing role type (`clearing`, `treasury`, …) plus the new
   `asset_code`; no new `AccountType` member and no schema migration.

The dispatcher, conversion layer, and posting/aggregation code are **not** touched —
they name no asset. A cross-asset transaction posts as one `ledger_transaction` that
balances within each asset independently (see `ledger`).

---

## Banker's rounding

Rounding is **ROUND_HALF_EVEN** (banker's rounding), declared once as
`conversion.ROUNDING` and applied at exactly one place — the decimal→integer
(minor-unit) conversion in `round_to_minor_units`. Everywhere else is exact
(validate/reject or lossless expansion).

Why: half-even removes the systematic upward bias of half-up rounding, so rounding
error nets to ~zero across many postings, and it matches the decimal/accounting
default — minimising one-minor-unit reconciliation breaks. Ties resolve to the even
neighbour:

| amount | → integer (half-even) |
|--------|-----------------------|
| 1.5    | 2 |
| 2.5    | 2 |
| 3.5    | 4 |
| 4.5    | 4 |

---

## Minor-unit philosophy

Money is stored and reasoned about as **integer minor units** wherever equality or
comparison matters. Amounts enter as decimal strings, are converted to minor units
via the registry, and internal logic (especially reconciliation's MATCH/BREAK
decisions) compares exact integers — never floats, never quantized Decimals. Values
are converted back to `Decimal`/string only at display/serialization boundaries.
This makes precision explicit, comparisons exact, and rounding auditable (it can
only happen at the single documented conversion point).
