# Contributing

Thanks for your interest. The fastest contribution path is adding to the
broker list.

## Adding or updating a broker

The broker list lives in `brokers/brokers.json`. Any change bumps the
top-level `version` number — the broker list is treated as a series of
immutable snapshots, not a mutable list.

To add a broker:

1. Increment the `version` field
2. Add an entry under `brokers`:
   ```json
   {
     "key": "examplebroker",
     "name": "Example Broker",
     "search_url": "https://example.com/search"
   }
   ```
3. The `key` is a stable lowercase slug (`[a-z0-9_-]+`). Once chosen, do
   not change it — it's what scan results reference internally.
4. Submit a PR.

## What we will and will not accept

The broker list is for US data brokers as defined under CCPA / state data
broker registration laws. We will not accept entries that:

- Are not actually data brokers (search engines, social networks,
  general directories)
- Have closed or merged into other brokers
- Require us to scrape behind authentication walls
- Are obviously low-quality or unverifiable

## Code changes

Standard PR flow. Please run:

```bash
make lint
make typecheck
make test
```

before submitting.

### Canonicalization

The PII canonicalization rules in `src/core/crypto.py` are deliberately
documented and conservative. Changing them may affect how identity
fields are matched during scans. Don't touch unless you have a
strong reason.

### Logging

Never log raw identity field values. The `PIIScrubFilter` is a
defense-in-depth layer, not a primary control. Use `field_type` and
broker keys in log messages, never `value`.

### Test coverage

New broker adapters require:

- Unit tests for the parser logic
- A test that a `BrokerError` is raised on simulated failures (so we
  don't store invalid results)
