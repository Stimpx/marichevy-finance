# Server revision contract (review and staging only)

The exact CAS SQL has now been applied and exercised in the separate FREE
Supabase project `marichevy-finance-staging` (`iqpoxphtvtogjowruufe`) with two
fictional households and three real test Auth accounts. Direct Auth/PostgREST/RLS,
concurrent CAS, receipts, legacy-write rejection, synthetic restore and protocol
rollback passed. The current client also passed real-server browser flows,
including same-record/edit-delete conflicts and offline reload. See
[RELEASE_CANDIDATE.md](RELEASE_CANDIDATE.md) for exact hashes and evidence.

**Production has not been changed or validated.** Its actual schema, grants,
policies, triggers and membership model still require read-only inspection.
The staging fixture membership policy is not a production migration.
Live browser flows forward verified HTTPS through a test route bridge; actual
Safari/Yandex and native browser proxy/CA remain separate acceptance.

`server/001_family_state_cas.sql` accepts only the inferred ordinary RLS-enabled
`public.family_state` table with exactly `household_id uuid` as its sole primary
key, `data jsonb`, `updated_at timestamptz`, and `updated_by uuid`. It rejects
unexpected columns, types, existing user triggers, missing auth prerequisites, or
a second application. Review/adapt a separate migration if preflight fails; do
not remove the guard to force it through. Existing RLS policies, table grants and
JSON data are preserved. It adds:

| Column | Initial value | Purpose |
| --- | --- | --- |
| `sync_revision bigint NOT NULL` | `0` | Server counter; every UPDATE increments it |
| `sync_protocol smallint NOT NULL` | `1` | `1` is unprotected legacy mode; `2` requires CAS |
| `last_request_id uuid` | `NULL` | Acknowledges a retry of the latest accepted request |

The trigger sets authenticated writes' `updated_by` from `auth.uid()` and
`updated_at` from the server clock. Callers cannot choose a revision. Maintenance
under the actual `postgres` or `supabase_admin` role can activate/disable protection;
maintenance updates also increment the revision and clear the request receipt.
Administrator access remains trusted and must not be used by application clients.

## HTTP/RPC contract

Read the authorized household using the existing table endpoint, selecting
`data,sync_revision,sync_protocol,last_request_id,updated_at`. Missing metadata or
protocol `1` means safe cloud writes are unavailable; preserve pending local work.
The new client must send writes only to:

```text
POST /rest/v1/rpc/family_state_cas
{
  "p_household_id": "<uuid>",
  "p_expected_revision": 12,
  "p_data": {"...complete merged household state...": "..."},
  "p_request_id": "<fresh uuid for this exact attempt>"
}
```

The JSON response always has `status`, `revision`, `protocol`, `data`, and
`request_id`. `written` returns the stored snapshot and resulting revision;
`conflict` returns the current snapshot/revision so the client can merge its
pending edits and retry with a new request ID. `upgrade_required` means the row
is still protocol `1`. `not_found` has null metadata/data and covers missing or
RLS-invisible rows; this RPC does not create households. Invalid arguments or
missing authentication raise an error. RLS or privilege errors are not success.

A row lock and revision condition serialize overlapping writers. A retry with
the latest `last_request_id` and identical JSONB returns the same acknowledgment
without advancing the revision; reusing that ID with different data conflicts.
JSON key order does not matter. Only the latest receipt is retained: after an
intervening accepted write, an old request must conflict/reconcile rather than
assume its earlier acknowledgment is still current. The client must verify the
acknowledged request ID, data and revision before clearing local pending work.
The server stores the entire JSON object without collection filtering, so known
collections, tombstones, nested unknown fields and future collections survive.

The function is `SECURITY INVOKER`, uses a fixed search path and requires existing
SELECT/UPDATE grants and RLS authorization. EXECUTE is revoked from PUBLIC/anon
and granted to authenticated. The trigger uses a transaction-local
`marichevy_sync.cas` marker only around the guarded UPDATE and restores it before
returning (also on exceptions). Protocol `2` blocks ordinary legacy UPDATE,
upsert, DELETE, protocol downgrade and household-key replacement with SQLSTATE
`PT409`, message `upgrade_required`; PostgREST should expose HTTP 409. Protocol
`1` keeps legacy table writes available, with **no lost-update guarantee**.

Custom PostgreSQL GUCs are not secret capabilities. This design assumes the
normal Supabase/PostgREST interface, which does not expose arbitrary SQL or
`set_config` to authenticated clients. Do not expose a helper RPC that permits
setting this marker, arbitrary SQL, disabling triggers, or bypassing this guard.
Review existing SECURITY DEFINER functions and every other write path in staging.
The guarantee covers ordinary application/legacy API writers under this boundary;
an administrator or a role with arbitrary SQL execution can bypass it. Existing
RLS must separately enforce household access, including SELECT, INSERT, UPDATE
WITH CHECK and DELETE. The fixture membership policy in the tests is illustrative,
not a replacement for real policies.

## Controlled rollout and rollback

Unsafe old writers and a lost-update guarantee cannot both remain enabled on the
same row: an old client can overwrite a new client's accepted snapshot unless the
server rejects that old write. Keeping a legacy fallback would invalidate CAS.

1. Inventory the actual schema, triggers, privileges, RLS policies and definer
   functions; verify authorization with two real staging households and anon.
   Confirm the RPC and PostgREST status mapping in staging without real data.
2. Make and verify a recoverable server backup and local export. Record each
   household's current JSON, protocol and revision. Freeze/drain old clients and
   resolve pending local work so rollout does not strand unsent edits.
3. Review/apply the migration in staging first. It leaves protocol `1` and data
   unchanged. Deploy the CAS-aware client with safe cloud writes gated off until
   metadata and protocol `2` are available. No production configuration is changed
   by this repository or its local tests.
4. A separately authorized operator can use `server/activate_household.sql` with
   explicit database, household UUID, expected revision and confirmation. Its
   transaction updates exactly one matching protocol-1 row, changes no JSON data,
   and advances its revision. Wrong database/revision/role/confirmation aborts.
   After activation, old clients can still read if authorized but their writes
   fail visibly. The new client must keep pending changes when writes fail.
5. Verify two overlapping staging writers, conflict merge/retry, idempotent
   retry, old-client rejection, authorization failures and all collections before
   considering a separately approved production rollout.

For rollback, first stop/drain clients and disable safe cloud writes; retain a
fresh backup. `server/rollback_household.sql` requires the current revision,
`expected_activation_revision` from the separately saved activation receipt, and
`DISABLE_SYNC_REVIEWED_HOUSEHOLD`. The two revisions must match each other and the
row: any application write after activation blocks rollback. Before those writes
it changes protocol `2` to `1` without restoring old JSON, increments the revision
and clears the receipt. After v95 writes, retain protocol2 and pause writers
until a compatible client is repaired; original v94 normalization drops v95
favorites/unknown fields and must not resume saving that document. The new client then stays
disabled (`upgrade_required`). Re-enabling legacy clients deliberately removes
the lost-update guarantee. Do not drop the guard or restore stale snapshots as an
automatic rollback; reconcile retained local pending work separately.

## Local verification

The runner uses only Python's standard library plus Docker. It uses the explicit
managed local Docker socket, preserves proxy/registry/TLS configuration and uses
a pinned official PostgreSQL image. Pull it once with normal TLS verification:

```sh
env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_TLS -u DOCKER_TLS_VERIFY -u DOCKER_CERT_PATH \
  docker --host=unix:///var/run/docker.sock pull \
  postgres:16-alpine@sha256:f4610795587492cd4fb887c2dc3de301b813278bb6f616992061141b5f15ac36
python tests/test_sync_database.py -v
```

The runner does not pull automatically. It creates a random ephemeral container
with `--network=none`, publishes no ports, keeps fictional data on tmpfs, uses
local container Unix-socket authentication only, and removes the container on
completion. It never reads app credentials, connects to Supabase, runs the app,
or modifies production. Tests cover actual PostgreSQL locking/triggers/RLS with
mock `auth.uid()` and two fictional household memberships. They do not prove
that unknown hosted RLS or PostgREST configuration is correct.

Local result (2026-10-22): `python tests/test_sync_database.py -v` completed
15 tests in 9.691 seconds, exit status 0, no skips. The image manifest digest was
`sha256:f4610795587492cd4fb887c2dc3de301b813278bb6f616992061141b5f15ac36`;
the local image ID was
`sha256:6a2e324ebe59af6031c4c1cd96c1d5072c2ebc36563d2196365e43b8297c062d`.
The test container was removed after completion.
