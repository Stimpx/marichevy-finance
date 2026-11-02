"""Public account UI against a local fake API. No mail or hosted request is made."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import unittest

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'https://synthetic-auth.example.invalid'
TOKEN = 'a' * 64
LONG_NAME = 'Оченьдлинноеназваниесемьибезпробелов' * 3


def session(email='owner@example.invalid'):
    return {'access_token': 'access-' + email, 'refresh_token': 'refresh-' + email,
            'expires_at': 4102444800, 'user': {'id': email, 'email': email,
            'email_confirmed_at': '2026-01-01T00:00:00Z'}}


def family(identifier='one', role='owner', name='Учебная семья'):
    return {'id': identifier, 'household_id': identifier, 'name': name,
            'timezone': 'Europe/Moscow', 'role': role, 'plan': 'free',
            'settings': {'people': [], 'categories': []}}


FAKE_LEDGER = r"""
window.fakeLedger={mounts:[],late:[]};
window.FinanceLedger={mount(container,options){
 const id=options.household.id,key='fake-financial-pending:'+options.session.user.id+':'+id;
 const label=document.createElement('label');label.textContent='Черновик записи';
 const input=document.createElement('input');input.id='ledger-draft';input.setAttribute('aria-label','Черновик записи');
 input.value=localStorage.getItem(key)||'';input.addEventListener('input',()=>localStorage.setItem(key,input.value));
 label.append(input);container.replaceChildren(label);window.fakeLedger.mounts.push(id);
 const ready=options.request('finance_read_state',{p_household_id:id}).then(()=>window.fakeLedger.late.push(id)).catch(()=>{});
 return {ready,unmount(){container.replaceChildren();}};
}};
"""


class FakeAPI:
    def reset(self, families=None):
        self.families = families or []
        self.calls = []
        self.invites = []
        self.members = [{'user_id': 'owner@example.invalid', 'email': 'owner@example.invalid', 'role': 'owner'},
                        {'user_id': 'editor@example.invalid', 'email': 'editor@example.invalid', 'role': 'editor'}]
        self.expired = False
        self.delay_reads = False
        self.read_started = threading.Event()
        self.release_read = threading.Event()
        self.delay_refresh_email = None
        self.refresh_started = threading.Event()
        self.release_refresh = threading.Event()
        self.delay_login_email = None
        self.login_started = threading.Event()
        self.release_login = threading.Event()
        self.real_ledger = False
        self.financial = {}

    def __init__(self):
        self.reset()

    def auth_session(self, email='owner@example.invalid'):
        result = session(email)
        if self.real_ledger:
            result['user']['id'] = '33333333-3333-4333-8333-333333333333'
        return result

    def handle(self, path, body, headers):
        self.calls.append((path, body))
        if path == '/api/config':
            return 200, {'enabled': True, 'supabaseUrl': PROJECT, 'publishableKey': 'sb_publishable_synthetic', 'appName': 'Семейные финансы'}
        if path.startswith('/api/auth/'):
            action = path.rsplit('/', 1)[-1]
            if action == 'refresh':
                if self.expired:
                    return 401, {'error': {'code': 'invalid_grant'}}
                email = body['refresh_token'].removeprefix('refresh-')
                if email == self.delay_refresh_email:
                    self.refresh_started.set()
                    self.release_refresh.wait(5)
                return 200, {'session': self.auth_session(email)}
            if action == 'login':
                if body['email'] == self.delay_login_email:
                    self.login_started.set()
                    self.release_login.wait(5)
                result = self.auth_session(body['email'])
                if body['email'] == 'pending@example.invalid':
                    result['user']['email_confirmed_at'] = None
                return 200, {'session': result}
            if action == 'confirm':
                if body.get('token_hash') != 'synthetic-confirmation':
                    return 400, {'error': {'code': 'invalid_token'}}
                return 200, {'session': self.auth_session()}
            if action == 'reset':
                return 200, {'user': self.auth_session()['user']}
            return 200, {'message': 'Если адрес доступен, письмо будет отправлено.'}
        name = path.rsplit('/', 1)[-1]
        email = headers.get('Authorization', '').removeprefix('Bearer access-')
        if name == 'finance_list_households':
            return 200, self.families
        if name == 'finance_get_household':
            result = next((item for item in self.families if item['id'] == body['p_household_id']), None)
            return (200, result) if result else (403, {'error': {'code': 'not_member'}})
        if name == 'finance_create_household':
            result = family('created', name=body['p_name'])
            result['timezone'] = body['p_timezone']
            self.families.append(result)
            return 200, result
        if name == 'finance_read_state':
            if self.delay_reads and body['p_household_id'] == 'one':
                self.read_started.set()
                self.release_read.wait(5)
            identifier = body['p_household_id']
            value = self.financial.setdefault(identifier, {'household_id': identifier, 'data': {'entries': [], 'settings': {}}, 'sync_revision': 0, 'sync_protocol': 2})
            return 200, [value]
        if name == 'finance_state_cas':
            value = self.financial[body['p_household_id']]
            if value['sync_revision'] != body['p_expected_revision']:
                return 200, {'status': 'conflict', 'protocol': 2, 'revision': value['sync_revision'], 'data': value['data']}
            value['data'] = body['p_data']
            value['sync_revision'] += 1
            return 200, {'status': 'written', 'protocol': 2, 'revision': value['sync_revision'], 'data': value['data'], 'request_id': body['p_request_id']}
        if name == 'finance_list_members':
            return 200, self.members
        if name == 'finance_list_invites':
            return 200, self.invites
        if name == 'finance_update_settings':
            result = next(item for item in self.families if item['id'] == body['p_household_id'])
            result.update(name=body['p_name'], timezone=body['p_timezone'], settings={'people': body['p_people'], 'categories': body['p_categories']})
            return 200, result
        if path == '/api/invites/create':
            invite = {'id': 'invite-one', 'email': body['email'], 'role': body['role'], 'status': 'pending', 'mail_status': 'failed'}
            self.invites.append(invite)
            return 200, invite
        if name == 'finance_revoke_invite':
            self.invites[0]['status'] = 'revoked'
            return 200, self.invites[0]
        if name == 'finance_set_member_role':
            self.members[1]['role'] = body['p_role']
            return 200, self.members[1]
        if name == 'finance_remove_member':
            self.members.pop()
            return 200, {'removed': True}
        if name == 'finance_accept_invite':
            if email != 'invited@example.invalid':
                return 403, {'error': {'code': 'invite_email_mismatch'}}
            result = family('invited', role='viewer')
            self.families.append(result)
            return 200, result
        return 404, {'error': {'code': 'unknown_endpoint'}}


class PublicAccountsUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = FakeAPI()
        api = cls.api

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def json_response(self, status, value):
                data = json.dumps(value, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                if self.path == '/ledger.js':
                    data = FAKE_LEDGER.encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/javascript')
                    self.end_headers()
                    self.wfile.write(data)
                elif self.path.startswith('/api/'):
                    self.json_response(*api.handle(self.path, {}, self.headers))
                else:
                    super().do_GET()

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.json_response(*api.handle(self.path, body, self.headers))

        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT / 'public')))
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
        self.api.reset()
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 900}, service_workers='block')
        self.outbound = []
        def local_only(route):
            if route.request.url.startswith(self.base):
                route.continue_()
            else:
                self.outbound.append(route.request.url)
                route.abort()
        self.context.route('**/*', local_only)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.set_default_timeout(5000)

    def tearDown(self):
        self.api.release_read.set()
        self.api.release_refresh.set()
        self.api.release_login.set()
        self.context.close()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.outbound, [])

    def login(self, email='owner@example.invalid'):
        self.page.locator('#auth-email').fill(email)
        self.page.locator('#auth-password').fill('Synthetic-password-26')
        self.page.locator('#auth-submit').click()

    def signed_in(self, families=None, email='owner@example.invalid'):
        self.api.families = families or [family()]
        self.page.goto(self.base)
        self.login(email)
        self.page.locator('[data-household]').first.wait_for()

    def open_settings(self):
        self.page.locator('[data-household]').first.click()
        self.page.locator('#nav-settings').click()
        self.page.locator('#settings-name').wait_for()

    def test_signup_pending_resend_login_and_empty_family(self):
        self.page.goto(self.base)
        self.page.locator('#auth-signup').click()
        self.page.locator('#auth-email').fill('new@example.invalid')
        self.page.locator('#auth-password').fill('Synthetic-password-26')
        self.page.locator('#auth-submit').click()
        self.page.locator('#auth-resend').click()
        self.page.locator('.form-success').wait_for()
        self.assertIn('Запрос принят', self.page.locator('.form-success').inner_text())
        self.assertFalse(any(path.endswith('finance_list_households') for path, _ in self.api.calls))
        self.page.locator('#pending-login').click()
        self.login()
        self.page.locator('#family-name').fill('Совершенно новая семья')
        self.page.locator('#family-timezone').fill('UTC')
        self.page.locator('#create-family').click()
        self.page.locator('#ledger-draft').wait_for()
        self.assertEqual(self.api.families[0]['settings'], {'people': [], 'categories': []})
        create = next(body for path, body in self.api.calls if path.endswith('finance_create_household'))
        self.assertEqual(create['p_name'], 'Совершенно новая семья')
        self.assertRegex(create['p_request_id'], r'^[a-f0-9-]{36}$')

    def test_confirmation_and_recovery_fragment_are_removed_before_requests(self):
        self.api.families = [family()]
        self.page.goto(self.base + '#token_hash=synthetic-confirmation&type=signup')
        self.page.locator('[data-household]').wait_for()
        self.assertEqual(self.page.url, self.base)
        self.page.locator('#logout').click()
        self.page.goto('about:blank')
        self.page.goto(self.base + '#access_token=synthetic-secret&refresh_token=refresh-owner%40example.invalid&type=recovery')
        self.page.locator('#reset-password').wait_for()
        self.assertEqual(self.page.url, self.base)
        self.assertEqual(self.page.locator('[data-household]').count(), 0)
        self.page.locator('#reset-password').fill('New-synthetic-password-26')
        self.page.locator('#reset-repeat').fill('New-synthetic-password-26')
        self.page.locator('#reset-submit').click()
        self.page.locator('[data-household]').wait_for()
        self.assertTrue(any(path == '/api/auth/reset' for path, _ in self.api.calls))
        self.assertNotIn('synthetic-secret', self.page.content())
        keys = self.page.evaluate('Object.keys(localStorage)')
        self.assertEqual(keys, ['finance.auth.v1:' + PROJECT])

    def test_recovery_request_has_neutral_status(self):
        self.page.goto(self.base)
        self.page.locator('#auth-recover').click()
        self.page.locator('#recover-email').fill('unknown@example.invalid')
        self.page.locator('#recover-submit').click()
        self.page.locator('.form-success').wait_for()
        self.assertIn('Ответ одинаков для любого адреса', self.page.locator('.form-success').inner_text())
        self.assertEqual(self.page.locator('[data-household]').count(), 0)

    def test_invitation_wrong_email_then_matching_verified_account(self):
        self.page.goto(self.base + '#invite_token=' + TOKEN)
        self.login('wrong@example.invalid')
        self.page.locator('#accept-invite').click()
        self.page.locator('.invitation-banner .form-error').wait_for()
        self.assertIn('другой почте', self.page.locator('.invitation-banner .form-error').inner_text())
        self.assertEqual(self.api.families, [])
        self.page.locator('#logout').click()
        self.login('invited@example.invalid')
        self.page.locator('#accept-invite').click()
        self.page.locator('#ledger-draft').wait_for()
        self.assertEqual(self.page.locator('#accept-invite').count(), 0)
        self.assertNotIn(TOKEN, self.page.content())

    def test_same_document_invitation_for_already_signed_in_account(self):
        self.signed_in([family()], 'invited@example.invalid')
        self.page.locator('[data-household]').click()
        self.page.locator('#ledger-draft').fill('Черновик до перехода по приглашению')
        self.page.goto(self.base + '#invite_token=' + TOKEN)
        self.page.locator('#accept-invite').wait_for()
        self.assertEqual(self.page.url, self.base)
        self.assertEqual(self.page.locator('#ledger-draft').count(), 0)
        self.assertIn('invited@example.invalid', self.page.locator('.invitation-banner').inner_text())
        self.assertEqual(sum(path == '/api/auth/login' for path, _ in self.api.calls), 1)
        self.page.locator('#accept-invite').click()
        self.page.locator('#ledger-draft').wait_for()
        self.assertEqual(self.api.families[-1]['id'], 'invited')
        self.assertIn('Черновик до перехода', self.page.evaluate("localStorage.getItem('fake-financial-pending:invited@example.invalid:one')"))

    def test_same_document_invitation_for_already_open_signed_out_page(self):
        self.page.goto(self.base)
        self.page.locator('#auth-submit').wait_for()
        self.page.goto(self.base + '#invite_token=' + TOKEN)
        self.page.get_by_text('У вас есть приглашение.', exact=False).wait_for()
        self.assertEqual(self.page.url, self.base)
        self.assertFalse(any(path.startswith('/api/rpc/') for path, _ in self.api.calls))
        self.login('invited@example.invalid')
        self.page.locator('#accept-invite').wait_for()
        self.page.locator('#accept-invite').click()
        self.page.locator('#ledger-draft').wait_for()
        self.assertEqual(self.api.families[-1]['id'], 'invited')

    def test_unverified_user_never_reads_family_data(self):
        self.page.goto(self.base)
        self.login('pending@example.invalid')
        self.page.locator('#auth-resend').wait_for()
        self.assertFalse(any(path.startswith('/api/rpc/') for path, _ in self.api.calls))

    def test_expired_saved_session_returns_to_login(self):
        self.api.expired = True
        storage_key = 'finance.auth.v1:' + PROJECT
        self.context.add_init_script('localStorage.setItem(' + json.dumps(storage_key) + ',' + json.dumps(json.dumps(session())) + ')')
        self.page.goto(self.base)
        self.page.locator('#auth-submit').wait_for()
        self.assertFalse(any(path.startswith('/api/rpc/') for path, _ in self.api.calls))
        self.assertIsNone(self.page.evaluate('(key)=>localStorage.getItem(key)', storage_key))

    def test_family_switch_preserves_scoped_pending_and_ignores_late_read(self):
        self.api.delay_reads = True
        self.signed_in([family('one'), family('two', name='Вторая учебная семья')])
        self.page.locator('[data-household="one"]').click()
        self.page.locator('#ledger-draft').fill('Несохранённая покупка первой семьи')
        self.assertTrue(self.api.read_started.wait(2))
        self.page.locator('#back-to-families').click()
        self.page.locator('[data-household="two"]').click()
        self.page.locator('#ledger-draft').wait_for()
        self.assertEqual(self.page.locator('#ledger-draft').input_value(), '')
        self.api.release_read.set()
        self.page.wait_for_timeout(120)
        self.assertNotIn('one', self.page.evaluate('window.fakeLedger.late'))
        self.page.locator('#back-to-families').click()
        self.page.locator('[data-household="one"]').click()
        self.assertEqual(self.page.locator('#ledger-draft').input_value(), 'Несохранённая покупка первой семьи')
        self.page.locator('#logout').click()
        self.assertIn('Несохранённая', self.page.evaluate("localStorage.getItem('fake-financial-pending:owner@example.invalid:one')"))

    def test_viewer_settings_and_members_are_read_only(self):
        self.signed_in([family(role='viewer')], 'viewer@example.invalid')
        self.open_settings()
        self.assertTrue(self.page.locator('#settings-name').is_disabled())
        self.assertEqual(self.page.locator('#settings-people-add').count(), 0)
        self.assertEqual(self.page.locator('#settings-save,#invite-send,.member-controls').count(), 0)
        self.assertFalse(any(path.endswith('finance_list_invites') for path, _ in self.api.calls))

    def test_new_tab_session_survives_older_inflight_refresh(self):
        self.api.families = [family()]
        self.api.delay_refresh_email = 'first@example.invalid'
        storage_key = 'finance.auth.v1:' + PROJECT
        self.context.add_init_script('localStorage.setItem(' + json.dumps(storage_key) + ',' + json.dumps(json.dumps(session('first@example.invalid'))) + ')')
        self.page.goto(self.base)
        self.page.locator('#logout').wait_for()
        self.page.wait_for_timeout(50)
        self.assertTrue(self.api.refresh_started.wait(2))
        second = session('second@example.invalid')
        self.page.evaluate('''({key,value})=>{
            const serialized=JSON.stringify(value);localStorage.setItem(key,serialized);
            window.dispatchEvent(new StorageEvent('storage',{key,newValue:serialized,storageArea:localStorage}));
        }''', {'key': storage_key, 'value': second})
        self.page.locator('[data-household]').wait_for()
        self.api.release_refresh.set()
        self.page.wait_for_timeout(120)
        stored = self.page.evaluate('(key)=>JSON.parse(localStorage.getItem(key))', storage_key)
        self.assertEqual(stored['user']['email'], 'second@example.invalid')
        self.assertIn('second@example.invalid', self.page.locator('#account-actions').inner_text())
        self.assertEqual(self.page.locator('#auth-submit').count(), 0)

    def test_late_login_cannot_replace_newer_explicit_login(self):
        self.api.families = [family()]
        self.api.delay_login_email = 'first@example.invalid'
        self.page.goto(self.base)
        self.login('first@example.invalid')
        self.page.locator('#auth-signup').click()
        self.page.locator('#auth-login').click()
        self.login('second@example.invalid')
        self.page.locator('[data-household]').wait_for()
        self.assertTrue(self.api.login_started.is_set())
        self.api.release_login.set()
        self.page.wait_for_timeout(120)
        stored = self.page.evaluate('(key)=>JSON.parse(localStorage.getItem(key))', 'finance.auth.v1:' + PROJECT)
        self.assertEqual(stored['user']['email'], 'second@example.invalid')

    def test_owner_settings_invite_delivery_revoke_and_roles(self):
        self.signed_in()
        self.open_settings()
        self.page.locator('#settings-name').fill('Новое название')
        self.page.locator('#settings-people-add').click()
        self.page.locator('#settings-people-0').fill('Лена')
        self.page.locator('#settings-people-add').click()
        self.page.locator('#settings-people-1').fill('Иван')
        self.page.locator('#settings-categories-add').click()
        self.page.locator('#settings-categories-0').fill('Дом')
        self.page.locator('#settings-save').click()
        self.page.wait_for_function('()=>document.querySelector(".family-title h1")?.textContent === "Новое название"')
        self.page.locator('#invite-email').wait_for()
        self.assertEqual([item['name'] for item in self.api.families[0]['settings']['people']], ['Лена', 'Иван'])
        self.page.locator('#invite-email').fill('invited@example.invalid')
        self.page.locator('#invite-role').select_option('viewer')
        self.page.locator('#invite-send').click()
        self.page.locator('.invite-list .invite-row').wait_for()
        self.assertIn('не принял письмо', self.page.locator('.invite-list').inner_text())
        self.assertNotIn('письмо доставлено', self.page.locator('.invite-list').inner_text().lower())
        self.api.invites[0]['mail_status'] = 'sent'
        self.page.locator('#invite-refresh').click()
        self.page.wait_for_function('()=>document.querySelector(".invite-list").textContent.includes("Провайдер принял письмо")')
        self.page.get_by_role('button', name='Отозвать приглашение invited@example.invalid').click()
        self.page.get_by_role('button', name='Отозвать приглашение invited@example.invalid').wait_for(state='detached')
        self.assertIn('отозвано', self.page.locator('.invite-list').inner_text())
        self.page.get_by_role('combobox', name='Роль участника editor@example.invalid').select_option('viewer')
        self.page.wait_for_function('()=>document.querySelector(".member-controls select").disabled === false')
        self.assertEqual(self.api.members[1]['role'], 'viewer')
        self.page.get_by_role('button', name='Удалить участника editor@example.invalid').click()
        self.page.wait_for_function('()=>document.querySelectorAll(".member-row").length === 1')

    def test_catalog_rename_and_archive_preserve_identity(self):
        catalog_id = '11111111-1111-4111-8111-111111111111'
        home = family()
        home['settings']['people'] = [{'id': catalog_id, 'name': 'Первое имя', 'archived': False}]
        self.signed_in([home])
        self.open_settings()
        self.page.locator('#settings-people-0').fill('Новое имя')
        self.page.get_by_role('button', name='В архив: Первое имя').click()
        self.page.locator('#settings-save').click()
        self.page.locator('#settings-people-0').wait_for(state='attached')
        self.page.wait_for_function('()=>document.querySelector("#settings-people-0")?.disabled === true')
        value = self.api.families[0]['settings']['people'][0]
        self.assertEqual(value, {'id': catalog_id, 'name': 'Новое имя', 'archived': True})

    def test_long_names_and_forms_fit_four_viewports(self):
        self.signed_in([family(name=LONG_NAME), family('two', name='Ещё одна семья')])
        self.api.members[1]['email'] = 'оченьдлинныйадрес' * 7 + '@example.invalid'
        self.api.invites = [{'id': 'long', 'email': 'длинныйадрес' * 12 + '@example.invalid', 'role': 'editor', 'status': 'pending', 'mail_status': 'pending'}]
        for width in (320, 390, 768, 1280):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': 900})
                self.page.locator('[data-household="one"]').click()
                self.page.locator('#nav-settings').click()
                self.page.locator('#invite-email').wait_for()
                size = self.page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
                self.assertLessEqual(size['scroll'], width + 2)
                self.page.locator('#back-to-families').click()
                self.page.locator('[data-household="one"]').wait_for()
                size = self.page.evaluate('document.documentElement.scrollWidth')
                self.assertLessEqual(size, width + 2)

    def test_public_source_has_no_untrusted_html_or_private_bootstrap(self):
        source = (ROOT / 'public' / 'accounts.js').read_text()
        self.assertNotIn('innerHTML', source)
        for secret in ('9946-WZ3/00067', '1985-11-27', 'service_role', 'sb_secret_'):
            self.assertNotIn(secret, source)
        html = (ROOT / 'public' / 'index.html').read_text()
        self.assertNotIn('unsafe-eval', html)
        self.assertNotIn('unsafe-inline', html)

    def test_actual_shell_mounts_full_ledger_under_strict_parent_csp(self):
        self.api.real_ledger = True
        self.page.route('**/ledger.js', lambda route: route.fulfill(path=str(ROOT / 'public/ledger.js'), content_type='application/javascript'))
        identifier = '11111111-1111-4111-8111-111111111111'
        home = family(identifier)
        home['settings'] = {'people': [{'id': '55555555-5555-4555-8555-555555555555', 'name': 'Участник', 'archived': False}],
                            'categories': [{'id': '66666666-6666-4666-8666-666666666666', 'name': 'Дом', 'archived': False}]}
        self.signed_in([home])
        self.page.locator('[data-household]').click()
        self.page.locator('iframe.finance-ledger-frame').wait_for(state='visible')
        frame = self.page.frames[-1]
        frame.wait_for_function('()=>!document.getElementById("appRoot").classList.contains("auth-locked")')
        self.assertEqual(frame.evaluate('state.entries.length'), 0)
        frame.evaluate('''()=>{go('today');document.getElementById('eAmount').value='12,34';document.getElementById('eCategory').value='Дом';document.getElementById('eBeneficiary').value='Участник';return addEntry()}''')
        self.assertEqual(frame.evaluate('sum(state.entries)'), 12.34)
        self.assertEqual(self.api.financial[identifier]['data']['entries'][0]['category_id'], '66666666-6666-4666-8666-666666666666')
        for width in (320, 390, 768, 1280):
            self.page.set_viewport_size({'width': width, 'height': 900})
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 2)
        self.page.locator('#nav-settings').click()
        self.page.locator('#settings-people-0').wait_for()
        self.assertEqual(self.page.locator('#settings-people-0').input_value(), 'Участник')
        self.assertEqual(frame.evaluate('state.entries.length'), 1)


if __name__ == '__main__':
    unittest.main()
