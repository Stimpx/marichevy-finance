# Account gateway runtime

`server/account_gateway.py` is the new public account entry point. It uses Python
3.11+ standard libraries and serves only files in `public/`. The existing root
`index.html`, old household tables, production configuration, and private backup
directories are outside this server's routes. No additional Python package is
required.

Run `python3 server/account_gateway.py --host 127.0.0.1 --port 8787` behind an HTTPS
reverse proxy. The proxy must preserve the public `Host`, `Origin`, and
`Authorization` headers, restrict direct backend access, and avoid logging query
strings, bodies, authorization headers, or email addresses. The application does
not log requests or provider diagnostics. TLS verification and inherited proxy/CA
settings remain enabled for outbound HTTP and SMTP. Upstream redirects are never
followed.

## Protected configuration

Inject these values through the deployment's protected runtime configuration;
do not put them in JavaScript, a tracked `.env` file, command arguments, test
reports, or backups of application data.

| Variable | Purpose |
| --- | --- |
| `PUBLIC_ORIGIN` | Exact public HTTPS origin, without a path, query, or fragment. |
| `SUPABASE_URL` | HTTPS origin of the isolated account project's GoTrue/PostgREST gateway. |
| `SUPABASE_PUBLISHABLE_KEY` | Public publishable/legacy anon key. A service key is rejected here. |
| `INVITE_TOKEN_KEY_BASE64` | Stable, protected base64 encoding of at least 32 random bytes; shared by API and worker. |
| `SUPABASE_SERVICE_ROLE_KEY` | Required only in the separate invitation mail worker process. Never used for user requests. |
| `SMTP_HOST`, `SMTP_PORT` | Invitation SMTP host and port, normally 587 for STARTTLS or 465 for TLS. |
| `SMTP_MODE` | `starttls` (default) or `ssl`; TLS is mandatory and certificates are verified. |
| `SMTP_FROM` | A single authorized sender mailbox. |
| `SMTP_USER`, `SMTP_PASSWORD` | SMTP credentials, both configured together when authentication is required. |

Keep `INVITE_TOKEN_KEY_BASE64` stable across restarts and retries. Replacing it
requires revoking pending invitations before creating replacements. The key is
independent of the database and service-role credential. The API process can omit
the service-role and SMTP credentials entirely. Its `/api/config` response exposes
only `supabaseUrl`, `publishableKey`, `publicOrigin`, display fields, and `enabled`.

Local development additionally requires `ACCOUNT_DEV_LOOPBACK=1` to permit HTTP
origins on `127.0.0.1`, `::1`, or `localhost`. Plain SMTP requires **both** that flag
and `SMTP_PLAIN_LOOPBACK_TEST=1`, with `SMTP_MODE=plain` and a loopback SMTP host.
This mode is for a local capture sink with fake `.invalid` addresses. Development
and automated tests must never use a real recipient or a production project.

## API contract

All POST requests require `Content-Type: application/json` and an exact
`Origin: PUBLIC_ORIGIN`. Cookie authentication is not used. Send
`Authorization: Bearer <user access token>` for authenticated actions. The server
does not trust forwarded client IP headers. Apply shared rate limits at the edge
when running multiple instances; built-in public account limits are per process.
Auth bodies are limited to 16 KiB and financial compare-and-set bodies to 1 MiB.
Upstream calls time out after 10 seconds. Responses have `Cache-Control: no-store`
and `Referrer-Policy: no-referrer`.

| Endpoint | JSON body / response |
| --- | --- |
| `GET /api/config` | Public runtime configuration. |
| `POST /api/auth/signup` | `{email,password}` → neutral `{message}`. |
| `POST /api/auth/login` | `{email,password}` → `{session}`. |
| `POST /api/auth/confirm` | `{token_hash,type}` → `{session}`; type `signup`, `recovery`, `email`, `invite`, or `email_change`. PKCE exchange requires `{code,code_verifier}`. |
| `POST /api/auth/recover` | `{email}` → neutral `{message}`. |
| `POST /api/auth/resend` | `{email,type:"signup"}` → neutral `{message}`. |
| `POST /api/auth/reset` | `{password}`, recovery session bearer → `{user}`. |
| `POST /api/auth/refresh` | `{refresh_token}` → `{session}`. |
| `POST /api/auth/logout` | `{}`, session bearer → `{ok:true}`. |
| `POST /api/invites/create` | `{household_id,email,role,request_id}`; role `editor` or `viewer`, request UUID retained for retries → canonical SQL invitation including `mail_status`. |
| `POST /api/rpc/<name>` | The allowlisted `finance_*` public function's named `p_...` arguments → SQL JSON result. |

Failures use `{error:{code,message}}`. Signup, recovery, and resend conceal account
existence; they do not promise delivery. Provider outages return an error instead
of simulated success. Login/confirm/refresh succeed only when GoTrue returns a
real access token and refresh token. User RPCs always receive the caller's bearer
token and publishable key. `finance_create_invite` and the mail worker functions
are excluded from the generic RPC proxy.

The invitation route gets the inviter's canonical user UUID from GoTrue `/user`,
requires confirmed email, then calculates a 256-bit HMAC token over a
versioned canonical tuple of request UUID, household UUID, normalized email, and
that user UUID. It passes only `SHA256(token UTF8)` to `finance_create_invite`.
Injected inviter IDs and token hashes are rejected. SQL independently checks
ownership, roles, request idempotency, membership, invitation status, and expiry.

## Confirmation and recovery mail

Configure **GoTrue's own SMTP** for signup confirmation, confirmation resend,
and password recovery. The account gateway forwards these calls to GoTrue; it
never invents confirmation tokens and never replaces confirmation with a fake
success session. Keep email autoconfirm disabled. Configure GoTrue's site URL and
redirect allowlist to the exact `PUBLIC_ORIGIN/`. The API supplies that fixed
redirect and rejects client-provided redirect URLs.

The default GoTrue verification link redirects to the public shell with a session
in the URL fragment. The shell must consume and immediately remove it. Recovery
opens the password form and updates the password using the recovery access token.
Custom email templates may instead point to
`PUBLIC_ORIGIN/?token_hash=...&type=signup` (or `recovery`); the shell exchanges it
through `/api/auth/confirm` and removes the query immediately. Edge access logs
must redact these callback parameters too.

## Invitation worker and delivery status

Run `python3 server/account_gateway.py --worker-once` from a scheduler, or invoke
`MailWorker.run_once()` repeatedly in a supervised worker. Each invocation claims
one job through `finance_claim_mail_jobs`; multiple workers can run concurrently.
Claiming one job at a time avoids a batch spending another job's 120-second lease
waiting for SMTP. Keep worker clocks synchronized and upstream timeouts short.
The claim must include its authoritative `lease_until` timestamp. The worker
rejects an expired or missing lease and limits the entire SMTP connection,
TLS handshake, authentication, and DATA exchange to the lesser of 60 seconds or
the remaining lease minus a 10-second status-update margin. Slow multiline
replies cannot extend that absolute deadline by resetting socket timeouts.

The worker reconstructs the stable raw token from canonical job metadata and
checks its hash against the database before SMTP. A mismatch never sends mail.
The plain text invitation link is `PUBLIC_ORIGIN/#invite_token=<hex token>`; the
token is in the fragment, so it is not sent in HTTP requests or referrers.

`finance_finish_mail_job` receives `p_sent=true` only after the SMTP server accepts
the DATA transaction. Recipient refusal, connection, TLS, and authentication
failures produce safe error codes and database-managed retry/backoff. SQL rejects
stale leases and stops after five failed attempts. `sent` means the SMTP server
accepted the message, not that it reached the recipient's inbox. Successful QUIT
is not needed to establish acceptance.

SMTP delivery is at least once: a worker crash after SMTP acceptance and before
the database status update can deliver a duplicate on retry. A stable Message-ID
helps mail systems deduplicate, and accepting an invitation is idempotent. No
claim of exactly-once external email delivery is made.

## Полная копия устройства и настройки семьи

В публичном клиенте «Полная копия устройства» сохраняет исходные финансовые
строки выбранного аккаунта и семьи, очередь, конфликты и состояние памяти.
Дополнительный `household_metadata` содержит только `household_id`, `name`,
`timezone`, `people` и `categories`. Элементы каталогов сохраняются с `id`, `name`
и `archived`, включая неиспользованные и архивные элементы. Сессии, email аккаунта,
роли, тариф и приглашения в этот снимок настроек не входят. Копирование не меняет
очередь, настройки семьи или локальное хранилище. Строковые элементы каталогов
старого формата сохраняются без преобразования и синтетических идентификаторов.

Поле `household_metadata_sha256_utf8` — SHA-256 от UTF-8 строки
`JSON.stringify(capture.household_metadata)`. Это отдельная контрольная сумма
снимка настроек; исходные финансовые строки сохраняют собственные контрольные
суммы. Перед подготовкой файла клиент повторно сравнивает настройки, финансовые
строки и состояние памяти, а также проверяет, что аккаунт и доступ не сменились
во время вычисления сумм. При изменениях файл не подготавливается.

Обычная «Резервная копия JSON» и её импорт сохраняют прежний финансовый формат.
Настройки семьи из полной копии автоматически не импортируются. Полную копию
устройства нельзя загружать через обычный импорт JSON; существующие закрытые
средства восстановления личной установки не поддерживают публичный формат
`family-budget-local-queue-capture-v1` и не должны применяться к нему.

При ручном восстановлении настроек владелец сначала проверяет контрольную сумму,
сверяет `household_id` с выбранной семьёй и просматривает название, часовой пояс и
оба каталога. Сопровождающий затем вызывает `POST /api/rpc/finance_update_settings`
с текущей пользовательской сессией владельца: `p_household_id` берётся из
проверенного текущего доступа, `p_name` и `p_timezone` — из просмотренного снимка,
`p_people` и `p_categories` — из проверенных каталогов, `p_request_id` — новый UUID.
Идентификаторы элементов и архивные отметки сохраняются. Сервер повторно проверяет
права владельца; элементы старого формата передаются как строки. При восстановлении
в другую семью соответствие и конфликты
идентификаторов требуют отдельного ручного решения; значение из файла не
переключает семью или локальный namespace. Финансовые записи восстанавливаются
отдельно и не переписываются этим вызовом. Членство, роли, тариф, приглашения и
учётные записи этим способом не восстанавливаются.

## Verification

Run `python3 -m unittest discover -s tests -p 'test_account_gateway.py' -v`.
The suite uses a real loopback HTTP server with a documented GoTrue/PostgREST
contract fixture and a real SMTP capture server. It verifies authenticated
forwarding, origin/host checks, limits, neutral responses, fixed redirects,
idempotent token derivation, bad JWT/foreign household fixture failures, refusal
and retry, hash mismatch, mandatory TLS, verified STARTTLS and implicit TLS, and
public/private configuration boundaries. The fixture is explicitly not proof of
real GoTrue or PostgreSQL behavior; the isolated full-stack acceptance runner
must also exercise real GoTrue, PostgreSQL/PostgREST, and captured mail before
release. The TLS SMTP tests use `openssl` only to issue a local test certificate.

From the source checkout, run
`python3 tools/check_accounts_stack.py --report /tmp/accounts-full-stack.json`
for that full local acceptance check with real pinned GoTrue/PostgREST images,
PostgreSQL, the SMTP sink, gateway, and Chromium. Container images must already
be loaded; the runner uses `--pull=never` and a disposable internal Docker
network, then removes its containers and network. It uses fake data and captures
mail locally. `--backend-only` is a partial diagnostic, not the full acceptance
check. This runner and its test credentials are excluded from the downloadable
runtime bundle.

Build the explicit candidate download from the source checkout with
`python3 tools/build_accounts_bundle.py`. It writes
`preview/public-accounts-candidate.zip` with the nine allowlisted runtime sources,
a Russian setup README, and a SHA-256 manifest. It contains no environment files,
credentials, old personal root `index.html`, or backups. Rebuild after changing
any included source so the downloadable bytes and manifest remain current.

Production delivery remains a deployment configuration step: provide a verified
SMTP sender, credentials, DNS authentication, and GoTrue SMTP settings. Do not
enable real outbound delivery while validating the fake-data staging release.
