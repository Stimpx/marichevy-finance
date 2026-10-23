Run the PR1 local storage, JSON import/export, and record rendering regressions:

```sh
python tests/test_local_data_safety.py -v
python3 tests/test_staging_server.py -v
```

Requirements: Python 3, Playwright Python 1.62, and Chromium at `/usr/bin/chromium`.
No dependency installation or app server is needed. The suite starts and stops its
own HTTP server on a free loopback port, creates a fresh browser context for each
test, and aborts **all external requests** (including Supabase). It never signs in,
fakes authentication, reads real user data, or contacts external services. Browser
storage and imports contain fictional fixtures only.

To compare the same assertions against another HTML snapshot:

```sh
git show bfc7ce5:index.html > /tmp/marichevy-before-pr1.html
python tests/test_local_data_safety.py --html /tmp/marichevy-before-pr1.html -v
# Equivalent: MARICHEVY_HTML=/tmp/marichevy-before-pr1.html python tests/test_local_data_safety.py -v
```

The original snapshot is expected to fail. The tests drive the real file input,
JSON download, add-entry function/form, pagehide/reload lifecycle, and rendered
record buttons. Quota failures are injected only into `Storage.setItem` for the
specific key under test. Recovery and malformed import assertions compare persisted
bytes as well as in-memory state; valid roundtrips check legacy category/`who`,
unknown participant strings, and modern `beneficiary` without a whitelist.

Additional atomic import cases cover malformed installment parts and board authors,
plus failures while writing primary/pending import snapshots. Pending-only recovery
must regenerate a valid backup and retain corrupt backup bytes in quarantine.

The rendering cases click malicious record IDs in today/recent transactions,
goals, dates, chores/home reminders, board messages, budgets, recurring payments,
and manual accounts. Visible markup-like strings must stay literal text. These
cases deliberately assign synthetic records to live state so rendering remains
safe independently of import validation. The suite excludes cloud sync/CAS,
advisor, and financial calculation changes reserved for subsequent PRs.

The staging server tests use only the Python standard library. They check the
actual HTTP response policy, disabled backend configuration, separate storage
keys, denied private paths and denied mutation methods. They never use a backend.

Baseline evidence (2026-10-21): the same 23 tests against `bfc7ce5:index.html`
completed in 11.8 seconds with exit status 1: 21 failing tests, 22 failure reports
(the corrupt-file test reports both overwritten primary and backup). The valid
legacy roundtrip and invalid-JSON rejection passed. All ten malicious-ID button
cases executed the synthetic JavaScript marker on that baseline. The failures
also demonstrated missing backup recovery, corrupt-file replacement on pagehide,
misleading primary/pending write failure handling, import despite a failed
pre-import backup, and mutation from malformed nested records. No harness errors,
external backend calls, or real data were involved.

The five added cases were also run against that same original snapshot: all five
failed in 4.6 seconds (malformed installment part, malformed board author,
primary/pending import write failures, and pending-only recovery). Across the
original 23-test run and this targeted five-test run, the baseline has 26 failing
tests and 27 failure reports; the same two original tests pass.

PR1 implementation evidence (same environment, 2026-10-21):
`python tests/test_local_data_safety.py -q` completed the expanded full suite of
28 tests in 14.6 seconds, exit status 0 (`OK`), with no skips or harness errors.

Continuation: two additional tests reproduced discarded unknown top-level and
settings fields on the initial PR1 code. Both failed before the compatibility
fix; all 30 storage/browser tests now pass (13.4s), plus the 3 staging tests.

## Candidate regression (PR2–PR5)

Run `python -m unittest discover -s tests -v` once after integration. The current
baseline PR5 suite contained 97 tests: storage 30, staging server 3, client CAS 19, local
PostgreSQL 15, financial integrity 18, expense form 7, bundle 4, release layout 1
(the last test performs 144 view/width checks). The PostgreSQL image must already
be cached; see `docs/SYNC_SERVER.md`. No additional libraries are installed by the
suite. All browser data is synthetic; every external request is blocked or handled
by a strict in-memory protocol fixture. Protocol fixtures replace session/token
checks only in their isolated browser, never in the delivered personal client.

Focused commands: `python tests/test_sync_protocol.py -v`,
`python tests/test_financial_integrity.py -v`,
`python tests/test_expense_form.py -v`. These accept `--html PATH` for reproducing
failures against an older client. Protocol baseline failures and the later
unknown-intelligence regression were captured before each corresponding fix.
Financial baseline reproduced 14 failed assertions; all 18 cases pass afterward.
Green local tests do not establish hosted Supabase/RLS or actual Safari support.

## Продолжение 23 октября: фактический стенд

Полный локальный прогон текущего клиента завершил 146 тестов без пропусков
(56.143s), включая 144 UI-проверки. В него вошли дополнительные проверки
primary/pending, поздних auth-ответов и архива конфликтов. Позднее добавленный
read-only production inspector проверяется отдельно; его tests не вызывают
производственный API.

`tools/supabase_staging.py run` был отдельно выполнен на разрешённом новом
Supabase-стенде и прошёл33 реальных Auth/PostgREST/CAS/RLS шагов. Повторять
bootstrap на текущем стенде не нужно. `browser` проверил9 сценариев настоящего
клиента и сервера, включая независимые добавления, same-ID/edit-delete с
неверными часами, reload/offline и чужую семью. Тестовый bridge сохраняет TLS
и пересылает реальные ответы; не подменяет сервер. Native browser proxy/CA
этим не проверены; отдельный настоящий CORS preflight прошёл.

Обычный unittest по-прежнему использует синтетические/локальные зависимости,
не вызывает hosted runner и не копирует реальные данные. Подключение и
ограничения — docs/STAGING_SETUP.md; точные SHA/результаты — RELEASE_CANDIDATE.

## v95-rc1: фактическая схема и частные очереди

После read-only production inventory подготовлены 002/003 hardening и
production-shaped эволюция только фиктивного стенда. Новый общий прогон прошёл
212/212,84.274s, без skips; в нём 22 inspector, 18 permissions, 9 fixture-v2,
6 local-queue capture и остальные клиентские/финансовые проверки. Три финальных
runner-теста добавлены после загрузки общего набора; весь runner затем отдельно
прошёл35/35,0.025s. Указывать247 как число разных тестов нельзя.

```sh
PYTHONPATH=tests python3 -m unittest test_production_permissions test_staging_membership_v2 -v
PYTHONPATH=tests python3 -m unittest test_production_schema_inspector test_supabase_staging_runner -v
PYTHONPATH=tests python3 -m unittest test_local_queue_capture -v
```

Queue-capture тесты перехватывают точный production origin внутри Playwright и
отдают локальную синтетическую страницу. Во внешний production не обращаются,
его storage не читают. Проверяют реальные загрузки PRIVATE JSON, raw UTF-16,
хеши, отсутствие чтения сессии/изменения storage и отказ при гонке/неверном origin.
002/003 локально исполняются в PostgreSQL 16; это не заменяет Supabase17/PostgREST.

## Частный резерв: инструменты подготовлены, реальные данные не читались

```sh
PYTHONPATH=tests python3 -m unittest test_private_server_backup test_private_backup_verifier test_private_pg_restore test_build_bundle -v
```

53/53 прошли за 10.654s: 18 fixed-extractor boundary/file tests, 19 offline verifier,
12 PostgreSQL restore/integration и 4 bundle checks. Они проверяют только вымышленные
данные. Экспортёр использует fake transport; реальный production endpoint не вызывается.
Restore создаёт новый networkless tmpfs PostgreSQL без портов, восстанавливает четыре
app-таблицы с PK/FK/RLS и репетирует 001–003/CAS, сохраняя оригинальные поля.
Auth UUID stand-ins не являются восстановлением Supabase/Auth или всей платформы.

Проверены точные числа/часовой пояс/неизвестный JSON/tombstones, повреждения и
неоднозначности очередей, SQL/COPY injection, неизменённые исходники, закрытые пути,
право владельца/0700/0600, exclusive output, cleanup и отсутствие PII в ошибках.
Инструменты требуют явного разрешения на частные входы; действующий catalog-only
доступ автоматически не расширяется до истории. Реальный резерв/restore остаётся
незавершённым. Порядок: docs/PRIVATE_RESTORE_ACCEPTANCE.md.
