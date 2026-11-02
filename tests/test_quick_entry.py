"""Family-created favorites and explicit Repeat drafts, synthetic browser fixtures only."""
import json
from copy import deepcopy
import unittest

import test_local_data_safety as harness
import test_sync_protocol as protocol


class QuickEntry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    def setUp(self):
        self.context=self.browser.new_context(timezone_id='Europe/Moscow',service_workers='block')
        self.context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(self.base) else route.abort())
        self.page=self.context.new_page();self.page.set_default_timeout(4000)
        self.accept_dialogs=True
        self.page.on('dialog',lambda dialog:dialog.accept() if self.accept_dialogs else dialog.dismiss())

    tearDown=harness.LocalDataSafety.tearDown
    open=harness.LocalDataSafety.open
    snapshot=harness.LocalDataSafety.snapshot

    def prepare(self):
        self.open()
        self.page.evaluate("""() => {
          session=null;stopCloudSync();localStorage.clear();state=blankState();
          const row=(id,category='Продукты')=>({id,type:'expense',amount:1250.50,
            date:'2025-02-02',category,subcategory:'Учебное уточнение',
            beneficiary:'Вымышленная получательница',who:'Старый участник',
            store:'Учебный магазин '+id,pay:'Учебная оплата',comment:'Учебная покупка',
            created_at:'2025-02-02T00:00:00Z',updated_at:'2025-02-02T00:00:00Z',
            futureField:{mustRemain:[1,null,true]},futureLinkId:'do-not-copy'});
          state.entries=[row('first'),row('second','ЖКХ')];
          state.intelligence.templates={oldNames:['Не менять'],unknownFuture:[null,8]};
          showApp();renderAll();clearEntry();go('history');
          document.getElementById('fMonth').value='';renderHistory();
        }""")
        self.before=self.snapshot()

    def rows(self):
        return self.page.evaluate('JSON.stringify(state.entries)')

    def add_favorite(self,name='Учебный обед',source='first'):
        self.page.evaluate('id=>v97SaveFavoriteFromEntry(id)',source)
        self.page.locator('#v97FavoriteName').fill(name)
        self.page.locator('#v97FavoriteEditor button[type="submit"]').click()
        self.page.wait_for_function('!v97FavoriteSaving')
        return self.page.evaluate('v97FavoriteRows().at(-1).id')

    def test_repeat_history_is_new_today_draft_no_writes_until_explicit_save(self):
        self.prepare()
        first=self.page.locator('#historyBody tr').filter(has_text='Учебный магазин first')
        first.get_by_role('button',name='Повторить',exact=True).click()
        self.assertEqual(self.snapshot(),self.before)
        self.assertEqual(self.page.locator('#eDate').input_value(),self.page.evaluate('today()'))
        self.assertEqual(self.page.locator('#eAmount').input_value(),'1250,5')
        self.assertEqual(self.page.locator('#eBeneficiary').input_value(),'Вымышленная получательница')
        self.assertEqual(self.page.locator('#eSubcategory').input_value(),'Учебное уточнение')
        self.assertEqual(self.page.locator('#ePay').input_value(),'Учебная оплата')
        self.assertIn('новый черновик',self.page.locator('#v97DraftStatus').inner_text())
        self.page.locator('#v90Save').click();self.page.wait_for_function('!v90Saving')
        rows=self.page.evaluate('state.entries')
        self.assertEqual(len(rows),3);fresh=rows[-1]
        self.assertNotIn(fresh['id'],['first','second']);self.assertEqual(fresh['date'],self.page.evaluate('today()'))
        self.assertEqual(fresh['amount'],1250.5)
        self.assertNotIn('futureField',fresh);self.assertNotIn('futureLinkId',fresh)
        self.assertEqual(rows[:2],json.loads(self.before['state'])['entries'])
        for key in ['paymentKey','installmentId','installmentPartId','recurringId','recurringPeriod','scheduledDate','debtRepayment','accountingMode','mortgagePayment','obligationType']:
            self.assertNotIn(key,fresh)

    def test_populated_today_actions_wrap_without_overflow_on_compact_phone(self):
        self.prepare();self.page.set_viewport_size({'width':320,'height':900})
        self.page.evaluate("""() => {
          for(const entry of state.entries)entry.date=today();renderAll();go('today');go('home');go('today');
        }""")
        before=self.snapshot()
        self.assertEqual(self.page.locator('#todayList .v91-transaction').count(),2)
        self.assertEqual(self.page.locator('#todayList .v91-row-actions button').count(),8)
        sizes=self.page.evaluate("""() => ({viewport:innerWidth,width:document.body.scrollWidth,
          right:Math.max(...[...document.querySelectorAll('#todayList .v91-row-actions button')].map(button=>button.getBoundingClientRect().right))})""")
        self.assertLessEqual(sizes['width'],sizes['viewport'])
        self.assertLessEqual(sizes['right'],sizes['viewport'])
        self.assertEqual(self.snapshot(),before)

    def test_missing_payment_accounts_never_inherit_previous_draft_values(self):
        self.prepare()
        self.page.evaluate("""() => {
          delete state.entries[0].pay;document.getElementById('ePay').value='Наличные';
          clearEntry();v97RepeatEntry('first');
        }""")
        self.assertEqual(self.page.locator('#ePay').input_value(),'')
        self.page.evaluate("""() => {
          state.entries[1].type='transfer';delete state.entries[1].from;delete state.entries[1].to;
          document.getElementById('eFrom').value='Карта';document.getElementById('eTo').value='Накопления';
          clearEntry();v97RepeatEntry('second');
        }""")
        self.assertEqual(self.page.locator('#eFrom').input_value(),'')
        self.assertEqual(self.page.locator('#eTo').input_value(),'')
        self.assertEqual(self.snapshot()['storage'],self.before['storage'])

    def test_same_amount_repeat_uses_actual_id_and_preserves_legacy_fields(self):
        self.prepare()
        self.page.evaluate("state.entries[1].category='Категория прежней версии';state.entries[1].comment='Именно вторая';renderHistory()")
        before=self.snapshot()
        second=self.page.locator('#historyBody tr').filter(has_text='Учебный магазин second')
        second.get_by_role('button',name='Повторить',exact=True).click()
        self.assertEqual(self.page.locator('#eCategory').input_value(),'Категория прежней версии')
        self.assertEqual(self.page.locator('#eComment').input_value(),'Именно вторая')
        self.assertEqual(self.snapshot(),before)

    def test_dirty_draft_cancel_keeps_every_field_and_inflight_save_blocks_prefill(self):
        self.prepare()
        self.page.evaluate("openEntry();document.getElementById('eAmount').value='17,25';document.getElementById('eComment').value='Несохранённое'")
        before=self.page.evaluate('v97DraftFields()')
        self.accept_dialogs=False
        self.assertFalse(self.page.evaluate("v97RepeatEntry('second')"))
        self.assertEqual(self.page.evaluate('v97DraftFields()'),before)
        self.page.evaluate('v90Saving=true')
        self.assertFalse(self.page.evaluate("v97RepeatEntry('first')"))
        self.assertFalse(self.page.evaluate("v97SaveFavoriteFromEntry('first')"))
        self.assertEqual(self.page.evaluate('v97DraftFields()'),before)
        self.assertIn('Дождитесь',self.page.locator('#v97DraftStatus').inner_text())
        self.assertEqual(self.snapshot(),self.before)

    def test_linked_debt_and_recurring_payments_refuse_repeat_and_favorite_without_any_mutation(self):
        self.prepare();self.accept_dialogs=False
        for fields in [{'installmentId':'plan','installmentPartId':'part'}, {'recurringId':'rent','recurringPeriod':'2025-02'},
                       {'mortgagePayment':True},{'paymentKey':'auto-key'},{'debtRepayment':True}, {'category':'Кредит'}]:
            with self.subTest(fields=fields):
                self.page.evaluate("fields=>{Object.assign(state.entries[0],fields);clearEntry()}",fields)
                before=self.snapshot();draft=self.page.evaluate('v97DraftFields()')
                self.assertFalse(self.page.evaluate("v97RepeatEntry('first')"))
                self.assertFalse(self.page.evaluate("v97SaveFavoriteFromEntry('first')"))
                self.assertEqual(self.snapshot(),before);self.assertEqual(self.page.evaluate('v97DraftFields()'),draft)
                self.assertFalse(self.page.locator('#v97FavoriteEditor').is_visible())
                self.page.evaluate('value=>state.entries[0]=value',json.loads(self.before['state'])['entries'][0])

    def test_family_favorite_create_open_rename_remove_roundtrip_preserves_finance_and_unknown_extensions(self):
        self.prepare();rows=self.rows();identifier=self.add_favorite()
        self.assertEqual(self.rows(),rows)
        saved=self.page.evaluate('JSON.parse(localStorage.getItem(KEYS.pending))')
        self.assertEqual(saved['intelligence']['favorites'][0]['id'],identifier)
        self.assertEqual(saved['intelligence']['templates'],json.loads(self.before['state'])['intelligence']['templates'])
        self.page.evaluate("id=>{v97FindFavorite(id).futureFavorite={untouched:[1,null]};clearEntry();v97OpenFavorite(id)}",identifier)
        self.assertEqual(self.rows(),rows);self.assertEqual(self.page.locator('#eDate').input_value(),self.page.evaluate('today()'))
        self.assertEqual(self.page.locator('#eAmount').input_value(),'1250,5')
        self.page.evaluate('id=>v97RenameFavorite(id)',identifier)
        self.page.locator('#v97FavoriteName').fill('Новое учебное имя')
        self.page.locator('#v97FavoriteEditor button[type="submit"]').click();self.page.wait_for_function('!v97FavoriteSaving')
        self.assertEqual(self.page.evaluate('id=>v97FindFavorite(id).futureFavorite',identifier),{'untouched':[1,None]})
        self.assertIn('Новое учебное имя',self.page.locator('#v97FavoriteList').inner_text())
        self.page.evaluate('id=>v97RemoveFavorite(id)',identifier)
        self.assertEqual(self.page.evaluate('v97FavoriteRows().length'),0)
        self.assertTrue(self.page.evaluate('id=>Boolean(state.intelligence.deleted.favorites[id])',identifier))
        self.assertEqual(self.rows(),rows)
        self.page.reload(wait_until='domcontentloaded');self.page.wait_for_function("typeof state==='object'")
        self.assertEqual(self.page.evaluate('state.entries.length'),2)
        self.assertEqual(self.page.evaluate('v97FavoriteRows().length'),0)
        self.assertTrue(self.page.evaluate('id=>Boolean(state.intelligence.deleted.favorites[id])',identifier))

    def test_favorite_from_form_saves_only_preset_and_copy_open_never_autosaves(self):
        self.prepare();rows=self.rows()
        self.page.evaluate("openEntry('income');document.getElementById('eAmount').value='0,30';document.getElementById('eIncomeSource').value='Учебный источник';document.getElementById('eWho').value='Сергей';v97SaveFavoriteFromForm()")
        self.assertEqual(self.snapshot(),self.before)
        self.page.locator('#v97FavoriteName').fill('Учебное поступление');self.page.locator('#v97FavoriteEditor button[type="submit"]').click()
        self.page.wait_for_function('!v97FavoriteSaving')
        self.page.evaluate('clearEntry();v97OpenFavorite(v97FavoriteRows()[0].id)')
        self.assertEqual(self.page.locator('#eType').input_value(),'income')
        self.assertEqual(self.page.locator('#eAmount').input_value(),'0,3')
        self.assertEqual(self.page.locator('#eIncomeSource').input_value(),'Учебный источник')
        self.assertEqual(self.rows(),rows)

    def test_quota_failure_is_honest_preserves_editor_and_retry_does_not_duplicate(self):
        self.prepare();rows=self.rows()
        self.page.evaluate("""() => {window.__setItem=Storage.prototype.setItem;Storage.prototype.setItem=function(k,v){if(k===KEYS.pending)throw new DOMException('fictional quota','QuotaExceededError');return window.__setItem.call(this,k,v)}}""")
        identifier=self.add_favorite('Учебный резерв')
        self.assertTrue(self.page.locator('#v97FavoriteEditor').is_visible())
        self.assertIn('не сохранено надёжно',self.page.locator('#v97FavoriteEditorStatus').inner_text())
        self.assertNotIn('сохранено в облако',self.page.locator('#v97FavoritesStatus').inner_text().lower())
        self.assertEqual(self.rows(),rows)
        self.page.evaluate('() => {Storage.prototype.setItem=window.__setItem}')
        self.page.locator('#v97FavoriteEditor button[type="submit"]').click();self.page.wait_for_function('!v97FavoriteSaving')
        self.assertEqual(self.page.evaluate('v97FavoriteRows().length'),1)
        self.assertEqual(self.page.evaluate('v97FavoriteRows()[0].id'),identifier)
        self.assertFalse(self.page.locator('#v97FavoriteEditor').is_visible())

    def test_logout_blocks_actions_and_late_favorite_save_cannot_reopen_or_show_success(self):
        self.prepare();self.page.evaluate("() => {v97SaveFavoriteFromEntry('first');document.getElementById('v97FavoriteName').value='Учебное';window.__realSaveAll=saveAll;saveAll=()=>new Promise(resolve=>window.__favoriteResolve=resolve);v97SubmitFavoriteEditor();}")
        self.page.evaluate("logout();document.getElementById('gateEmail').focus();window.__favoriteResolve(true)")
        self.page.wait_for_function('!v97FavoriteSaving')
        after=self.snapshot()
        self.assertFalse(self.page.locator('#v97FavoriteEditor').is_visible())
        self.assertEqual(self.page.locator('#v97FavoriteName').input_value(),'')
        self.assertEqual(self.page.locator('#v97FavoritesStatus').inner_text(),'')
        self.assertFalse(self.page.evaluate("v97RepeatEntry('first')"))
        self.assertFalse(self.page.evaluate("v97OpenFavorite(v97FavoriteRows()[0].id)"))
        self.assertFalse(self.page.evaluate("v97SaveFavoriteFromEntry('second')"))
        self.assertEqual(self.page.evaluate('document.activeElement.id'),'gateEmail')
        self.assertEqual(self.snapshot(),after)

    def test_same_base_independent_favorite_additions_merge_as_rows_and_ack_needs_favorites(self):
        self.prepare()
        result=self.page.evaluate("""() => {
          const base=normalize(state),remote=normalize(base),local=normalize(base);
          const favorite=id=>({id,name:'Учебное '+id,type:'expense',amount:0.10,
            category:'Продукты',updated_at:'2026-10-01T00:00:00Z',future:{keep:id}});
          remote.intelligence.favorites=[favorite('remote')];local.intelligence.favorites=[favorite('local')];
          rememberCloudBase(base);const merged=reconcileCloudSnapshot(remote,local,'fictional favorite adds');
          return {merged,conflicts:reconcileCloudSnapshot.conflicts,
            missingAccepted:verifiedCloudContains(base,local),completeAccepted:verifiedCloudContains(merged,local)};
        }""")
        self.assertEqual(result['conflicts'],[])
        self.assertEqual({r['id'] for r in result['merged']['intelligence']['favorites']},{'remote','local'})
        self.assertFalse(result['missingAccepted']);self.assertTrue(result['completeAccepted'])
        self.assertEqual(result['merged']['entries'],json.loads(self.before['state'])['entries'])

    def test_edit_delete_conflicts_even_with_clock_skew_and_original_queue_is_not_discarded(self):
        self.prepare()
        result=self.page.evaluate("""() => {
          const base=normalize(state);base.intelligence.favorites=[{id:'favorite',name:'Исходное',type:'expense',amount:1,category:'Продукты',updated_at:'2099-01-01T00:00:00Z',future:{keep:true}}];
          const remote=normalize(base),local=normalize(base);remote.intelligence.favorites[0].name='Удалённое редактирование';remote.intelligence.favorites[0].updated_at='2100-01-01T00:00:00Z';
          local.intelligence.favorites=[];local.intelligence.deleted.favorites.favorite='2020-01-01T00:00:00Z';
          localStorage.setItem(KEYS.pending,JSON.stringify(local));rememberCloudBase(base);
          const merged=reconcileCloudSnapshot(remote,local,'fictional favorite edit/delete');
          return {merged,conflicts:reconcileCloudSnapshot.conflicts,pending:JSON.parse(localStorage.getItem(KEYS.pending)),packet:JSON.parse(localStorage.getItem(CLOUD_CONFLICT_KEY))};
        }""")
        self.assertIsNone(result['merged']);self.assertIn('intelligence_favorites:favorite',result['conflicts'])
        self.assertEqual(result['pending']['intelligence']['favorites'],[])
        self.assertEqual(result['packet']['cloud']['intelligence']['favorites'][0]['name'],'Удалённое редактирование')
        self.assertEqual(result['packet']['local']['intelligence']['deleted']['favorites']['favorite'],'2020-01-01T00:00:00Z')

    def test_deleted_favorite_is_not_resurrected_by_import_with_future_clock(self):
        self.prepare()
        result=self.page.evaluate("""() => {
          const stale=normalize(state),deleted=normalize(state);
          stale.intelligence.favorites=[{id:'gone',name:'Старое',type:'expense',amount:1,category:'Продукты',updated_at:'2099-01-01T00:00:00Z'}];
          deleted.intelligence.deleted.favorites.gone='2020-01-01T00:00:00Z';
          return mergeStates(stale,deleted);
        }""")
        self.assertEqual(result['intelligence']['favorites'],[])
        self.assertEqual(result['intelligence']['deleted']['favorites']['gone'],'2020-01-01T00:00:00Z')
        self.assertEqual(result['entries'],json.loads(self.before['state'])['entries'])

    def test_unrelated_remote_favorite_edit_and_local_delete_merge_without_touching_other_rows(self):
        self.prepare()
        result=self.page.evaluate("""() => {
          const base=normalize(state);base.intelligence.favorites=['keep','remove'].map(id=>({id,name:id,type:'expense',amount:1,category:'Продукты',updated_at:'2099-01-01T00:00:00Z',future:{keep:true}}));
          const remote=normalize(base),local=normalize(base);remote.intelligence.favorites[0].name='Изменённое';remote.intelligence.favorites[0].updated_at='2020-01-01T00:00:00Z';
          local.intelligence.favorites=local.intelligence.favorites.filter(r=>r.id!=='remove');local.intelligence.deleted.favorites.remove='2010-01-01T00:00:00Z';
          rememberCloudBase(base);return reconcileCloudSnapshot(remote,local,'fictional independent edit/delete');
        }""")
        self.assertEqual([r['id'] for r in result['intelligence']['favorites']],['keep'])
        self.assertEqual(result['intelligence']['favorites'][0]['name'],'Изменённое')
        self.assertEqual(result['intelligence']['favorites'][0]['future'],{'keep':True})
        self.assertIn('remove',result['intelligence']['deleted']['favorites'])

    def test_malicious_ids_names_are_data_and_favorite_limit_never_truncates_existing_rows(self):
        self.prepare()
        malicious='id\" onclick=\"window.__injected=true\" <x>'
        self.page.evaluate("""id=>{state.entries[0].id=id;state.entries[0].store='<img src=x onerror=window.__injected=true>';renderHistory()}""",malicious)
        self.page.locator('#historyBody tr').filter(has_text='<img src=x').get_by_role('button',name='Повторить',exact=True).click()
        self.assertEqual(self.page.locator('#eStore').input_value(),'<img src=x onerror=window.__injected=true>')
        self.assertFalse(self.page.evaluate('Boolean(window.__injected)'))
        self.page.evaluate("""() => {state.intelligence.favorites=Array.from({length:31},(_,i)=>({id:'fav-'+i,name:'Учебное '+i,type:'expense',amount:1,category:'Продукты'}));v97RenderFavorites();clearEntry()}""")
        before=self.snapshot()
        self.assertFalse(self.page.evaluate('id=>v97SaveFavoriteFromEntry(id)',malicious))
        self.assertEqual(self.page.evaluate('v97FavoriteRows().length'),31);self.assertEqual(self.snapshot(),before)
        for width in [320,390,1280]:
            self.page.set_viewport_size({'width':width,'height':900})
            self.page.evaluate('go("today")')
            self.assertTrue(self.page.locator('#v97Favorites').is_visible())
            self.assertLessEqual(self.page.locator('#v97Favorites').evaluate('el=>el.getBoundingClientRect().right'),width+1)


    def test_long_favorite_names_and_touch_controls_fit_compact_screens(self):
        for width in (320,390,768,1280):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width':width,'height':844})
                self.prepare()
                identifier=self.add_favorite('Д'*40)
                result=self.page.evaluate("""id=>{
                  go('home');renderAll();
                  const chip=document.querySelector('#v97HomeFavorites [data-record-action="favorite-open"]');
                  const card=document.getElementById('v97HomeFavorites').getBoundingClientRect(),box=chip.getBoundingClientRect();
                  const chipFits=box.left>=card.left&&box.right<=card.right&&chip.scrollWidth<=chip.clientWidth+2;
                  v97RenameFavorite(id);
                  const input=document.getElementById('v97FavoriteName').getBoundingClientRect();
                  const editor=document.getElementById('v97FavoriteEditor').getBoundingClientRect();
                  const heights=[...document.querySelectorAll('#v97Favorites button,#v97HomeFavorites button')].filter(b=>b.getBoundingClientRect().width&&b.getBoundingClientRect().height).map(b=>b.getBoundingClientRect().height);
                  return {chipFits,heights,inputHeight:input.height,inputFits:input.left>=editor.left&&input.right<=editor.right};
                }""",identifier)
                self.assertTrue(result['chipFits'])
                self.assertTrue(result['inputFits'])
                self.assertGreaterEqual(result['inputHeight'],44)
                self.assertTrue(result['heights'] and all(height>=44 for height in result['heights']))


class QuickEntryCAS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        protocol.SyncProtocol.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        protocol.SyncProtocol.tearDownClass.__func__(cls)

    setUp=protocol.SyncProtocol.setUp
    tearDown=protocol.SyncProtocol.tearDown
    device=protocol.SyncProtocol.device
    start=protocol.SyncProtocol.start
    finish=protocol.SyncProtocol.finish
    wait_held=protocol.SyncProtocol.wait_held
    pending=protocol.SyncProtocol.pending
    assert_no_legacy_write=protocol.SyncProtocol.assert_no_legacy_write
    concurrent_push=protocol.SyncProtocol.concurrent_push

    def test_two_devices_concurrent_favorite_additions_survive_real_cas_retry(self):
        base=protocol.fixture()
        base['entries']=[protocol.entry('financial-history',futureField={'preserve':True})]
        self.backend.data=deepcopy(base)
        first,second=self.device(base),self.device(base)
        for page,identifier in [(first,'device-a-favorite'),(second,'device-b-favorite')]:
            page.evaluate("""id=>{state.intelligence.favorites=[{id,name:'Учебное '+id,type:'expense',amount:17.25,category:'Продукты',updated_at:'2026-10-21T12:00:00Z',future:{keep:id}}];savePendingLocal()}""",identifier)
        self.concurrent_push(first,second)
        self.assertEqual({row['id'] for row in self.backend.data['intelligence']['favorites']},{'device-a-favorite','device-b-favorite'})
        self.assertEqual(self.backend.data['entries'],base['entries'])
        self.assertGreaterEqual(len(self.backend.calls),3)
        self.assertEqual(self.backend.revision,2)

    def test_two_devices_edit_delete_conflict_retains_deleted_favorite_queue_with_slow_clock(self):
        base=protocol.fixture();base['entries']=[protocol.entry('history')]
        base['intelligence']['favorites']=[{'id':'shared-favorite','name':'Исходное','type':'expense','amount':1,'category':'Продукты','updated_at':'2026-10-21T12:00:00Z','future':{'keep':True}}]
        self.backend.data=deepcopy(base)
        editing,deleting=self.device(base),self.device(base)
        editing.evaluate("state.intelligence.favorites[0].name='Изменено';state.intelligence.favorites[0].updated_at='2099-01-01T00:00:00Z';savePendingLocal()")
        deleting.evaluate("state.intelligence.favorites=[];state.intelligence.deleted.favorites['shared-favorite']='2000-01-01T00:00:00Z';savePendingLocal()")
        self.assertTrue(editing.evaluate('pushCloud()'))
        self.assertFalse(deleting.evaluate('pushCloud()'))
        self.assertEqual(self.backend.data['intelligence']['favorites'][0]['name'],'Изменено')
        self.assertEqual(self.backend.data['entries'],base['entries'])
        before=self.pending(deleting)
        self.assertIn('shared-favorite',before['intelligence']['deleted']['favorites'])
        self.assertIn('Конфликт',deleting.locator('#syncStatus').inner_text())
        deleting.reload();deleting.wait_for_function("typeof state==='object'")
        self.assertEqual(self.pending(deleting),before)
        self.assert_no_legacy_write()


if __name__=='__main__':
    unittest.main()
