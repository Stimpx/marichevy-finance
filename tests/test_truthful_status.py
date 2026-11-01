"""Read-only, evidence-based status presentation; fictional data and blocked network."""
import unittest

import test_local_data_safety as harness


class TruthfulStatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open
    snapshot = harness.LocalDataSafety.snapshot

    def prepare(self):
        self.open()
        self.page.evaluate("""() => {
          session=null;stopCloudSync();localStorage.clear();state=blankState();
          v89StorageFailed=false;localRecoveryBlocked=false;
          state.entries=[{id:'fictional-first',date:today(),type:'expense',amount:17.25,
            category:'Продукты',who:'Сергей',beneficiary:'Сергей',store:'Учебный магазин',
            updated_at:'2026-10-21T00:00:00Z',futureField:{keep:[true,null,'original']}},
            {id:'fictional-other',date:today(),type:'income',amount:40.5,category:'Доход',
             who:'Виктория',store:'Учебный источник',updated_at:'2026-10-21T00:00:00Z'}];
          state.boardItems=[{id:'fictional-board',type:'message',text:'Учебная заметка',
            author:'Учебный участник',created_at:'2026-10-21T00:00:00Z',
            updated_at:'2026-10-21T00:00:00Z',futureField:{keep:'original'}}];
          state.futureTop={preserve:[true,null,'fictional']};
          telegramNotify=()=>Promise.resolve(false);
          window.__telegramCalls=[];
          sendTelegramMessage=async (...args)=>{__telegramCalls.push(args);return {ok:true}};
          weatherCache={at:Date.now(),source:'Open-Meteo',data:{temperature_2m:4,weather_code:0}};
          showApp();renderAll();go('home');
        }""")

    def test_signed_out_and_configuration_alone_never_claim_family_saved(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          rememberCloudBase(state);localStorage.removeItem(KEYS.pending);
          v120RenderTruthStatus();return {global:v120SyncSummary(),
            row:v120RecordSyncStatus('entries','fictional-first'),
            header:document.getElementById('v120BoardSync').textContent,
            clockLive:document.getElementById('liveClock').getAttribute('aria-live')};
        }""")
        self.assertEqual(result['global']['kind'], 'local')
        self.assertEqual(result['row']['kind'], 'local')
        self.assertEqual(result['header'], 'На этом устройстве')
        self.assertIsNone(result['clockLive'])

    def test_verified_record_can_be_saved_while_a_different_record_is_pending(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          session={access_token:'fictional-only'};rememberCloudBase(state);
          localStorage.removeItem(KEYS.pending);
          const initial=v120SyncSummary();
          state.entries[0].comment='Несохранённое изменение';
          const memory=v120RecordSyncStatus('entries','fictional-first');
          savePendingLocal();
          return {initial,memory,global:v120SyncSummary(),
            edited:v120RecordSyncStatus('entries','fictional-first'),
            other:v120RecordSyncStatus('entries','fictional-other')};
        }""")
        self.assertEqual(result['initial']['kind'], 'saved')
        self.assertEqual(result['memory']['kind'], 'local')
        self.assertEqual(result['global']['kind'], 'pending')
        self.assertEqual(result['edited']['label'], 'Ждёт отправки')
        self.assertEqual(result['other']['label'], 'Сохранено в семье')

    def test_storage_recovery_and_malformed_copies_take_priority_over_success(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          session={access_token:'fictional-only'};rememberCloudBase(state);
          v89StorageFailed=true;const storage=v120SyncSummary();v89StorageFailed=false;
          localRecoveryBlocked=true;const recovery=v120SyncSummary();localRecoveryBlocked=false;
          localStorage.setItem(KEYS.pending,'{broken');const corruptQueue=v120SyncSummary();
          localStorage.removeItem(KEYS.pending);
          localStorage.setItem(CLOUD_BASE_KEY,JSON.stringify({household:'another-family',url:CONFIG.url,data:state}));
          const foreign=v120SyncSummary();
          return {storage,recovery,corruptQueue,foreign};
        }""")
        for name, status in result.items():
            self.assertEqual(status['kind'], 'error', name)
            self.assertNotEqual(status['label'], 'Сохранено в семье', name)

    def test_status_rendering_is_read_only_and_handles_invalid_or_future_check_dates(self):
        self.prepare()
        self.page.evaluate("""() => {
          session={access_token:'fictional-only'};rememberCloudBase(state);savePendingLocal();
          localStorage.setItem('marichevy_v75_last_sync','not-a-date');
          window.__statusWrites=0;const original=Storage.prototype.setItem;
          Storage.prototype.setItem=function(...args){__statusWrites++;return original.apply(this,args)};
        }""")
        before = self.snapshot()
        result = self.page.evaluate("""() => {
          for(let n=0;n<5;n++){v120RenderTruthStatus();v120SyncSummary();
            v120RecordSyncStatus('entries','fictional-first');}
          return {writes:__statusWrites,verifiedAt:v120SyncSummary().verifiedAt,
            unknown:v120RecordSyncStatus('unknown','x'),missing:v120RecordSyncStatus('entries','missing')};
        }""")
        self.assertEqual(result['writes'], 0)
        self.assertEqual(result['verifiedAt'], '')
        self.assertEqual(result['unknown']['kind'], 'unverified')
        self.assertEqual(result['missing']['kind'], 'unverified')
        self.assertEqual(self.snapshot(), before)
        self.page.evaluate("localStorage.setItem('marichevy_v75_last_sync',new Date(Date.now()+86400000).toISOString())")
        self.assertEqual(self.page.evaluate('v120SyncSummary().verifiedAt'), '')

    def test_unknown_record_fields_require_exact_verified_content(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          session={access_token:'fictional-only'};rememberCloudBase(state);
          const initial=v120RecordSyncStatus('entries','fictional-first');
          state.entries[0].futureField.keep.push('new');
          const changed=v120RecordSyncStatus('entries','fictional-first');
          savePendingLocal();const queued=v120RecordSyncStatus('entries','fictional-first');
          return {initial,changed,queued,extension:state.entries[0].futureField};
        }""")
        self.assertEqual(result['initial']['kind'], 'saved')
        self.assertEqual(result['changed']['kind'], 'local')
        self.assertEqual(result['queued']['kind'], 'pending')
        self.assertEqual(result['extension']['keep'], [True, None, 'original', 'new'])

    def test_newer_remote_timestamp_does_not_confirm_different_local_content(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          session={access_token:'fictional-only'};
          const remote=JSON.parse(JSON.stringify(state));
          remote.entries[0].comment='Другая версия семейной записи';
          remote.entries[0].updated_at='2026-10-22T00:00:00Z';
          rememberCloudBase(remote);localStorage.removeItem(KEYS.pending);
          return {global:v120SyncSummary(),row:v120RecordSyncStatus('entries','fictional-first')};
        }""")
        self.assertEqual(result['global']['kind'], 'unverified')
        self.assertEqual(result['row']['kind'], 'local')

    def test_board_status_updates_after_actual_confirmation_and_keeps_records(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          session={access_token:'fictional-only'};savePendingLocal();renderFamilyBoard();
          const before=JSON.stringify(state),pending=document.querySelector('[data-v120-sync-id="fictional-board"]').textContent;
          rememberCloudBase(state);localStorage.removeItem(KEYS.pending);updateSync('Синхронизировано');
          return {pending,saved:document.querySelector('[data-v120-sync-id="fictional-board"]').textContent,
            headline:document.getElementById('v120BoardSync').textContent,
            kind:document.getElementById('syncStatus').dataset.kind,
            unchanged:before===JSON.stringify(state)};
        }""")
        self.assertEqual(result['pending'], 'Ждёт отправки')
        self.assertEqual(result['saved'], 'Сохранено в семье')
        self.assertEqual(result['headline'], 'Сохранено в семье')
        self.assertEqual(result['kind'], 'saved')
        self.assertTrue(result['unchanged'])

    def test_enabled_telegram_preferences_do_not_claim_test_or_schedule_delivery(self):
        self.prepare()
        before = self.page.evaluate('JSON.parse(JSON.stringify(state))')
        result = self.page.evaluate("""() => {
          state.settings.notifications={...state.settings.notifications,enabled:true,
            sergey:true,victoria:true,creditReminder:true,salaryReminder:true};
          renderTelegramSettings();return {global:telegramGlobalStatus.textContent,globalKind:telegramGlobalStatus.dataset.kind,
            sergey:v120TelegramStatusSergey.textContent,victoria:v120TelegramStatusVictoria.textContent,
            detail:v120TelegramDetailSergey.textContent,note:v120TelegramScheduleNote.textContent,
            sends:__telegramCalls.length};
        }""")
        self.assertEqual(result['global'], 'Отправка включена в настройках')
        self.assertEqual(result['globalKind'], 'configured')
        self.assertEqual(result['sergey'], 'Не проверено')
        self.assertEqual(result['victoria'], 'Не проверено')
        self.assertIn('ещё не проверялась', result['detail'])
        self.assertIn('расписанию проверяется отдельно', result['note'])
        self.assertEqual(result['sends'], 0)
        self.assertEqual(self.page.evaluate('state.entries'), before['entries'])

    def test_mocked_test_acknowledges_send_only_and_failure_remains_specific(self):
        self.prepare()
        before = self.snapshot()
        result = self.page.evaluate("""async () => {
          const sent=await testTelegram('sergey');
          const status=v120TelegramStatusSergey.textContent,detail=v120TelegramDetailSergey.textContent;
          sendTelegramMessage=async()=>{throw new Error('Учебный отказ сервиса')};
          const failed=await testTelegram('victoria');
          return {sent,status,detail,failed,failure:v120TelegramStatusVictoria.textContent,
            calls:__telegramCalls.length,other:v120TelegramStatusSergey.textContent};
        }""")
        self.assertTrue(result['sent'])
        self.assertEqual(result['status'], 'Тест отправлен')
        self.assertIn('прочтение не подтверждается', result['detail'])
        self.assertFalse(result['failed'])
        self.assertEqual(result['failure'], 'Тест не отправлен')
        self.assertEqual(result['other'], 'Тест отправлен')
        self.assertEqual(result['calls'], 1)
        self.assertEqual(self.snapshot(), before)

    def test_late_test_result_from_previous_session_is_not_shown_as_verified(self):
        self.prepare()
        result = self.page.evaluate("""async () => {
          sendTelegramMessage=()=>new Promise(resolve=>window.__resolveTelegram=resolve);
          const pending=testTelegram('sergey');authEpoch++;
          __resolveTelegram({ok:true});const result=await pending;
          const unknown=await testTelegram('__proto__');
          return {result,unknown,label:v120TelegramStatusSergey.textContent,detail:v120TelegramDetailSergey.textContent};
        }""")
        self.assertFalse(result['result'])
        self.assertFalse(result['unknown'])
        self.assertEqual(result['label'], 'Не проверено')
        self.assertNotIn('Сервис подтвердил', result['detail'])

    def test_legacy_health_summary_uses_facts_without_free_money_or_threshold_verdicts(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          state.entries=[{id:'fictional-income',type:'income',date:today(),amount:100,category:'Доход',who:'Сергей'},
            {id:'fictional-expense',type:'expense',date:today(),amount:20,category:'Продукты',who:'Сергей'}];
          const before=JSON.stringify(state);renderHealthDashboard();
          return {title:smartStatusTitle.textContent,flow:moneyFlow.textContent,
            unchanged:before===JSON.stringify(state)};
        }""")
        self.assertEqual(result['title'], 'Доходы и расходы за выбранный месяц')
        self.assertNotIn('Можно отложить', result['flow'])
        self.assertNotIn('под контролем', result['title'])
        self.assertIn('Остаток по истории', result['flow'])
        self.assertTrue(result['unchanged'])

    def test_advisor_gap_offers_choices_without_demanding_higher_income(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          v87AdvisorData=()=>({months:['2026-10'],provisional:false,hasIncome:true,partialIncome:false,
            monthsMissingExpenses:[],spent:90,income:100,goalMonthly:40,reserve:0,required:130,
            projectedSaving:0,byCategory:{'Продукты':90},goals:[{id:'fictional-goal'}],cut:0});
          v87RenderAdvisor();return {text:v87AdvisorGuidance.textContent,metrics:v87AdvisorMetrics.textContent,
            actions:[...v87AdvisorGuidance.querySelectorAll('button')].map(node=>node.textContent)};
        }""")
        self.assertIn('выше среднего внесённого дохода', result['text'])
        self.assertIn('30', result['text'])
        self.assertNotIn('доход должен вырасти', result['text'])
        self.assertIn('130', result['metrics'])
        self.assertIn('Открыть план месяца', result['actions'])


if __name__ == '__main__':
    unittest.main()
