# Release candidate review — NOT PUBLISHED

This candidate is prepared for owner review. Production, DNS, Cloudflare, Supabase configuration, real family records, and payments are not changed by the build or QA workflow.

## Approved expense form

One compact screen: amount, purchase/search, beneficiary, optional merchant visible. Date, payment method and comment belong under Details. Screenshots of the approved proposal are `mock-desktop.png` and `mock-mobile.png` in the external artifact directory. Final `candidate-form`, `candidate-home` and `candidate-loans` desktop/mobile screenshots were captured from the final sanitized candidate. Proposal screenshots are kept separately and do not stand in for implementation.

## Build and inspect safely

1. Run `python -m unittest discover -s tests -p test_build_bundle.py`.
2. Run `python -m unittest discover -s tests -p test_release_ui.py`. It generates only a temporary sanitized demo, serves only that demo directory on loopback, seeds fictional rich fixtures, and blocks every nonlocal request. The report is `/workspace/artifacts/release-ui-report.json` (override with `RELEASE_UI_REPORT`).
3. Run `python tools/build_bundle.py --output-dir /workspace/artifacts` after all source changes. The resulting `safe-demo.zip` is for review; `personal-installation-PRIVATE.zip` contains the exact personal client and must remain private. Each archive contains a SHA-256 manifest. Rebuild after modifying source; old ZIPs are stale.
4. For local inspection, serve only `/workspace/artifacts/safe-demo`; never serve its parent directory, which also contains the private installation. No localhost address is offered as an external review link.

The layout sweep covers all 11 sections (home, purchase form, history, analytics, income, car, loans, goals, chores, dates, settings), all requested widths (320, 360, 390, 430, 768, 1024, 1280, 1512, 1920), expanded purchase details, loan schedule/installment/early-payment controls, operation-edit modal, analytics drill modal and login presentation. It checks document horizontal overflow, horizontal modal bounds, console/page errors, and nonlocal requests. Synthetic fixtures include income/expenses/transfers, goals/deposits, dates, chores, notes, installment plans, budgets/regular plans and manual accounts. These checks do not substitute for financial logic tests or actual Safari/Yandex checks.

## Review register

| Area | Status / evidence |
| --- | --- |
| Compact form | Implemented in frozen local PR4 `fd83e47`. Six final candidate screenshots captured from the sanitized demo only; all four primary fields and Save are visible in the mobile form crop. |
| Offline demo privacy | Generator removes configured identities, real loan/family constants, backend client config and remote literals; focused checks passing at initial QA handoff. |
| Demo isolation | Separate storage namespace; original state preserved; browser edit survived reload; zero outbound requests in initial Chromium check. |
| Responsive candidate | Final app sweep passed: 144 checks across 9 widths, 11 sections and expanded forms/modals; no overflow or console/page errors. See `release-ui-report.json`, bound to the app source SHA-256. |
| Server synchronization | Separate CAS/authorization validation required. Offline demo and green UI checks do not prove production sync or RLS. |
| Telegram / feedback | Disabled in demo; production delivery remains separately unverified. |
| External HTTPS preview | Not provisioned. Needs authorized isolated hosting/access; never publish private client or real operations as the demo. |
| Browser access | Chromium available. Owner checks in Safari and Yandex Browser remain. |
| Focused checks | 19 sync, 15 isolated PostgreSQL, 18 finance, 7 form, 30 storage, 3 staging, 4 bundle; 1 UI sweep with 144 viewport/section checks. The integrated run passed 82 non-database tests. Database setup encountered transient init-server readiness; after waiting for the final TCP listener, all 15 database tests passed (9.662 s). Total: 97 passed across those runs; no skipped tests. Final bundle checks were also repeated after packaging updates. |
| Repository access | Normal GitHub access recovered and all stage 2–5 branches were pushed without force. Draft PRs #2, #3, #4 and #5 now exist with predecessor-branch bases. Main is unchanged. A sanitized recovery ZIP and standalone offline demo are available on the PR5 branch; no production deployment. |
| Publication | None. Owner approval required before changing the personal bank. |

## Backup, manual update, rollback

Before updating the personal bank, export the live JSON backup from the working app and confirm it downloads. Keep that backup private. Save the current deployed `index.html`, icons and CNAME separately with the date. Do not import or rewrite historical records as part of a static update.

Review the final candidate and the exact changed files first. Check its data-save status messages and recovery behavior using fictional data. The new client blocks cloud writes until the CAS server contract is installed, reviewed and activated; do not treat this as an ordinary static update. Included SQL is review/staging material, never automatic migration. Upload the personal static files only after explicit owner approval and through the owner's existing trusted hosting workflow. Keep CNAME only for the approved personal installation. The build does not trigger a deployment.

If the update fails, restore the saved prior static files and reload. Preserve browser storage and pending changes; do not clear site data to hide a sync issue. Keep real JSON exports untouched; any restore/import or server schema change needs its own reviewed backup and recovery plan. A static rollback does not undo remote writes, which is why no automatic migration or import is included here.

## Owner's final action

The concrete remaining access step is to provide or approve an isolated HTTPS preview destination for the sanitized demo. Production access is unnecessary for demo review. Once final QA passes and this destination is available, the safe demo can be uploaded to that destination for owner inspection; this document itself grants no production deployment approval.

## Exact verified application

Application commit: `fd83e47` (PR4). `index.html` SHA-256:
`d4960f314f08773c96914a27eaa8b3450812802d9f92c0e2924c8581e4b84370`.
PR5 adds packaging/tests/docs only; no further app change. Test logs are preserved
outside the checkout as review artifacts. The PostgreSQL runner fix changes only
test startup, not SQL or the application. No production authorization is implied.

Standalone owner review: `preview/safe-demo.html` is generated from the same sanitized demo transform, with an embedded favicon. It needs no server or account. This is fictional local-only review, not a hosted backend or production release.
