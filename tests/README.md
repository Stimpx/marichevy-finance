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
