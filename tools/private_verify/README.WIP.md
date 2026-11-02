# Local verification — implementation resumed, native acceptance pending

Current status on 27 October: core.cjs, owner-export.sql/cjs, mac-main.cjs and
local-restore.cjs are implemented. Fictional differential comparison, real
PostgreSQL owner export, guarded selected-file IO and an actual PostgreSQL17.5
WASM four-table restore have focused tests. An integrated seven-file workflow
also executes the real restore and preserves review status for differences,
pending values and conflicts. See the respective tests, not the historical
stub description below, for the current executable contracts.

The new code-only Mac add-on is being packaged. A complete native Mac launch,
file selection and all-device comparison are still pending. No result here
authorizes production publication, and no real device reconciliation is claimed.
Original private backups remain unchanged. The restore covers four application
tables and Auth UUID stubs, not the complete Supabase/Auth platform.

## Historical checkpoint from the overnight pause

This is an explicit fail-closed checkpoint, not a usable verifier. The owner
asked to stop work for the night before implementation was completed. No private
inputs were read; no comparison or restoration result is claimed.

The behavior oracle is `tools/verify_private_backup.py`; existing fixtures are in
`tests/test_private_backup_verifier.py`. The planned core is filesystem-free and
network-free. A separate owner-local wrapper will select/read files safely.

Planned API:

- `parse(string|Buffer)`, `number(text)`, `equal(a,b)`, `cents(value)`.
- `stateRows(state)`, `stateHealth(state)`.
- `snapshot(parsedWrapper, project, household)` returns `{tables,state,health}`.
- `capture(parsedCapture, project, household, serverState, exportedState)` returns
  fixed counters, preserving corrupt/quarantined/conflicting variants.
- `compareDevices({server, devices:[{exported,captured,
  scope_verified_by_owner}], project, household, scopeAttested})` returns a
  device-phase report. It never claims an executed restore or release readiness.

Implementation notes already established against the oracle:

- Every JSON number must retain an exact lexical/decimal representation; financial
  values must never pass through binary floating-point JSON parsing. Use bounded
  BigInt coefficient/exponent semantics; booleans are distinct from numbers.
- Reject duplicate object keys, depth above64, nodes above500000, number tokens
  above512 characters, and Decimal tuple exponents outside±1000. Check the tuple
  exponent before removing trailing zeros: `1.0e1001` is allowed, `1e1001` and
  `0.0e-1000` are refused. Exact zero passes cents validation.
- `number()` for amount strings needs Python Decimal lexical parity, including
  plus signs, surrounding whitespace, `.1`, `1.`, underscores, and Unicode decimal
  digits; the JSON parser itself remains strict JSON.
- Identifier length is counted in Unicode code points, not UTF-16 units. Prototype
  names such as `__proto__` and `hasOwnProperty` must remain ordinary own keys.
- Raw capture UTF-8 hashing uses TextEncoder semantics (replace lone surrogates);
  UTF-16LE hashing preserves exact code units. Snapshot text rejects actual lone
  surrogates before UTF-8 hashing. No raw strings or errors are printed.
- Keep all unknown JSON fields and duplicate legacy rows. Duplicate IDs, corrupt
  values, conflict packets, divergent active/memory state, and any pending value
  require review; a matching pending value still needs server acknowledgement.
- The device phase must not manufacture `restored_file` by reusing source input.
  Joining local comparison to the separate worker restore remains under review.

No operational tests have passed for this checkpoint. The separate differential
test agent was preparing oracle cases when work was paused.
