# integrations

Vendor clients, mappers, and adapters implementing **module-owned** ports.

## Rules (ARCHITECTURE.md §8)

- Integrations contain **implementations only**. The port is defined by the consuming module
  in `app/modules/<domain>/domain/ports.py`. An integration never defines a port.
- Integrations **never** import a module's internals.
- Retries and circuit-breaking come from `platform/resilience/`. Never re-implement them here.
- Webhook signature verification uses `platform/security/`. Never roll bespoke crypto.
- Message content and templates belong to `modules/notifications/`. Integrations only transmit.

## Deviation from ARCHITECTURE.md

§4 and §8 spell four capability folders with hyphens (`payment-networks`, `exchange-rates`,
`identity-providers`, `object-storage`). Python cannot import a hyphenated package, and
`modules/` must import `integrations/`. They use underscores here.
