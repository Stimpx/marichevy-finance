"""Client sync protocol tests against synthetic, isolated in-memory Supabase routes.

These fixtures replace session/ensureToken only to exercise the sync protocol. They
never log in, use real credentials, or permit an external network request.
Run with --html PATH (or MARICHEVY_HTML) to compare an older client.
"""
import argparse
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import unittest
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

HTML = Path(os.environ.get('MARICHEVY_HTML', Path(__file__).resolve().parents[1] / 'index.html'))
PENDING = 'marichevy_pending_v10'
AT = '2026-10-21T12:00:00.000Z'
LATER = '2026-10-21T12:00:02.000Z'
LATEST = '2026-10-21T12:00:03.000Z'


def entry(identifier, **overrides):
    return dict(dict(id=identifier, type='expense', date='2026-10-21', amount=17,
                     category='Прочее', who='Общее', store='Fictional test shop',
                     created_at=AT, updated_at=AT), **overrides)


def fixture():
    return dict(entries=[], goals=[], birthdays=[], boardItems=[], chores=[], installments=[],
                deletedEntries={}, deletedGoals={}, deletedBirthdays={}, deletedBoardItems={},
                deletedChores={}, deletedInstallments={}, settings={},
                intelligence=dict(budgets=[], recurring=[], accounts=[],
                                  deleted=dict(budgets={}, recurring={}, accounts={})))


def all_collections():
    state = fixture()
    state['entries'] = [entry('entry')]
    state['goals'] = [dict(id='goal', name='Fictional goal', target=100, saved=0, updated_at=AT)]
    state['birthdays'] = [dict(id='birthday', name='Fictional date', date='2000-01-01', updated_at=AT)]
    state['boardItems'] = [dict(id='board', text='Fictional note', author='Семья', type='message', created_at=AT, updated_at=AT)]
    state['chores'] = [dict(id='chore', title='Fictional chore', assignee='Семья', dueDate='2026-10-21', recurrence='once', updated_at=AT)]
    state['installments'] = [dict(id='installment', title='Fictional purchase', kind='split', accountingMode='payments', amount=17, updated_at=AT,
                                  parts=[dict(id='part', date='2026-10-21', amount=17)], links={})]
    state['intelligence']['budgets'] = [dict(id='budget', group='Продукты', amount=100, updated_at=AT)]
    state['intelligence']['recurring'] = [dict(id='recurring', name='Fictional payment', amount=17, category='Прочее', day=21, updated_at=AT)]
    state['intelligence']['accounts'] = [dict(id='account', name='Fictional cash', amount=100, updated_at=AT)]
    return state


class MemoryCAS:
    """Atomic model of the public RPC contract, with explicit transport barriers."""
    def __init__(self):
        self.data = fixture()
        self.revision = 0
        self.protocol = 2
        self.request_id = None
        self.replays = {}
        self.lock = threading.Lock()
        self.calls = []
        self.blocked = []
        self.legacy_posts = []
        self.gets = []
        self.held = []
        self.hold_gets = 0
        self.hold_ack = False
        self.fail_rpc = False
        self.offline = False
        self.legacy_columns = False
        self.drop_next_ack = False
        self.conflict_always = False
        self.not_found = False
        self.bad_ack = None

    def row(self):
        return dict(data=deepcopy(self.data), updated_at=AT, sync_revision=self.revision,
                    sync_protocol=self.protocol, last_request_id=self.request_id)

    def answer(self, status):
        return dict(status=status, revision=self.revision, protocol=self.protocol,
                    data=deepcopy(self.data), request_id=self.request_id)

    def route(self, route, base, cloud_host):
        request = route.request
        url = urlparse(request.url)
        if request.url.startswith(base):
            route.continue_()
            return
        if url.scheme != 'https' or url.netloc != cloud_host:
            self.blocked.append(request.url)
            route.abort()
            return
        if request.method == 'GET' and url.path == '/rest/v1/family_state':
            self.gets.append(parse_qs(url.query))
            if self.offline:
                route.abort()
                return
            if self.legacy_columns and 'sync_revision' in parse_qs(url.query).get('select', [''])[0]:
                route.fulfill(status=400, json={'code': '42703', 'message': 'column sync_revision does not exist'})
                return
            result = [] if self.not_found else [self.row()]
            if self.legacy_columns:
                result = [dict(data=deepcopy(self.data), updated_at=AT)]
            if self.hold_gets:
                self.hold_gets -= 1
                self.held.append((route, result))
            else:
                route.fulfill(json=result)
            return
        if request.method == 'POST' and url.path == '/rest/v1/family_state':
            self.legacy_posts.append(request.post_data_json)
            route.fulfill(status=409, json={'message': 'Legacy blind writes are forbidden by protocol 2'})
            return
        if request.method != 'POST' or url.path != '/rest/v1/rpc/family_state_cas':
            self.blocked.append(request.url)
            route.abort()
            return
        body = request.post_data_json
        self.calls.append(deepcopy(body))
        required = {'p_household_id', 'p_expected_revision', 'p_data', 'p_request_id'}
        if set(body) != required or not isinstance(body['p_request_id'], str) or not body['p_request_id']:
            route.fulfill(status=400, json={'message': 'Invalid CAS request contract'})
            return
        if self.offline:
            route.abort()
            return
        if self.fail_rpc:
            route.fulfill(status=503, json={'message': 'Synthetic unavailable backend'})
            return
        with self.lock:
            if body['p_request_id'] in self.replays:
                result = deepcopy(self.replays[body['p_request_id']])
            elif self.not_found:
                result = self.answer('not_found')
            elif self.protocol != 2:
                result = self.answer('upgrade_required')
            elif self.conflict_always or body['p_expected_revision'] != self.revision:
                result = self.answer('conflict')
            else:
                self.data = deepcopy(body['p_data'])
                self.revision += 1
                self.request_id = body['p_request_id']
                result = self.answer('written')
                self.replays[body['p_request_id']] = deepcopy(result)
        if self.bad_ack and result['status'] == 'written':
            result = deepcopy(result)
            if self.bad_ack == 'changed-content':
                result['data']['entries'][0]['amount'] += 1
            elif self.bad_ack == 'missing-intelligence':
                result['data']['intelligence']['accounts'] = []
        if self.drop_next_ack:
            self.drop_next_ack = False
            route.abort()
        elif self.hold_ack:
            self.hold_ack = False
            self.held.append((route, result))
        else:
            route.fulfill(json=result)

    def release(self):
        pending, self.held = self.held, []
        for route, data in pending:
            route.fulfill(json=data)


class SyncProtocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                content = HTML.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *_args):
                pass

        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}/'
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.backend = MemoryCAS()
        self.contexts = []
        self.pages = []
        self.cloud_host = None

    def tearDown(self):
        self.backend.release()
        for context in self.contexts:
            context.close()

    def device(self, state=None, pending=False):
        context = self.browser.new_context(service_workers='block', timezone_id='Europe/Moscow')
        self.contexts.append(context)
        # The configured host is extracted from the source, never from credentials.
        import re
        cloud_host = re.search(r"url:\s*'https://([^']+)'", HTML.read_text()).group(1)
        context.route('**/*', lambda route: self.backend.route(route, self.base, cloud_host))
        page = context.new_page()
        self.pages.append(page)
        page.set_default_timeout(5000)
        page.on('dialog', lambda dialog: dialog.accept())
        page.goto(self.base, wait_until='domcontentloaded')
        page.wait_for_function("typeof state==='object' && typeof saveAll==='function'")
        self.assertIsNone(page.evaluate('session'), 'Protocol fixtures must start without real authentication')
        page.evaluate('''value => {
            stopCloudSync(); localStorage.clear(); state=normalize(value.data);
            // Explicit protocol-only fixture, bypassing login and token refresh.
            ensureToken=async()=>true;
            session={access_token:'synthetic-protocol-token',user:{id:'fictional-user'}};
            if(value.pending)savePendingLocal(); saveLocal();
            window.confirm=()=>true; window.__finished=false;
        }''', {'data': state or fixture(), 'pending': pending})
        return page

    def start(self, page, expression='pushCloud()'):
        page.evaluate('''expression => {
            window.__finished=false;window.__result=null;window.__failure=null;
            Promise.resolve().then(()=>eval(expression)).then(value=>window.__result=value)
                .catch(error=>window.__failure=String(error)).finally(()=>window.__finished=true);
        }''', expression)

    def finish(self, page):
        page.wait_for_function('window.__finished === true')
        self.assertIsNone(page.evaluate('window.__failure'))
        return page.evaluate('window.__result')

    def wait_held(self, count=1):
        # Playwright pumps route events while waiting; no timing-dependent sleeps.
        self.pages[0].wait_for_function('() => true')
        for _ in range(100):
            if len(self.backend.held) >= count:
                return
            self.pages[0].wait_for_timeout(10)
        self.fail(f'Expected {count} held network responses, got {len(self.backend.held)}')

    def pending(self, page):
        return page.evaluate('(key)=>JSON.parse(localStorage.getItem(key)||"null")', PENDING)

    def assert_no_legacy_write(self):
        self.assertEqual(self.backend.legacy_posts, [], 'New clients must never send a blind legacy POST')

    def concurrent_push(self, first, second):
        self.backend.hold_gets = 2
        self.start(first)
        self.start(second)
        self.wait_held(2)
        self.backend.release()
        results = [self.finish(first), self.finish(second)]
        self.assertEqual(results, [True, True])
        self.assert_no_legacy_write()

    def test_two_devices_concurrent_additions_survive_cas_conflict(self):
        a, b = fixture(), fixture()
        a['entries'], b['entries'] = [entry('device-a')], [entry('device-b')]
        self.concurrent_push(self.device(a, True), self.device(b, True))
        self.assertEqual({e['id'] for e in self.backend.data['entries']}, {'device-a', 'device-b'})
        self.assertGreaterEqual(len(self.backend.calls), 3, 'A stale revision must retry after a CAS conflict')
        self.assertEqual(self.backend.revision, 2)

    def test_concurrent_edit_delete_uses_record_and_tombstone_clocks(self):
        a, b = fixture(), fixture()
        a['entries'] = [entry('edit-wins', amount=23, updated_at=LATER), entry('delete-wins', updated_at=LATER)]
        b['deletedEntries'] = {'edit-wins': AT, 'delete-wins': LATEST}
        self.concurrent_push(self.device(a, True), self.device(b, True))
        self.assertEqual([(e['id'], e['amount']) for e in self.backend.data['entries']], [('edit-wins', 23)])
        self.assertEqual(self.backend.data['deletedEntries'], b['deletedEntries'])

    def test_all_collections_and_deletions_survive_conflict_roundtrip(self):
        data = all_collections()
        tombstones = fixture()
        top = [('entries', 'deletedEntries'), ('goals', 'deletedGoals'), ('birthdays', 'deletedBirthdays'),
               ('boardItems', 'deletedBoardItems'), ('chores', 'deletedChores'), ('installments', 'deletedInstallments')]
        for collection, deleted in top:
            data[collection].append(dict(data[collection][0], id='deleted-' + collection))
            tombstones[deleted]['deleted-' + collection] = LATEST
        for collection in ('budgets', 'recurring', 'accounts'):
            data['intelligence'][collection].append(dict(data['intelligence'][collection][0], id='deleted-' + collection))
            tombstones['intelligence']['deleted'][collection]['deleted-' + collection] = LATEST
        self.concurrent_push(self.device(data, True), self.device(tombstones, True))
        reader = self.device()
        self.assertTrue(reader.evaluate('syncFromCloud()'))
        saved = reader.evaluate('state')
        for collection, deleted in top:
            with self.subTest(collection=collection):
                self.assertEqual(len(saved[collection]), 1)
                self.assertEqual(saved[deleted], tombstones[deleted])
        for collection in ('budgets', 'recurring', 'accounts'):
            with self.subTest(collection=collection):
                self.assertEqual(len(saved['intelligence'][collection]), 1)
                self.assertEqual(saved['intelligence']['deleted'][collection], tombstones['intelligence']['deleted'][collection])

    def test_failed_rpc_retains_pending_and_manual_sync_reports_false(self):
        value = fixture(); value['entries'] = [entry('unsent')]
        page = self.device(value, True)
        self.backend.fail_rpc = True
        self.assertFalse(page.evaluate('syncFromCloud()'))
        self.assertEqual([e['id'] for e in self.pending(page)['entries']], ['unsent'])
        self.assertNotIn('Синхронизировано', page.locator('#syncStatus').inner_text())
        self.assertEqual(self.backend.revision, 0)
        self.assert_no_legacy_write()

    def test_lost_write_ack_retry_is_idempotent(self):
        value = fixture(); value['entries'] = [entry('once')]
        page = self.device(value, True)
        self.backend.drop_next_ack = True
        page.evaluate('pushCloud()')
        self.assertTrue(page.evaluate('pushCloud()'))
        self.assertEqual([e['id'] for e in self.backend.data['entries']], ['once'])
        self.assertIsNone(self.pending(page))
        self.assertGreaterEqual(len(self.backend.calls), 2)
        self.assert_no_legacy_write()

    def test_offline_edit_is_queued_and_syncs_when_network_resumes(self):
        page = self.device()
        self.backend.offline = True
        self.assertFalse(page.evaluate('''() => {state.entries.push(%s);return saveAll()}''' % json.dumps(entry('offline'))))
        self.assertEqual(self.pending(page)['entries'][0]['id'], 'offline')
        self.backend.offline = False
        self.assertTrue(page.evaluate('syncFromCloud()'))
        self.assertEqual([e['id'] for e in self.backend.data['entries']], ['offline'])
        self.assertIsNone(self.pending(page))
        self.assert_no_legacy_write()

    def test_new_mutation_during_ack_keeps_pending_until_later_write(self):
        value = fixture(); value['entries'] = [entry('first')]
        page = self.device(value, True)
        self.backend.hold_ack = True
        self.start(page, 'saveAll()')
        self.wait_held()
        # Queue the new mutation behind the in-flight write, holding its next read.
        self.backend.hold_gets = 1
        page.evaluate('''() => {state.entries.push(%s);window.__later=saveAll()}''' % json.dumps(entry('later')))
        self.backend.release()
        self.finish(page)
        self.wait_held()
        self.assertEqual({e['id'] for e in self.pending(page)['entries']}, {'first', 'later'})
        self.assertEqual([e['id'] for e in self.backend.data['entries']], ['first'])
        self.backend.release()
        self.assertTrue(page.evaluate('window.__later'))
        self.assertEqual({e['id'] for e in self.backend.data['entries']}, {'first', 'later'})
        self.assertIsNone(self.pending(page))

    def test_verifier_rejects_same_timestamp_changed_content_every_collection(self):
        page = self.device()
        results = page.evaluate('''value => {
            const out={};
            for(const key of ['entries','goals','birthdays','boardItems','chores','installments']){
                const actual=structuredClone(value);
                const field={entries:'amount',goals:'name',birthdays:'date',boardItems:'text',chores:'title',installments:'amount'}[key];
                actual[key][0][field]=typeof actual[key][0][field]==='number'?999:'changed';
                out[key]=verifiedCloudContains(actual,value);
            }
            for(const key of ['budgets','recurring','accounts']){
                const actual=structuredClone(value);actual.intelligence[key][0].amount+=1;
                out[key]=verifiedCloudContains(actual,value);
            }
            return out;
        }''', all_collections())
        self.assertEqual(results, dict.fromkeys(results, False))

    def test_verifier_rejects_missing_intelligence_and_tombstones(self):
        value = all_collections()
        for key in ('deletedEntries', 'deletedGoals', 'deletedBirthdays', 'deletedBoardItems', 'deletedChores', 'deletedInstallments'):
            value[key]['gone'] = LATEST
        for key in ('budgets', 'recurring', 'accounts'):
            value['intelligence']['deleted'][key]['gone'] = LATEST
        page = self.device()
        results = page.evaluate('''value => {
            const variants=[];
            for(const key of ['budgets','recurring','accounts']){
                const actual=structuredClone(value);actual.intelligence[key]=[];variants.push(actual);
            }
            for(const key of ['deletedEntries','deletedGoals','deletedBirthdays','deletedBoardItems','deletedChores','deletedInstallments']){
                const actual=structuredClone(value);delete actual[key].gone;variants.push(actual);
            }
            for(const key of ['budgets','recurring','accounts']){
                const actual=structuredClone(value);delete actual.intelligence.deleted[key].gone;variants.push(actual);
            }
            return variants.map(actual=>verifiedCloudContains(actual,value));
        }''', value)
        self.assertEqual(results, [False] * 12)

    def test_legacy_columns_are_read_only_and_pending_is_retained(self):
        self.backend.legacy_columns = True
        value = fixture(); value['entries'] = [entry('legacy-pending')]
        page = self.device(value, True)
        self.assertFalse(page.evaluate('syncFromCloud()'))
        self.assertEqual(self.pending(page)['entries'][0]['id'], 'legacy-pending')
        self.assertEqual(self.backend.calls, [])
        self.assert_no_legacy_write()
        self.assertTrue(any('sync_revision' in q.get('select', [''])[0] for q in self.backend.gets))
        self.assertTrue(any(q.get('select') == ['data,updated_at'] for q in self.backend.gets), 'An old schema may be read through the legacy fallback')

    def test_protocol_upgrade_required_never_blind_writes(self):
        for protocol in (1, 3):
            with self.subTest(protocol=protocol):
                self.backend.protocol = protocol
                value = fixture(); value['entries'] = [entry('unsupported-protocol')]
                page = self.device(value, True)
                self.assertFalse(page.evaluate('pushCloud()'))
                self.assertIsNotNone(self.pending(page))
                self.assertEqual(self.backend.revision, 0)
                self.assert_no_legacy_write()

    def test_conflicts_are_bounded_and_exhaustion_keeps_pending(self):
        self.backend.conflict_always = True
        value = fixture(); value['entries'] = [entry('retry-later')]
        page = self.device(value, True)
        self.assertFalse(page.evaluate('pushCloud()'))
        self.assertGreaterEqual(len(self.backend.calls), 2)
        self.assertLessEqual(len(self.backend.calls), 5)
        self.assertEqual(self.pending(page)['entries'][0]['id'], 'retry-later')
        self.assert_no_legacy_write()

    def test_missing_household_is_not_created_by_blind_post(self):
        self.backend.not_found = True
        value = fixture(); value['entries'] = [entry('unprovisioned')]
        page = self.device(value, True)
        self.assertFalse(page.evaluate('pushCloud()'))
        self.assertIsNotNone(self.pending(page))
        self.assertEqual(self.backend.revision, 0)
        self.assert_no_legacy_write()

    def test_two_devices_recurring_confirmation_has_one_business_id(self):
        value = all_collections(); value['entries'] = []
        a, b = self.device(value), self.device(value)
        for page in (a, b):
            page.evaluate("session=null")
            page.evaluate("v84ConfirmRecurring('recurring','2026-10')")
            page.evaluate("session={access_token:'synthetic-protocol-token',user:{id:'fictional-user'}}")
        self.concurrent_push(a, b)
        rows = [e for e in self.backend.data['entries'] if e.get('recurringId') == 'recurring']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], 'recurring:recurring:2026-10')
        self.assertEqual(rows[0].get('paymentKey'), rows[0]['id'])

    def test_two_devices_installment_confirmation_has_one_business_id(self):
        value = all_collections(); value['entries'] = []
        a, b = self.device(value), self.device(value)
        for page in (a, b):
            page.evaluate("session=null;v77PayPart('installment','part');session={access_token:'synthetic-protocol-token',user:{id:'fictional-user'}}")
        self.concurrent_push(a, b)
        rows = [e for e in self.backend.data['entries'] if e.get('installmentId') == 'installment']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], 'installment:installment:part')
        self.assertEqual(rows[0].get('paymentKey'), rows[0]['id'])
        self.assertEqual(self.backend.data['installments'][0]['links']['part'], rows[0]['id'])

        # Imported IDs may contain separators; distinct business keys cannot collide.
        self.backend = MemoryCAS()
        value = all_collections(); value['entries'] = []
        template = value['installments'][0]
        value['installments'] = []
        for plan_id, part_id in (('a:b', 'c'), ('a', 'b:c')):
            plan = deepcopy(template)
            plan['id'], plan['parts'][0]['id'] = plan_id, part_id
            value['installments'].append(plan)
        a, b = self.device(value), self.device(value)
        for page, plan_id, part_id in ((a, 'a:b', 'c'), (b, 'a', 'b:c')):
            page.evaluate('''ids => {
                session=null;v77PayPart(ids[0],ids[1]);
                session={access_token:'synthetic-protocol-token',user:{id:'fictional-user'}};
            }''', [plan_id, part_id])
        self.concurrent_push(a, b)
        self.assertEqual({e['id'] for e in self.backend.data['entries']},
                         {'installment:a%3Ab:c', 'installment:a:b%3Ac'})

    def test_written_ack_must_confirm_exact_snapshot_before_clearing_queue(self):
        for corruption in ('changed-content', 'missing-intelligence'):
            with self.subTest(corruption=corruption):
                self.backend = MemoryCAS()
                self.backend.bad_ack = corruption
                value = all_collections()
                page = self.device(value, True)
                self.assertFalse(page.evaluate('pushCloud()'))
                self.assertEqual(self.backend.revision, 1, 'The backend committed before its malformed acknowledgment')
                pending = self.pending(page)
                self.assertIsNotNone(pending)
                self.assertEqual(pending['entries'][0]['amount'], 17)
                self.assertEqual(len(pending['intelligence']['accounts']), 1)
                self.assertNotIn('Синхронизировано', page.locator('#syncStatus').inner_text())
                self.assert_no_legacy_write()

    def test_existing_uuid_payment_history_is_preserved(self):
        value = fixture()
        value['entries'] = [entry('historical-uuid-a', recurringId='recurring', recurringPeriod='2026-10'),
                            entry('historical-uuid-b', recurringId='recurring', recurringPeriod='2026-10')]
        page = self.device(value, True)
        self.assertTrue(page.evaluate('pushCloud()'))
        self.assertEqual({e['id'] for e in self.backend.data['entries']}, {'historical-uuid-a', 'historical-uuid-b'})

    def test_unknown_intelligence_extensions_survive_normalize_merge_and_cas(self):
        remote, local = fixture(), fixture()
        remote['intelligence']['futurePlans'] = [{'id': 'opaque-plan', 'payload': {'version': 9}}]
        remote['intelligence']['deleted']['futurePlans'] = {'opaque-gone': AT}
        local['intelligence']['futureFlags'] = {'opaque': [1, {'preserve': True}]}
        self.backend.data = deepcopy(remote)
        page = self.device(local, True)
        normalized = page.evaluate('value=>normalize(value)', remote)
        self.assertEqual(normalized['intelligence'].get('futurePlans'), remote['intelligence']['futurePlans'])
        self.assertEqual(normalized['intelligence']['deleted'].get('futurePlans'), remote['intelligence']['deleted']['futurePlans'])
        merged = page.evaluate('values=>mergeStates(...values.map(value=>normalize(value)))', [remote, local])
        self.assertEqual(merged['intelligence'].get('futurePlans'), remote['intelligence']['futurePlans'])
        self.assertEqual(merged['intelligence'].get('futureFlags'), local['intelligence']['futureFlags'])
        self.assertEqual(merged['intelligence']['deleted'].get('futurePlans'), remote['intelligence']['deleted']['futurePlans'])
        self.assertTrue(page.evaluate('pushCloud()'))
        self.assertEqual(self.backend.data['intelligence'].get('futurePlans'), remote['intelligence']['futurePlans'])
        self.assertEqual(self.backend.data['intelligence'].get('futureFlags'), local['intelligence']['futureFlags'])
        self.assertEqual(self.backend.data['intelligence']['deleted'].get('futurePlans'), remote['intelligence']['deleted']['futurePlans'])

    def test_get_and_cas_contract_use_revision_and_request_id(self):
        value = fixture(); value['entries'] = [entry('contract')]
        page = self.device(value, True)
        self.assertTrue(page.evaluate('pushCloud()'))
        self.assert_no_legacy_write()
        fields = self.backend.gets[0].get('select', [''])[0].split(',')
        self.assertEqual(set(fields), {'data', 'updated_at', 'sync_revision', 'sync_protocol', 'last_request_id'})
        self.assertEqual(self.backend.calls[0]['p_expected_revision'], 0)
        self.assertEqual(self.backend.calls[0]['p_data']['entries'][0]['id'], 'contract')
        self.assertIsInstance(self.backend.calls[0]['p_request_id'], str)
        self.assertTrue(self.backend.calls[0]['p_household_id'])
        self.assertIsNone(self.pending(page))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--html', type=Path)
    args, remaining = parser.parse_known_args()
    if args.html:
        HTML = args.html.resolve()
    unittest.main(argv=[__file__, *remaining])
