"""PR1 browser regressions; synthetic local data only, every external request blocked."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import threading
import unittest

from playwright.sync_api import sync_playwright

HTML = Path(os.environ.get('MARICHEVY_HTML', Path(__file__).resolve().parents[1] / 'index.html'))
PRIMARY = 'marichevy_state_v10'
PENDING = 'marichevy_pending_v10'
BACKUP = 'marichevy_state_backup_v44'
PRE_IMPORT = 'marichevy_pre_import_backup_v73'


def entry(identifier='fictional-entry', **fields):
    return dict(id=identifier, type='expense', date='2026-10-21', amount=17,
                category='Прочее', who='Вымышленный участник', store='Учебный магазин',
                comment='Только тестовые данные', **fields)


def fixture():
    return {'entries': [entry()], 'settings': {}}


class LocalDataSafety(unittest.TestCase):
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
        self.context = self.browser.new_context(timezone_id='Europe/Moscow', service_workers='block')
        self.context.route('**/*', lambda route: route.continue_()
                           if route.request.url.startswith(self.base) else route.abort())
        self.page = self.context.new_page()
        self.page.set_default_timeout(4000)
        self.page.on('dialog', lambda dialog: dialog.accept())

    def tearDown(self):
        self.context.close()

    def open(self, storage=None):
        if storage:
            self.context.add_init_script('''if (!sessionStorage.getItem('pr1-seeded')) {
                for (const [key,value] of Object.entries(%s)) localStorage.setItem(key,value);
                sessionStorage.setItem('pr1-seeded','1');
            }''' % json.dumps(storage))
        self.page.goto(self.base, wait_until='domcontentloaded')
        self.page.wait_for_function("typeof state==='object' && typeof exportData==='function'")
        self.assertIsNone(self.page.evaluate('session'), 'Tests must never authenticate')

    def import_data(self, value):
        payload = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        self.page.locator('#importFile').set_input_files(
            {'name': 'fictional-backup.json', 'mimeType': 'application/json', 'buffer': payload.encode()})
        self.page.wait_for_function("document.getElementById('importFile').value === ''")

    def snapshot(self):
        return self.page.evaluate('''() => ({state:JSON.stringify(state),
            storage:Object.fromEntries(Object.keys(localStorage).sort().map(k=>[k,localStorage.getItem(k)]))})''')

    def test_recover_corrupt_primary_from_backup_and_keep_after_reload(self):
        self.check_recovery('{broken')

    def test_recover_missing_primary_from_backup_and_keep_after_reload(self):
        self.check_recovery(None)

    def check_recovery(self, primary):
        storage = {BACKUP: json.dumps({'saved_at': '2026-10-21T00:00:00Z', 'data': fixture()})}
        if primary is not None:
            storage[PRIMARY] = primary
        self.open(storage)
        self.assertEqual(self.page.evaluate('state.entries.map(e=>e.id)'), ['fictional-entry'])
        self.page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
        self.page.reload(wait_until='domcontentloaded')
        self.assertEqual(self.page.evaluate('state.entries.map(e=>e.id)'), ['fictional-entry'])
        self.assertEqual(self.page.evaluate('(key)=>JSON.parse(localStorage.getItem(key)).data.entries.map(e=>e.id)', BACKUP),
                         ['fictional-entry'])

    def test_pending_recovery_replaces_corrupt_backup_and_quarantines_original(self):
        self.open({PENDING: json.dumps(fixture()), BACKUP: '{corrupt-backup'})
        self.assertEqual(self.page.evaluate('state.entries.map(e=>e.id)'), ['fictional-entry'])
        self.page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
        self.page.reload(wait_until='domcontentloaded')
        snapshot = self.snapshot()
        self.assertEqual(self.page.evaluate('state.entries.map(e=>e.id)'), ['fictional-entry'])
        self.assertEqual(json.loads(snapshot['storage'][BACKUP])['data']['entries'][0]['id'], 'fictional-entry')
        self.assertTrue(any('corrupt-backup' in value for key, value in snapshot['storage'].items()
                            if key != BACKUP), 'Original corrupt backup must remain available in quarantine')

    def test_no_valid_recovery_does_not_replace_corrupt_files_with_blank(self):
        storage = {PRIMARY: '{corrupt-primary', BACKUP: '{corrupt-backup', PENDING: '{corrupt-pending'}
        self.open(storage)
        self.page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
        self.page.reload(wait_until='domcontentloaded')
        for key, expected in storage.items():
            with self.subTest(key=key):
                self.assertEqual(self.page.evaluate('(key)=>localStorage.getItem(key)', key), expected)

    def fail_writes(self, key):
        self.page.evaluate('''key => {
            const original=Storage.prototype.setItem;
            Storage.prototype.setItem=function(k,v){
                if(k===key)throw new DOMException('Synthetic quota failure','QuotaExceededError');
                return original.call(this,k,v);
            };
        }''', key)

    def check_failed_entry_save(self, key):
        self.open()
        self.fail_writes(key)
        self.page.evaluate('''async () => {
            openEntry('expense'); document.getElementById('eAmount').value='123';
            document.getElementById('eCategory').value='Прочее';
            document.getElementById('eStore').value='Fictional unsaved shop';
            document.getElementById('eComment').value='Keep this form'; await addEntry();
        }''')
        self.assertEqual(self.page.locator('#eAmount').input_value(), '123')
        self.assertEqual(self.page.locator('#eStore').input_value(), 'Fictional unsaved shop')
        self.assertEqual(self.page.locator('#eComment').input_value(), 'Keep this form')
        self.assertEqual(self.page.locator('#saveMsg .success').count(), 0)
        self.assertNotIn('сохранена локально', self.page.locator('#saveMsg').inner_text().lower())

    def test_primary_write_failure_preserves_form_and_shows_no_success(self):
        self.check_failed_entry_save(PRIMARY)

    def test_pending_write_failure_preserves_form_and_shows_no_success(self):
        self.check_failed_entry_save(PENDING)

    def test_failed_pre_import_backup_aborts_before_mutation(self):
        self.open({PRIMARY: json.dumps(fixture())})
        before = self.snapshot()
        self.fail_writes(PRE_IMPORT)
        incoming = fixture()
        incoming['entries'] = [entry('fictional-new')]
        self.import_data(incoming)
        self.assertEqual(self.snapshot(), before)

    def check_failed_import_save(self, key):
        self.open({PRIMARY: json.dumps(fixture())})
        before = self.snapshot()
        self.fail_writes(key)
        incoming = fixture()
        incoming['entries'] = [entry('fictional-new')]
        self.import_data(incoming)
        after = self.snapshot()
        self.assertEqual(after['state'], before['state'])
        for storage_key in (PRIMARY, PENDING, BACKUP):
            self.assertEqual(after['storage'].get(storage_key), before['storage'].get(storage_key))
        message = self.page.get_by_text(re.compile('^Ошибка импорта:')).inner_text().lower()
        self.assertTrue(any(word in message for word in ('ошибка', 'не удалось', 'не сохран', 'отмен')), message)
        self.assertNotIn('импорт сохранён', message)
        self.assertNotIn('копия объединена', message)

    def test_failed_primary_import_save_is_atomic(self):
        self.check_failed_import_save(PRIMARY)

    def test_failed_pending_import_save_is_atomic(self):
        self.check_failed_import_save(PENDING)

    def check_malformed_import(self, value):
        self.open({PRIMARY: json.dumps(fixture())})
        before = self.snapshot()
        self.import_data(value)
        self.assertEqual(self.snapshot(), before)

    def test_import_export_reload_preserves_legacy_and_unknown_participants(self):
        self.open()
        records = [entry('legacy'), entry('modern'), entry('unknown')]
        records[0].update(category='Супермаркеты', who='Алиса')
        records[1].update(category='Вкусняшки', who='Не указано', beneficiary='Сергей')
        records[2].update(category='Историческая необычная категория', who='Вымышленный участник')
        self.import_data({'entries': records, 'settings': {}})
        with self.page.expect_download() as download:
            self.page.evaluate('exportData()')
        exported = json.loads(Path(download.value.path()).read_text())
        self.assertEqual(sorted(exported['entries'], key=lambda e:e['id']), sorted(records, key=lambda e:e['id']))
        self.page.reload(wait_until='domcontentloaded')
        self.assertEqual(sorted(self.page.evaluate('state.entries'), key=lambda e:e['id']), sorted(records, key=lambda e:e['id']))

    def check_surface(self, surface):
        self.open()
        result = self.page.evaluate('''surface => {
            state=blankState();window.__pr1Xss=0;
            const id="');window.__pr1Xss=1;//";
            const text='<img src=x onerror="window.__pr1Xss=2">fictional & text';
            const e={id,type:'expense',date:today(),amount:12,category:'Прочее',who:'Общее',store:text,comment:text};
            let root,selector='button';
            if(surface==='today'||surface==='recent'){
                state.entries=[e]; if(surface==='today'){renderToday();root='todayList'}else{renderHome();root='recent'}
            }else if(surface==='goals'){
                state.goals=[{id,name:text,target:100,saved:0,deposits:[]}];renderGoals();root='goalsList';selector='button.btn.danger';
            }else if(surface==='dates'){
                state.birthdays=[{id,name:text,date:'2000-01-01',note:text}];renderDates();root='birthdayList';selector='.birthday-row:not(.birthday-row-family) button';
            }else if(surface==='chores'||surface==='homeChores'){
                state.chores=[{id,title:text,dueDate:today(),assignee:'Семья',recurrence:'none'}];
                renderChores();root=surface==='chores'?'choresList':'homeChoresBody';
            }else if(surface==='board'){
                state.boardItems=[{id,text,author:'Семья',type:'message',created_at:new Date().toISOString()}];renderFamilyBoard();root='boardFeed';
            }else{
                const data=v84Data();
                if(surface==='budgets'){data.budgets=[{id,group:text,amount:10}];v84RenderBudgets();root='v84BudgetList'}
                if(surface==='recurring'){data.recurring=[{id,name:text,category:'Прочее',amount:10,day:1}];v84RenderRecurring();root='v84RecurringList'}
                if(surface==='accounts'){data.accounts=[{id,name:text,amount:10,updated_at:new Date().toISOString()}];v84RenderAccounts();root='v84AccountsList'}
            }
            const el=document.getElementById(root),button=el.querySelector(selector);
            const shown=el.textContent.includes(text),injected=el.querySelectorAll('img').length;
            if(button)button.click();
            return {shown,injected,clicked:!!button,xss:window.__pr1Xss,
                correctEditTarget:editId===id,editOpen:document.getElementById('editModal').classList.contains('open')};
        }''', surface)
        self.assertTrue(result['shown'], result)
        self.assertEqual(result['injected'], 0, result)
        self.assertTrue(result['clicked'], result)
        self.assertEqual(result['xss'], 0, result)
        if surface in ('today', 'recent'):
            self.assertTrue(result['correctEditTarget'], result)
            self.assertTrue(result['editOpen'], result)


MALFORMED_IMPORTS = {
    'invalid_json': '{',
    'null_entry': {'entries': [entry('partial-valid'), None], 'settings': {}},
    'invalid_entry': {'entries': [entry('partial-valid'), {'id': 'bad', 'amount': 'NaN'}], 'settings': {}},
    'invalid_goal': {'entries': [], 'settings': {}, 'goals': [{'id': 'bad-goal', 'target': {}}]},
    'null_chore': {'entries': [], 'settings': {}, 'chores': [None]},
    'null_account': {'entries': [], 'settings': {}, 'intelligence': {'accounts': [None]}},
    'installment_part_missing_date': {'entries': [], 'settings': {}, 'installments': [
        {'id': 'fictional-plan', 'name': 'Fictional plan', 'parts': [
            {'id': 'part-one', 'date': '2026-10-21', 'amount': 10},
            {'id': 'part-two', 'amount': 10}]}]},
    'board_author_object': {'entries': [], 'settings': {}, 'boardItems': [
        {'id': 'bad-note', 'text': 'Fictional text', 'author': {'toString': 'bad'}}]},
}
for _name, _value in MALFORMED_IMPORTS.items():
    setattr(LocalDataSafety, 'test_atomic_import_rejection_' + _name,
            lambda self, value=_value: self.check_malformed_import(value))


for _surface in ('today', 'recent', 'goals', 'dates', 'chores', 'homeChores', 'board', 'budgets', 'recurring', 'accounts'):
    setattr(LocalDataSafety, 'test_record_ids_cannot_execute_' + _surface,
            lambda self, surface=_surface: self.check_surface(surface))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--html', type=Path)
    args, remaining = parser.parse_known_args()
    if args.html:
        HTML = args.html.resolve()
    unittest.main(argv=[__file__, *remaining])
