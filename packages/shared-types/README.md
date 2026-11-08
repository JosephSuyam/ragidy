# shared-types

TypeScript types that mirror the API's Pydantic schemas (`apps/api/app/schemas`), for `apps/web` ([ADR 0010](../../docs/decisions/0010-web-client.md)).

| File | What it is |
|---|---|
| `openapi.json` | Generated. A dump of FastAPI `app.openapi()`, written by `infrastructure/scripts/dump_openapi.py`. |
| `api.d.ts` | Generated. `paths`, `components` and `operations` types, written by `openapi-typescript` from `openapi.json`. |
| `index.ts` | Hand-written. Named aliases for the schemas, plus what OpenAPI cannot express: `ApiErrorBody`, `ValidationErrorBody` and `ChatStreamEvent` (the SSE events of `POST /chats/{id}/messages`). Type-only: `import type` and `export type` only. |
| `package.json`, `package-lock.json` | The generator: `openapi-typescript` and `typescript@5`, exact-pinned. |

Never edit `openapi.json` or `api.d.ts` by hand. Import from `index.ts`.

## Regenerate

After any change to an API schema or route, run `make types`. Without `make`:

```bash
cd apps/api && uv run python ../../infrastructure/scripts/dump_openapi.py
cd packages/shared-types && npm ci && npm run gen
```

Commit both generated files. CI and the Docker build use the committed files and never run the generator.

## Why a nested package

`openapi-typescript` needs `typescript@5` (peer `^5.x`), because it uses the TypeScript JS compiler API. `apps/web` uses TypeScript 7, the Go port, which has no JS API, so the generator cannot be an `apps/web` devDependency. This package pins its own `typescript@5` and has its own lockfile, so nothing it installs reaches `apps/web`.
