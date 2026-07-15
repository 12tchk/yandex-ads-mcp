# DirectOps integration

## Role

This MCP server is an external operator interface for Codex. It does not replace
the canonical DirectOps connector plane, scheduled workers, normalized datasets,
or cached analytics.

```text
Yandex Direct API
       |                    scheduled collection
       +----> Direct connector/workers ----> PostgreSQL/ClickHouse/Redis
       |                                      |
       |                                      +----> DirectOps dashboards
       |                                      +----> signals/recommendations
       |
       +----> read-only MCP <---- Codex (interactive investigation)
```

The existing connector plane remains responsible for:

- credential storage and project-to-account mappings;
- incremental entity sync and stable daily statistics;
- caching, freshness metadata, retry, rate limiting, and reconciliation;
- normalized Direct, Metrika, VK, CRM, and Wordstat datasets;
- deterministic signals, recommendations, and effect measurement.

The MCP adds:

- a broad typed Direct API surface for on-demand investigation;
- a Codex-compatible STDIO tool interface;
- account and tool isolation independent of model instructions;
- a migration path from read-only analysis to controlled ChangeSets.

## Production pilot

The first deployment exposes only selected Direct read tools. Metrika and
Wordstat stay disabled in this MCP because DirectOps already collects those
datasets through shared connectors. This prevents duplicate polling and avoids
giving the external agent a second path to the same client data.

Every Direct call must include an exact allowlisted `client_login`. The agency
account discovery tool is intentionally not exposed, so Codex cannot enumerate
all customers attached to the OAuth token.

## Future write path

Do not let the MCP call mutating Yandex methods directly in production. Add a
DirectOps-owned control plane first:

```text
Codex
  -> create_changeset
  -> policy validation
  -> human approval
  -> DirectOps executor
  -> before/after snapshot and Yandex RequestId
  -> immediate connector sync
  -> effect evaluation and rollback
```

Required controls before write rollout:

1. Organization, project, account, and campaign scope on every ChangeSet.
2. Immutable preview with `before`, `after`, reason, evidence, and expiry.
3. Idempotency key and optimistic current-value check.
4. Policy limits for budgets, strategies, goals, geo, and bulk operations.
5. Per-item handling of partial Direct API success.
6. Audit ledger, immediate post-write sync, and rollback where supported.

Until that control plane exists, keep `YD_READONLY=true` and
`YD_WRITE_ARMED=false`.
