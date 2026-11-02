"""Differential device-verification fixtures; no private inputs or network.

The existing Decimal-based Python verifier is the independent behavior oracle.
The Node implementation is only a device-comparison phase: these checks never
claim that executing either implementation restores a server or authorizes a
release. Every file and row generated below is deliberately fictional.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / 'tools/private_verify/core.cjs'
SPEC = importlib.util.spec_from_file_location('python_private_oracle', ROOT / 'tools/verify_private_backup.py')
ORACLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ORACLE)

PROJECT = 'abcdefghijklmnopqrst'
HOUSE = '11111111-1111-4111-8111-111111111111'
USER = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
OTHER = '22222222-2222-4222-8222-222222222222'
MARKER = 'FICTIONAL_PRIVATE_HISTORY_MUST_NOT_APPEAR'

RUNNER = r"""
'use strict';
const fs=require('node:fs');
const core=require(process.argv[1]);
const requests=JSON.parse(fs.readFileSync(0,'utf8'));
function parsed(value){return core.parse(value);}
function perform(q){
  switch(q.op){
    case 'parse': parsed(q.raw); return true;
    case 'parseBytes': core.parse(Buffer.from(q.hex,'hex')); return true;
    case 'equal': return core.equal(parsed(q.left),parsed(q.right));
    case 'cents': return core.cents(parsed(q.raw));
    case 'health': return core.stateHealth(parsed(q.raw));
    case 'snapshot': {
      const result=core.snapshot(parsed(q.raw),q.project,q.household);
      return {health:result.health,state_equal:core.equal(result.state,parsed(q.state))};
    }
    case 'capture': return core.capture(parsed(q.raw),q.project,q.household,parsed(q.server),parsed(q.exported));
    case 'compare': return core.compareDevices({server:parsed(q.server),project:q.project,household:q.household,
      scopeAttested:q.scopeAttested,devices:q.devices.map(d=>({exported:parsed(d.exported),captured:parsed(d.captured),
        scope_verified_by_owner:d.scope_verified_by_owner}))});
    case 'compareRaw': return core.compareDevices(parsed(q.raw));
    case 'prototypeSafety': {
      const value=parsed(q.raw);
      return {prototype_unchanged:({}).polluted===undefined,
        owns_proto:Object.hasOwn(value,'__proto__'),owns_has_own:Object.hasOwn(value,'hasOwnProperty'),
        keys:Object.keys(value).length};
    }
    default: throw new Error('invalid-test-operation');
  }
}
const results=requests.map(q=>{
  try{return {ok:true,value:perform(q)};}
  catch(error){const candidate=error?.code||error?.message;
    return {ok:false,code:typeof candidate==='string'&&/^[a-z][a-z0-9-]{0,80}$/.test(candidate)?candidate:'unexpected-node-error'};}
});
process.stdout.write(JSON.stringify(results));
"""


def dump(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'))


def state():
    return {
        'entries': [{'id': 'entry', 'type': 'expense', 'amount': '1250.50', 'date': '2026-10-23',
                     'installmentId': 'plan', 'installmentPartId': 'part', 'recurringId': 'recurring',
                     'recurringPeriod': '2026-10', 'comment': MARKER,
                     'unknown': {'keep': [None, True, {'x': 3}]}}],
        'goals': [{'id': 'goal', 'target': '12.30', 'saved': 0, 'monthly': '1e-2',
                   'deposits': [{'amount': '0.10', 'date': '2024-02-29'}]}],
        'birthdays': [{'id': 'birthday', 'date': '1990-01-01'}],
        'boardItems': [{'id': 'board', 'text': MARKER}], 'chores': [{'id': 'chore'}],
        'installments': [{'id': 'plan', 'amount': '1250.50', 'total': '1250.50',
                          'parts': [{'id': 'part', 'amount': '1250.50', 'date': '2026-10-23'}],
                          'links': {'part': 'entry'}, 'futurePlanField': {'preserve': True}}],
        'deletedEntries': {'old-entry': '2020-01-01T00:00:00Z'}, 'deletedGoals': ['old-goal'],
        'deletedChores': {}, 'deletedBirthdays': {}, 'deletedBoardItems': {}, 'deletedInstallments': {},
        'settings': {'futureField': {'nested': [1, 2, None]}},
        'intelligence': {'budgets': [{'id': 'budget', 'amount': 100}],
                         'recurring': [{'id': 'recurring', 'amount': '12.34'}],
                         'accounts': [{'id': 'account', 'amount': '-2.01'}],
                         'favorites': [{'id': 'favorite', 'amount': '12.30', 'unknown': {'keep': MARKER}}],
                         'deleted': {'budgets': {'old': '2020-01-01'}, 'accounts': {}, 'recurring': {},
                                     'favorites': {'old-favorite': '2020-01-01T00:00:00Z'}}},
        'futureCollection': [{'anything': MARKER}],
    }


def snapshot(state_raw):
    placeholder = 'FICTIONAL_STATE_SLOT'
    tables = {
        'households': [{'id': HOUSE, 'name': MARKER, 'unknown': {'retained': True}}],
        'household_members': [{'household_id': HOUSE, 'user_id': USER, 'role': 'owner'}],
        'family_state': [{'household_id': HOUSE, 'data': placeholder,
                          'updated_at': '2026-10-23T00:00:00Z', 'updated_by': USER}],
        'family_chore_deliveries': [{'household_id': HOUSE, 'chore_id': 'chore',
                                    'due_date': '2026-10-23', 'chat_id': MARKER, 'unknown': [True, None]}],
    }
    raw = dump(tables).replace(dump(placeholder), state_raw)
    return {'format': 'marichevy-private-server-backup-v1', 'project_ref': PROJECT,
            'configured_household': HOUSE, 'configured_household_count': 1, 'database_timezone': 'UTC',
            'read_only': True, 'captured_at_utc': '2026-10-23T00:00:00Z', 'query_sha256': '0' * 64,
            'snapshot_json': raw, 'snapshot_json_sha256': hashlib.sha256(raw.encode('utf8')).hexdigest()}


def captured(values):
    records = []
    for key, raw in values.items():
        utf16 = raw.encode('utf-16-le', errors='surrogatepass')
        utf8 = ORACLE.utf8_js(raw)
        records.append({'key': key, 'raw': raw, 'utf16_code_units': len(utf16) // 2,
                        'utf8_bytes': len(utf8), 'sha256_utf8': hashlib.sha256(utf8).hexdigest(),
                        'sha256_utf16le': hashlib.sha256(utf16).hexdigest()})
    return {'format': 'marichevy-local-queue-capture-v1', 'origin': ORACLE.ORIGIN,
            'device_clock_verified': False, 'session_included': False, 'storage_modified': False,
            'captured_at_device_utc': '2099-01-01T00:00:00Z', 'key_count': len(records), 'records': records}


def call_oracle(request):
    try:
        op = request['op']
        if op == 'parse':
            ORACLE.parse(request['raw']); result = True
        elif op == 'parseBytes':
            ORACLE.parse(bytes.fromhex(request['hex'])); result = True
        elif op == 'equal':
            result = ORACLE.equal(ORACLE.parse(request['left']), ORACLE.parse(request['right']))
        elif op == 'cents':
            result = ORACLE.cents(ORACLE.parse(request['raw']))
        elif op == 'health':
            result = ORACLE.state_health(ORACLE.parse(request['raw']))
        elif op == 'snapshot':
            _, selected, health = ORACLE.snapshot(ORACLE.parse(request['raw']), request['project'], request['household'])
            result = {'health': health, 'state_equal': ORACLE.equal(selected, ORACLE.parse(request['state']))}
        elif op == 'capture':
            result = ORACLE.capture(ORACLE.parse(request['raw']), request['project'], request['household'],
                                    ORACLE.parse(request['server']), ORACLE.parse(request['exported']))
        else:
            raise AssertionError('unsupported-oracle-operation')
        return {'ok': True, 'value': result}
    except ORACLE.InvalidBackup as error:
        return {'ok': False, 'code': str(error)}


class PrivateDeviceNodeParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')
        if cls.node is None:
            raise unittest.SkipTest('Node is required for differential verification')
        if not CORE.is_file():
            raise AssertionError('node-device-core-missing')

    def node_results(self, requests):
        env = os.environ.copy()
        env.pop('NODE_OPTIONS', None)
        env.pop('NODE_PATH', None)
        result = subprocess.run([self.node, '--no-global-search-paths', '-e', RUNNER, str(CORE)],
                                input=dump(requests), text=True, encoding='utf8', capture_output=True,
                                env=env, timeout=45)
        self.assertEqual(result.returncode, 0, 'node-runner-failed')
        self.assertEqual(result.stderr, '', 'node-runner-stderr')
        self.assertNotIn(MARKER, result.stdout, 'private-marker-disclosed')
        return json.loads(result.stdout)

    def parity(self, requests):
        expected = [call_oracle(request) for request in requests]
        actual = self.node_results(requests)
        for index, (left, right) in enumerate(zip(expected, actual)):
            self.assertEqual(right, left, f'case-{index}-oracle-mismatch')
        self.assertEqual(len(actual), len(expected))
        return actual

    def health_case(self, data):
        return {'op': 'health', 'raw': dump(data)}

    def capture_case(self, value, *, server=None, exported=None):
        base = dump(state())
        return {'op': 'capture', 'raw': dump(value), 'project': PROJECT, 'household': HOUSE,
                'server': base if server is None else server, 'exported': base if exported is None else exported}

    def test_exact_numbers_boolean_distinction_negative_zero_and_unknown_fields(self):
        pairs = [
            ('9007199254740992', '9007199254740993', False),
            ('-9007199254740993', '-9007199254740992', False),
            ('123456789012345678901234567890.123456789', '123456789012345678901234567890.123456788', False),
            ('1.2300', '123e-2', True), ('-0.000', '0', True), ('true', '1', False), ('false', '0', False),
            ('"1"', '1', False), ('{"x":[1,true,null]}', '{"x":[1,1,null]}', False),
            ('{"x":1,"y":2}', '{"y":2.0,"x":1e0}', True),
            ('{"future":{"amount":9007199254740993}}', '{"future":{"amount":9007199254740992}}', False),
        ]
        requests = [{'op': 'equal', 'left': left, 'right': right} for left, right, _ in pairs]
        result = self.parity(requests)
        self.assertEqual([item['value'] for item in result], [item[2] for item in pairs])

    def test_strict_json_duplicate_keys_bounds_and_utf8_failure_codes(self):
        raws = ['{"x":1,"x":2}', '{"__proto__":{},"__proto__":{}}', '{"x":',
                '{"x":NaN}', '{"x":Infinity}', '[1,]', '01', '+1', '1.', '.1', '\ufeff{}',
                '1e1001', '1e-1001', '0.0e-1000', '9' * 513,
                '[' * 65 + '0' + ']' * 65, '1.0e1001', '9' * 512,
                '{"note":"\\ud800","pair":"\\ud83d\\ude00"}']
        requests = [{'op': 'parse', 'raw': raw} for raw in raws]
        requests += [{'op': 'parseBytes', 'hex': value.hex()} for value in
                     (b'{}', b'\xef\xbb\xbf{}', b'{"x":"\xff"}', b'\xc3(')]
        self.parity(requests)

    def test_cent_values_match_decimal_semantics_without_float_rounding(self):
        values = ['1.2300', '1.2301', '0.00000000000000000000', '-0.00', '1e-2', '1e-3',
                  '9007199254740993.01', '-9007199254740993.01', '9999999999999999999.99', '1e19',
                  'true', 'false', 'null', '"12.30"', '" +12.30 "', '".10"', '"1."',
                  '"1_000.00"', '"not money"', '"NaN"', '"Infinity"']
        self.parity([{'op': 'cents', 'raw': value} for value in values])

    def test_decimal_string_lexical_unicode_and_exponent_boundaries(self):
        # Decimal strings have a deliberately wider grammar than JSON numbers.
        # This matters for legacy exports whose exact amounts stayed strings.
        amounts = [
            '', ' ', '+', '.', '_', '__1__2__.3__0__', '1e+0', '+.10', '-.00',
            '\t+0012.300\n', '\u00a012.30\u00a0', '١٢.٣٠', '１２.３０',
            '१_२.३०', '1٢.3０', '١٢e-١', '1e1_0', '1e_2', '1 e2',
            '1\x001', '0e1000', '0e1001', '0.0e1001', '0.0e-1000',
            '0e-1000', '1.0e1001', '1e-1000', '1e18', '1e19',
            '0.00000000000000000001', '0.0000000000000000001',
            '1000000000000000000.01', '999999999999999999.99',
            '-999999999999999999.99', '1.230000000000000000000000000000',
            '1.000000000000000000000000000001',
            '0' * 512, '0' * 513, ' ' * 512 + '0',
            'sNaN', '-NaN', '+Infinity', 'inf', '0x10', '\u22121.00',
        ]
        self.parity([{'op': 'cents', 'raw': dump(value)} for value in amounts])

    def test_json_byte_encodings_surrogate_pairs_and_complexity_boundaries(self):
        document = '{"future":{"astral":"😀","money":9007199254740993.01}}'
        byte_cases = [document.encode(encoding) for encoding in
                      ('utf-8', 'utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be',
                       'utf-32', 'utf-32-le', 'utf-32-be')]
        self.parity([{'op': 'parseBytes', 'hex': item.hex()} for item in byte_cases])
        self.parity([
            {'op': 'equal', 'left': '"\\ud83d\\ude00"', 'right': '"😀"'},
            {'op': 'equal', 'left': '"\\ud800"', 'right': '"\\ufffd"'},
            {'op': 'equal', 'left': '"\\ud800"', 'right': '"\\ud800"'},
            {'op': 'parse', 'raw': '[' * 64 + '0' + ']' * 64},
            {'op': 'parse', 'raw': '[' * 65 + '0' + ']' * 65},
            {'op': 'parse', 'raw': '[' + ','.join('0' for _ in range(499999)) + ']'},
            {'op': 'parse', 'raw': '[' + ','.join('0' for _ in range(500000)) + ']'},
        ])

    def test_prototype_named_properties_and_ids_remain_own_data(self):
        raw = '{"__proto__":{"polluted":true},"hasOwnProperty":{"keep":1},"constructor":null}'
        result = self.node_results([{'op': 'prototypeSafety', 'raw': raw}])[0]
        self.assertEqual(result, {'ok': True, 'value': {'prototype_unchanged': True, 'owns_proto': True,
                                                      'owns_has_own': True, 'keys': 3}})
        variants = []
        for name in ('__proto__', 'hasOwnProperty', 'constructor', '\U0001f600' * 512):
            data = state(); data['entries'][0]['id'] = name; data['installments'][0]['links']['part'] = name
            variants.append(self.health_case(data))
        self.parity(variants)

    def test_duplicate_ids_cents_dates_links_periods_and_tombstones_match_oracle(self):
        requests = [self.health_case(state())]
        changes = [
            lambda d: d['entries'].append(copy.deepcopy(d['entries'][0])),
            lambda d: d['intelligence']['favorites'].append(copy.deepcopy(d['intelligence']['favorites'][0])),
            lambda d: d['installments'][0]['parts'].append(copy.deepcopy(d['installments'][0]['parts'][0])),
            lambda d: d['deletedGoals'].append('old-goal'),
            lambda d: d['entries'][0].update(amount='0.001'),
            lambda d: d['entries'][0].update(date='2026-02-29'),
            lambda d: d['entries'][0].update(date='2000-02-29'),
            lambda d: d['entries'][0].update(date='1900-02-29'),
            lambda d: d['entries'][0].update(date='0000-01-01'),
            lambda d: d['entries'][0].update(recurringPeriod='2026-13'),
            lambda d: d['installments'][0].update(links={'part': 'missing'}),
            lambda d: d['entries'][0].update(installmentId='missing-plan'),
            lambda d: d['entries'][0].update(installmentPartId='missing-part'),
            lambda d: d['entries'][0].update(recurringId='missing-recurring'),
            lambda d: d['entries'][0].update(recurringId='old-recurring'),
            lambda d: d['intelligence']['deleted']['recurring'].update({'old-recurring': '2020-01-01'}),
        ]
        for change in changes:
            data = state(); change(data); requests.append(self.health_case(data))
        self.parity(requests)

    def test_malformed_collections_tombstones_and_records_fail_safely(self):
        requests = []
        changes = [lambda d: d.update(entries={}), lambda d: d.update(settings=[]),
                   lambda d: d['entries'].append(None), lambda d: d['entries'][0].update(id='bad\nidentifier'),
                   lambda d: d['intelligence'].update(favorites={}),
                   lambda d: d['intelligence']['deleted'].update(favorites={'bad': 42}),
                   lambda d: d['installments'][0].update(parts={}),
                   lambda d: d['installments'][0].update(links=[]),
                   lambda d: d['goals'][0].update(deposits=['not-record'])]
        for change in changes:
            data = state(); change(data); requests.append(self.health_case(data))
        self.parity(requests)

    def test_identifier_codepoint_lengths_controls_and_tombstone_variants(self):
        requests = []
        for name in ('', 'x' * 512, 'x' * 513, '😀' * 512, '😀' * 513,
                     'embedded\x00nul', 'delete\x7fcontrol', '\u0085allowed',
                     '__proto__', 'hasOwnProperty'):
            data = state(); data['entries'][0]['id'] = name
            data['installments'][0]['links']['part'] = name
            requests.append(self.health_case(data))
        for tombstones in ([], {}, ['old-entry', 'old-entry'], {'old-entry': ''},
                           {'old-entry': None}, ['old-entry', 1], False, None):
            data = state(); data['deletedEntries'] = tombstones
            requests.append(self.health_case(data))
        self.parity(requests)

    def test_snapshot_coverage_scope_hash_metadata_and_unknown_values(self):
        base = dump(state())
        value = snapshot(base)
        cases = [value]
        def table_change(change):
            item = copy.deepcopy(value); tables = json.loads(item['snapshot_json']); change(tables)
            item['snapshot_json'] = dump(tables)
            item['snapshot_json_sha256'] = hashlib.sha256(item['snapshot_json'].encode()).hexdigest()
            return item
        for field, replacement in [('configured_household', OTHER), ('project_ref', 'z' * 20),
                                   ('configured_household_count', True), ('configured_household_count', 2),
                                   ('read_only', 1), ('database_timezone', 'UTC\nprivate')]:
            item = copy.deepcopy(value); item[field] = replacement; cases.append(item)
        item = copy.deepcopy(value); item['snapshot_json'] += ' '; cases.append(item)
        cases += [table_change(lambda t: t.pop('family_chore_deliveries')),
                  table_change(lambda t: t['household_members'].clear()),
                  table_change(lambda t: t['household_members'][0].update(user_id='not-uuid')),
                  table_change(lambda t: t['households'].append(copy.deepcopy(t['households'][0]))),
                  table_change(lambda t: t['family_chore_deliveries'][0].update(household_id=OTHER)),
                  table_change(lambda t: t.update(unexpected=[]))]
        self.parity([{'op': 'snapshot', 'raw': dump(item), 'state': base, 'project': PROJECT,
                      'household': HOUSE} for item in cases])

    def test_snapshot_compound_duplicates_exact_scope_and_nested_integrity(self):
        base = dump(state()); original = snapshot(base)
        cases = []
        def changed_tables(change):
            item = copy.deepcopy(original)
            tables = json.loads(item['snapshot_json']); change(tables)
            item['snapshot_json'] = dump(tables)
            item['snapshot_json_sha256'] = hashlib.sha256(item['snapshot_json'].encode()).hexdigest()
            return item
        for table in ('household_members', 'family_state', 'family_chore_deliveries'):
            cases.append(changed_tables(lambda t, table=table:
                                       t[table].append(copy.deepcopy(t[table][0]))))
        cases += [
            changed_tables(lambda t: t['family_state'][0].update(data=[])),
            changed_tables(lambda t: t['households'][0].pop('id')),
            changed_tables(lambda t: t['household_members'][0].update(user_id=USER.upper())),
            changed_tables(lambda t: t['household_members'][0].update(user_id=USER.replace('-', ''))),
            changed_tables(lambda t: t['family_chore_deliveries'][0].update(chat_id='')),
            changed_tables(lambda t: t.update(family_chore_deliveries=None)),
        ]
        for replacement in (None, '', 'x' * 128, 'x' * 129, 'UTC\x00'):
            item = copy.deepcopy(original); item['database_timezone'] = replacement; cases.append(item)
        item = copy.deepcopy(original); item['snapshot_json'] = '{"private":"\ud800"}'
        item['snapshot_json_sha256'] = '0' * 64; cases.append(item)
        item = copy.deepcopy(original)
        item['snapshot_json'] = item['snapshot_json'].replace('"households":', '"households":[],"households":', 1)
        item['snapshot_json_sha256'] = hashlib.sha256(item['snapshot_json'].encode()).hexdigest()
        cases.append(item)
        self.parity([{'op': 'snapshot', 'raw': dump(item), 'state': base,
                      'project': PROJECT, 'household': HOUSE} for item in cases])

    def test_raw_utf8_utf16_surrogates_and_tampering_match_oracle(self):
        base = dump(state())
        values = [captured({ORACLE.STATE: base}),
                  captured({ORACLE.STATE: base, ORACLE.PENDING + '_corrupt_v1': 'left\ud800right'}),
                  captured({ORACLE.STATE: base, ORACLE.PENDING + '_corrupt_v1': '\U0001f600'}),
                  captured({ORACLE.STATE: base, ORACLE.PENDING + '_corrupt_v1': '\ud83d\ude00'})]
        changed = copy.deepcopy(values[1]); changed['records'][1]['raw'] = 'left\ufffdright'; values.append(changed)
        changed = copy.deepcopy(values[0]); changed['records'][0]['raw'] += ' '; values.append(changed)
        for field in ('utf16_code_units', 'utf8_bytes'):
            changed = copy.deepcopy(values[0]); changed['records'][0][field] = True; values.append(changed)
        self.parity([self.capture_case(item) for item in values])

    def test_pending_conflicts_quarantine_base_memory_and_missing_primary_counts(self):
        base = dump(state()); changed = state(); changed['futureCollection'][0]['anything'] = 'other variant'
        packet = {'household': HOUSE, 'local': state(), 'cloud': {'entries': [], 'settings': {}}}
        cases = [captured({ORACLE.STATE: base, ORACLE.PENDING: base}),
                 captured({ORACLE.STATE: base, ORACLE.PENDING: dump(changed)}),
                 captured({ORACLE.STATE: base, ORACLE.CONFLICT: dump(packet)}),
                 captured({ORACLE.STATE: base, ORACLE.CONFLICT + '_archive_fixture-1': dump(packet)}),
                 captured({ORACLE.STATE: base, ORACLE.PENDING + '_corrupt_v1': base}),
                 captured({ORACLE.STATE: base, ORACLE.PENDING: '{broken'}),
                 captured({ORACLE.BASE: dump({'household': HOUSE, 'url': 'https://' + PROJECT + '.supabase.co', 'data': state()})}),
                 captured({ORACLE.STATE: base, 'marichevy_state_backup_v44': dump({'data': state()})})]
        memory = captured({ORACLE.STATE: base}); memory['memory_state_json'] = dump(changed); cases.append(memory)
        memory = captured({ORACLE.STATE: base}); memory['memory_state_json'] = base; cases.append(memory)
        memory = captured({ORACLE.STATE: base}); memory['memory_state_json'] = {}; cases.append(memory)
        result = self.parity([self.capture_case(item) for item in cases])
        self.assertEqual(result[0]['value']['pending_values'], 1)
        self.assertEqual(result[0]['value']['divergent_active_values'], 0)
        self.assertEqual(result[1]['value']['divergent_active_values'], 1)
        self.assertEqual(result[2]['value']['conflict_packets'], 1)

    def test_capture_foreign_scope_session_keys_formats_and_metadata_fail(self):
        base = dump(state()); cases = []
        for key in (ORACLE.BASE, ORACLE.CONFLICT, ORACLE.CONFLICT + '_archive_valid'):
            cases.append(captured({ORACLE.STATE: base, key: dump({'household': OTHER, 'data': state()})}))
        cases.append(captured({ORACLE.STATE: base, ORACLE.BASE: dump({'household': HOUSE, 'url': 'https://foreign.invalid', 'data': state()})}))
        cases.append(captured({'marichevy_session_v10': MARKER}))
        for field, value in [('origin', 'https://foreign.invalid'), ('session_included', True),
                             ('storage_modified', True), ('device_clock_verified', True), ('key_count', True)]:
            item = captured({ORACLE.STATE: base}); item[field] = value; cases.append(item)
        item = captured({ORACLE.STATE: base}); item['records'].append(copy.deepcopy(item['records'][0])); item['key_count'] += 1; cases.append(item)
        self.parity([self.capture_case(item) for item in cases])

    def test_capture_all_preserved_variants_and_invalid_metadata(self):
        base = dump(state()); cases = []
        for backup in sorted(ORACLE.BACKUPS):
            for raw in ('{}', dump({'data': state()}), dump({'data': []}), '{bad'):
                cases.append(captured({ORACLE.STATE: base, backup: raw}))
        for key in sorted(key for key in ORACLE.KEYS if key.endswith('_corrupt_v1')):
            cases.append(captured({ORACLE.STATE: base, key: base}))
        for suffix in ('', '_', 'bad.dot', 'bad/path', 'x' * 100, '😀'):
            cases.append(captured({ORACLE.STATE: base,
                                   ORACLE.CONFLICT + '_archive_' + suffix: dump({'household': HOUSE})}))
        for replacement in ([], None, {}, [None]):
            item = captured({ORACLE.STATE: base}); item['records'] = replacement; cases.append(item)
        for field in ('key_count', 'session_included', 'storage_modified', 'device_clock_verified'):
            item = captured({ORACLE.STATE: base}); item.pop(field); cases.append(item)
        for key in (ORACLE.STATE, ORACLE.PENDING):
            cases.append(captured({ORACLE.STATE: base, key: 'null'}))
            cases.append(captured({ORACLE.STATE: base, key: dump({'entries': [], 'settings': []})}))
        memory = captured({ORACLE.STATE: base}); memory['memory_state_json'] = '{bad'; cases.append(memory)
        # A claimed memory-inclusion flag alone is not an in-memory value.
        memory = captured({ORACLE.STATE: base}); memory['memory_state_included'] = False; cases.append(memory)
        self.parity([self.capture_case(item) for item in cases])

    def test_device_phase_reports_review_for_pending_and_divergent_unknown_fields(self):
        base = dump(state())
        devices = [{'exported': base, 'captured': dump(captured({ORACLE.STATE: base})),
                    'scope_verified_by_owner': True} for _ in range(3)]
        requests = []
        for mode in ('matching', 'pending', 'unknown-divergence', 'unattested', 'corrupt', 'conflict'):
            variants = copy.deepcopy(devices)
            if mode == 'pending': variants[0]['captured'] = dump(captured({ORACLE.STATE: base, ORACLE.PENDING: base}))
            if mode == 'unknown-divergence':
                data = state(); data['settings']['futureField']['nested'][-1] = False
                variants[0]['exported'] = dump(data)
            if mode == 'unattested': variants[0]['scope_verified_by_owner'] = False
            if mode == 'corrupt': variants[0]['captured'] = dump(captured({ORACLE.STATE: base, ORACLE.PENDING + '_corrupt_v1': '{broken'}))
            if mode == 'conflict': variants[0]['captured'] = dump(captured({ORACLE.STATE: base, ORACLE.CONFLICT: dump({'household': HOUSE})}))
            requests.append({'op': 'compare', 'project': PROJECT, 'household': HOUSE, 'scopeAttested': True,
                             'server': dump(snapshot(base)), 'devices': variants})
        actual = self.node_results(requests)
        for index, (request, observed) in enumerate(zip(requests, actual)):
            self.assertTrue(observed['ok'], f'compare-case-{index}-threw')
            report = observed['value']
            expected = self.oracle_device_report(request)
            self.assertEqual(report['outcome'], expected['outcome'], f'compare-case-{index}-outcome')
            self.assertEqual(report['issues'], expected['issues'], f'compare-case-{index}-issues')
            self.assertEqual(report['counts'], expected['counts'], f'compare-case-{index}-counts')
            self.assertIs(report['restore_execution_verified'], False)
            self.assertIs(report['release_authorized'], False)
            for name, value in report['checks'].items():
                if 'restor' in name:
                    self.assertIsNot(value, True, 'device-phase-must-not-claim-restore')

    def test_device_phase_invalid_input_fails_closed_without_private_output(self):
        base = state()
        device = {'exported': base, 'captured': captured({ORACLE.STATE: dump(base)}),
                  'scope_verified_by_owner': True}
        options = {'server': snapshot(dump(base)), 'project': PROJECT, 'household': HOUSE,
                   'scopeAttested': True, 'devices': [device, copy.deepcopy(device)]}
        cases = []
        def add(change, expected):
            item = copy.deepcopy(options); change(item); cases.append((item, expected))
        add(lambda o: o.update(scopeAttested=False), 'private-input-not-authorized')
        add(lambda o: o.pop('scopeAttested'), 'private-input-not-authorized')
        add(lambda o: o.update(household=HOUSE.upper().replace('1', 'A', 1)), 'invalid-scope-id')
        add(lambda o: o.update(project='invalid'), 'invalid-project-ref')
        for count in (0, 1, 7):
            add(lambda o, count=count: o.update(devices=[copy.deepcopy(device) for _ in range(count)]),
                'both-device-bundles-required')
        add(lambda o: o.update(devices=None), 'both-device-bundles-required')
        add(lambda o: o['devices'].__setitem__(0, None), 'invalid-device-plan')
        add(lambda o: o['devices'][0].update(exported={'private': MARKER}), 'invalid-state-shape')
        add(lambda o: o['devices'][0]['captured'].update(records=[None]), 'invalid-capture-records')
        actual = self.node_results([{'op': 'compareRaw', 'raw': dump(item)} for item, _ in cases])
        for index, ((_, expected), result) in enumerate(zip(cases, actual)):
            self.assertTrue(result['ok'], f'failed-report-case-{index}-threw')
            report = result['value']
            self.assertEqual(report['outcome'], 'failed', f'failed-report-case-{index}-outcome')
            self.assertIn(expected, report['issues'], f'failed-report-case-{index}-code')
            self.assertIs(report['network_used'], False)
            self.assertIs(report['inputs_modified'], False)
            self.assertIs(report['restore_execution_verified'], False)
            self.assertIs(report['release_authorized'], False)
            self.assertNotIn(MARKER, dump(report))

    def test_device_phase_malformed_nested_link_types_do_not_escape_report(self):
        # The Python oracle's CLI catches unexpected legacy shapes generically.
        # Require the Node boundary to be at least equally private and fail closed.
        cases = []
        for field, replacement in (('installmentId', {'private': MARKER}),
                                   ('recurringId', [MARKER]),
                                   ('installmentPartId', {'private': MARKER})):
            data = state(); data['entries'][0][field] = replacement
            cases.append(data)
        data = state(); data['installments'][0]['links']['part'] = {'private': MARKER}; cases.append(data)
        data = state(); data['goals'][0]['deposits'] = None; cases.append(data)
        requests = []
        for data in cases:
            device = {'exported': data, 'captured': captured({ORACLE.STATE: dump(data)}),
                      'scope_verified_by_owner': True}
            options = {'server': snapshot(dump(data)), 'project': PROJECT, 'household': HOUSE,
                       'scopeAttested': True, 'devices': [device, copy.deepcopy(device)]}
            requests.append({'op': 'compareRaw', 'raw': dump(options)})
        for index, result in enumerate(self.node_results(requests)):
            self.assertTrue(result['ok'], f'malformed-shape-{index}-escaped')
            report = result['value']
            self.assertIn(report['outcome'], ('failed', 'review_required'))
            self.assertTrue(report['issues'])
            self.assertNotIn(MARKER, dump(report))
            self.assertIs(report['release_authorized'], False)
            self.assertIs(report['restore_execution_verified'], False)

    def oracle_device_report(self, request):
        # Fictional source and readback fixtures are distinct files. This is a
        # behavior oracle only, never a claim that these fixtures were restored.
        with tempfile.TemporaryDirectory(prefix='fictional-device-parity-') as directory:
            folder = Path(directory)
            (folder / 'server.json').write_text(request['server'])
            (folder / 'readback.json').write_text(request['server'])
            devices = []
            for index, device in enumerate(request['devices']):
                export_name, capture_name = f'export{index}.json', f'capture{index}.json'
                (folder / export_name).write_text(device['exported'])
                (folder / capture_name).write_text(device['captured'])
                devices.append({'export_file': export_name, 'capture_file': capture_name,
                                'scope_verified_by_owner': device['scope_verified_by_owner']})
            plan = {'format': 'marichevy-private-restore-plan-v1', 'project_ref': PROJECT, 'household_id': HOUSE,
                    'server_file': 'server.json', 'restored_file': 'readback.json', 'devices': devices}
            (folder / 'plan.json').write_text(dump(plan))
            return ORACLE.verify(folder / 'plan.json', allow_private_input=True)


if __name__ == '__main__':
    unittest.main()
