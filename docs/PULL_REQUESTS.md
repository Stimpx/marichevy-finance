# Prepared dependent Draft PRs

PR1 already exists: https://github.com/Stimpx/marichevy-finance/pull/1.
Its head `4aa2c75` and updated body were verified on GitHub before the current
credentials expired. Main was `bfc7ce5`; no merge or deployment was performed.

The prepared branches have now been pushed to GitHub using the normal connection after API authorization recovered (permissions.push=true). Draft PR creation and remote SHA verification are performed separately; no merge or deployment is authorized. The earlier 401 was not bypassed.

## Stage 2

Title: Protect cloud synchronization with server revisions and retained pending edits
Head: `codex/pr2-versioned-sync`; base: `codex/pr1-local-data-safety`.
Commit: `a23f840`. Details: [PR2_SYNC.md](PR2_SYNC.md).

Simultaneous device writes use bounded CAS conflict/retry instead of blind upserts.
Pending edits survive failed/partial acknowledgments and in-flight new edits.
All known collections/tombstones are checked; opaque intelligence fields survive.
New recurring/installment confirmations share stable business IDs across devices;
historical IDs remain intact. SQL, activation/rollback templates and local tests
are included. Nothing was applied to Supabase.

Validation: 19 browser protocol cases, 15 actual isolated PostgreSQL tests,
30 existing storage checks. Legacy servers are read-only for this client;
hosted schema/RLS/PostgREST validation and server activation remain release blockers.
Changed files: index.html, server/ (3), tests/test_sync_protocol.py,
tests/test_sync_database.py, docs/PR2_SYNC.md, docs/SYNC_SERVER.md, docs/WORK_LOG.md.

## Stage 3

Title: Reconcile actual installment payments and bound early-repayment projections
Head: `codex/pr3-financial-integrity`; base: `codex/pr2-versioned-sync`.
Commit: `aaf1685`. Details: [PR3_FINANCE.md](PR3_FINANCE.md).

Current linked amounts control installment paid/remaining totals. New confirmations
record actual and scheduled dates separately; unknown accounting mode requires an
explicit choice. Overdue obligations enter the forecast. Early repayment caps
principal, includes interest and separates unused cash/unknown bank charges.
Advisor and beneficiary cuts reflect available history without counting transfers.
No automatic operation migration, duplicate deletion or bank schedule replacement.

Validation: 18 finance regressions (14 assertion failures reproduced on baseline),
plus the affected two-device installment business-ID test. Changed files:
index.html, tests/test_financial_integrity.py, the explicit accounting-mode fixture
in tests/test_sync_protocol.py, docs/PR3_FINANCE.md, docs/WORK_LOG.md.
Remaining limits: bank payoff is an estimate; historical recurring start dates and
income completeness cannot be inferred.

## Stage 4

Title: Use one-screen expense entry with existing categories and recipients
Head: `codex/pr4-simple-expense-form`; base: `codex/pr3-financial-integrity`.
Commit: `fd83e47`. Details: [PR4_EXPENSE_FORM.md](PR4_EXPENSE_FORM.md).

Amount, purchase search, recipient and optional merchant are immediately visible.
Date/payment/comment are in Details. Existing search vocabulary/categories and
historical recipients remain; individual pets are selectable. Removes conflicting
old form CSS and uses a scoped replacement without adding important declarations.
No new payer requirement, wizard, integrations or historical reclassification.

Validation: 7 focused browser cases, followed by the candidate's full regression
and desktop/mobile screenshots. Changed files: index.html,
tests/test_expense_form.py, docs/PR4_EXPENSE_FORM.md, docs/WORK_LOG.md.
Final owner design assessment and actual Safari/Yandex checks remain.

## Stage 5 · cumulative v95-rc1 release candidate

Title: Prepare v95-rc1 family release with verified Supabase CAS and permission guards
Head: `codex/pr5-release-candidate`; base: `main`; [Draft PR5](https://github.com/Stimpx/marichevy-finance/pull/5).

PR5 now contains the whole PR1–PR5 candidate for one coordinated frontend release.
Do not merge intermediate frontend branches into main one by one: each main change
triggers GitHub Pages. Main still serves bfc7ce5/v94; this Draft PR does not publish.

The candidate preserves pending/base/conflict copies, resolves unrelated concurrent
edits with server CAS and stops ambiguous same-record conflicts without choosing by
device clock. It checks household access before opening cached data, fixes late auth
responses after logout, retains unknown JSON fields, supports decimal money entry
and keeps the mobile expense Save visible. Server migrations restrict table
capabilities and bind membership lookups while preserving trusted service-role use.

Evidence: full local regression 212/212 with 144 UI checks, runner 35/35 separately
(overlapping counts); actual production-shaped Supabase/PostgREST 46 checks and 9
current-client browser scenarios, 40 real HTTPS requests and one actual CAS conflict.
Native Chromium probe encountered this cloud environment's CA trust failure; real
Safari/iPhone and Yandex acceptance are not claimed. Source/SQL hashes and remaining
backup/device/approval prerequisites are in RELEASE_CANDIDATE.md.

Safe demo and PRIVATE installation packages remain separate, with manifests and
source hashes. Actual family backups must never enter Git, demo, staging Supabase
or reusable environment snapshots. Restore and queue checks remain private.

Release/rollback order is in RELEASE_RUNBOOK.md. Keep PR5 Draft until the verified
private real backup, device queues/acceptance and owner release approval are ready.
Production schema/data/permissions, DNS and Telegram were not changed.
