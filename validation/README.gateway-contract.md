# Isolated gateway regression checks

Requirements: Node.js 24 or later and the gateway dependencies from its package-lock.json. Install dependencies with `npm ci` inside `services/ai-tutor` first. No real OpenAI key, PostgreSQL, Redis, production database or operational environment file is required.

From the repository root:

```sh
node validation/gateway_contract.cjs
```

Optional paths and ports:

```sh
node validation/gateway_contract.cjs --source services/ai-tutor --out ./validation-output --gateway-port 3401 --provider-port 9401
```

The runner uses the selected ports and the next adjacent port for each service. `--node-modules /path/to/installed/node_modules` can reuse an existing matching dependency installation. Do not commit validation-output or generated databases/logs.

The runner creates a new isolated source copy and disposable SQLite, with a deterministic provider on loopback. It copies only source/configuration files from an explicit allowlist. It never copies `.env`, `.env.local`, production data or provider credentials. The child gateway receives a synthetic key and a loopback provider URL. Source hashes are checked after the run.

The first suite covers concurrent sessions, persisted history separation, cross-owner chat writes, indexed retrieval, retrieval/provider failures, provider HTTP 408, stalled sockets, overall deadline, incomplete streams, cancellation of ordinary and silent streams, terminal-event finalization and recovery. It has 29 applicable criteria. The missing history HTTP endpoint is recorded as one not-applicable observation. Main does not export history/telemetry HTTP endpoints; persisted state is inspected read-only through SQLite, with that observation method recorded explicitly. No HTTP authorization success is inferred from missing endpoints.

The second suite has 21 criteria: human-readable validation errors; exact Russian, Kazakh and English refusal instructions; empty sources/citations for canonical refusal fixtures; strict lecture-only instructions; preservation of model and `store=false`; seven owner/course/version conditions; independent provider timeouts; failed, incomplete and malformed provider SSE. The SQLite owner/course/version query is exercised through actual chat HTTP. The corresponding PostgreSQL predicate is not exercised by this SQLite suite.

The expected corrected gateway result is 50 passed applicable criteria and one not-applicable HTTP observation. The runner exits nonzero on failures or source-hash drift. `gateway-contract-summary.json` points to raw reports, synthetic provider fixtures and server logs. These checks verify application behavior under controlled faults. They do not measure live-provider answer accuracy, production load, provider account settings or deployed-system deletion.

The production route supports `AI_CHAT_TIMEOUT_MS` (default 120000) as an overall retrieval/generation budget in addition to `AI_PROVIDER_TIMEOUT_MS` (default 60000) and `AI_PROVIDER_MAX_RETRIES` (default 2). After SSE headers are sent, errors use an error event. Client cancellation finalizes the event as 499; the overall chat deadline uses 504. Independent provider failures retain retrieval HTTP 502 or generation terminal status 500. Responses requests explicitly use `store=false`.
