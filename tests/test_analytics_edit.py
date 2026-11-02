"""Edit actual IDs from synthetic analytics drilldowns, never amount matching."""
import json
import re
import unittest

import test_local_data_safety as harness


class AnalyticsEdit(unittest.TestCase):
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

    def prepare(self, malicious=False):
        self.open()
        info=self.page.evaluate("""malicious => {
          session=null;stopCloudSync();state=blankState();localStorage.clear();
          window.__drillInjected=false;
          const m=previousMonthKey(month());
          const firstId=malicious?`x');window.__drillInjected=true;//<img id=drill-injected src=x>`:'fictional-first';
          state.entries=[
            {id:firstId,type:'expense',date:m+'-05',amount:120.50,category:'Продукты',
              beneficiary:'Сергей',who:'Legacy first',store:'Fictional first',comment:'First marker',
              futureField:{keep:[true,null,{unknown:'unchanged'}]}},
            {id:'fictional-second',type:'expense',date:m+'-06',amount:120.50,category:'Продукты',
              beneficiary:'Сергей',who:'Legacy second',store:'Fictional second',comment:'Second marker',
              futureField:{keep:'second unknown'}},
            {id:'fictional-other',type:'expense',date:m+'-07',amount:7.25,category:'ЖКХ',
              beneficiary:'Виктория',who:'Legacy other',store:'Fictional other',comment:'Other group'},
            {id:'fictional-current',type:'expense',date:month()+'-08',amount:3.01,category:'Продукты',
              beneficiary:'Сергей',who:'Legacy current',store:'Fictional current'}
          ];
          showApp();renderAll();document.getElementById('homeMonth').value=m;analyticsMonth.value=m;renderAll();go('analytics');
          return {month:m,group:expenseEntryGroup(state.entries[0]),firstId};
        }""",malicious)
        self.period=info['month'];self.group=info['group'];self.first_id=info['firstId']
        self.before=self.snapshot()

    def open_drill(self, mode='group', source='analytics'):
        if source=='home':
            self.page.evaluate("go('home')")
            if self.page.evaluate("document.getElementById('home').classList.contains('v73-focus')"):
                self.page.locator('#v73OverviewToggle').click()
        if mode=='group':
            container='#categoryLegend' if source=='home' else '#aCats'
            self.page.locator(container).get_by_role('button').filter(has_text=self.group).click()
        elif source=='home':
            self.page.locator('#familyBars').get_by_role('button').filter(has_text='Сергей').click()
        else:
            self.page.locator('#aPeopleChart').get_by_role('button').filter(has_text='Сергей').click()
        self.assertTrue(self.page.locator('#v84DrillModal').is_visible())

    def edit_first(self):
        row=self.page.locator('#v84DrillEntries .v85-drill-entry').filter(has_text='Fictional first')
        row.get_by_role('button',name=re.compile('^Изменить операцию:')).click()
        self.assertFalse(self.page.locator('#v84DrillModal').is_visible())
        self.assertTrue(self.page.locator('#editModal').is_visible())
        self.assertEqual(self.page.evaluate('editId'),self.first_id)

    def save(self):
        self.page.locator('#editModal').get_by_role('button',name='Сохранить',exact=True).click()
        self.page.wait_for_function("document.getElementById('v84DrillModal').classList.contains('open') && !document.getElementById('editModal').classList.contains('open')")
        self.page.wait_for_function("document.getElementById('v96DrillSaveStatus').textContent.length>0")

    def test_duplicate_amount_edits_exact_selected_record_and_preserves_other_rows(self):
        self.prepare();self.open_drill()
        self.assertEqual(self.page.locator('#v84DrillEntries .v85-drill-entry').count(),2)
        self.assertIn('120,50',self.page.locator('#v84DrillEntries').inner_text())
        self.edit_first()
        self.page.locator('#xAmount').fill('99,25');self.page.locator('#xComment').fill('Owner explicit edit')
        self.save()
        after=self.snapshot();old=json.loads(self.before['state']);new=json.loads(after['state'])
        self.assertEqual([e['id'] for e in new['entries']],[e['id'] for e in old['entries']])
        self.assertEqual(new['entries'][1:],old['entries'][1:])
        self.assertEqual(new['entries'][0]['amount'],99.25)
        self.assertEqual(new['entries'][0]['comment'],'Owner explicit edit')
        self.assertEqual(new['entries'][0]['who'],'Legacy first')
        self.assertEqual(new['entries'][0]['futureField'],old['entries'][0]['futureField'])
        self.assertEqual(self.page.locator('#analyticsMonth').input_value(),self.period)
        self.assertEqual(self.page.locator('#v84DrillTitle').inner_text(),self.group)
        self.assertIn('99,25',self.page.locator('#v84DrillEntries').inner_text())
        self.assertIn('Облако пока не подтвердило',self.page.locator('#v96DrillSaveStatus').inner_text())
        self.assertIsNotNone(self.page.evaluate("localStorage.getItem(KEYS.pending)"))

    def test_cancel_preserves_history_storage_and_selected_subfilter(self):
        self.prepare()
        self.page.evaluate("""() => {
          const m=previousMonthKey(month());
          for(let i=0;i<20;i++)state.entries.push({id:'fictional-scroll-'+i,type:'expense',
            date:m+'-20',amount:1.25,category:'Продукты',beneficiary:'Сергей',
            who:'Legacy scroll',store:'Fictional scroll '+i});
          renderAll();
          document.addEventListener('click',event=>{
            if(event.target.closest('[data-record-action="drill-entry-edit"]'))
              window.__expectedDrillScroll=document.querySelector('#v84DrillModal .v84-modal').scrollTop;
          },{capture:true});
        }""")
        self.before=self.snapshot();self.open_drill()
        self.page.locator('#v84DrillBody button[data-v84-sub]').filter(has_text='Сергей').click()
        self.edit_first()
        self.page.locator('#xAmount').fill('999,99');self.page.locator('#xComment').fill('Unsaved draft')
        self.page.locator('#editModal').get_by_role('button',name='Отмена',exact=True).click()
        self.assertTrue(self.page.locator('#v84DrillModal').is_visible())
        self.assertFalse(self.page.locator('#editModal').is_visible())
        self.assertEqual(self.snapshot(),self.before)
        active=self.page.locator('#v84DrillBody button[data-v84-sub][aria-pressed="true"]')
        self.assertIn('Сергей',active.inner_text())
        self.assertEqual(self.page.locator('#analyticsMonth').input_value(),self.period)
        scroll=self.page.evaluate("({expected:window.__expectedDrillScroll,actual:document.querySelector('#v84DrillModal .v84-modal').scrollTop})")
        self.assertGreater(scroll['expected'],0)
        self.assertAlmostEqual(scroll['actual'],scroll['expected'],delta=1)

    def test_category_change_removes_row_from_same_group_without_rewriting_unrelated(self):
        self.prepare();self.open_drill();self.edit_first()
        self.page.locator('#xCat').select_option('ЖКХ');self.save()
        self.assertEqual(self.page.locator('#v84DrillTitle').inner_text(),self.group)
        rows=self.page.locator('#v84DrillEntries')
        self.assertNotIn('Fictional first',rows.inner_text());self.assertIn('Fictional second',rows.inner_text())
        current=json.loads(self.snapshot()['state']);original=json.loads(self.before['state'])
        self.assertEqual(current['entries'][1:],original['entries'][1:])
        self.assertEqual(current['entries'][0]['category'],'ЖКХ')

    def test_subfilter_summary_tracks_only_visible_rows_and_all_reset_recovers(self):
        self.prepare()
        self.page.evaluate("state.entries[1].beneficiary='Виктория';renderAll()")
        self.open_drill()
        self.assertEqual(self.page.locator('#v96DrillCount').inner_text(),'2')
        self.assertIn('241,00',self.page.locator('#v96DrillTotal').inner_text())
        self.page.locator('#v84DrillBody button[data-v84-sub]').filter(has_text='Сергей').click()
        self.assertEqual(self.page.locator('#v96DrillCount').inner_text(),'1')
        self.assertIn('120,50',self.page.locator('#v96DrillTotal').inner_text())
        self.assertIn('120,50',self.page.locator('#v96DrillAverage').inner_text())
        self.edit_first();self.page.locator('#xCat').select_option('ЖКХ');self.save()
        self.assertEqual(self.page.locator('#v84DrillEntries .v85-drill-entry').count(),0)
        self.assertEqual(self.page.locator('#v96DrillCount').inner_text(),'0')
        self.assertIn('0,00',self.page.locator('#v96DrillTotal').inner_text())
        self.page.locator('#v84DrillBody').get_by_role('button',name='Все операции',exact=True).click()
        self.assertEqual(self.page.locator('#v96DrillCount').inner_text(),'1')
        self.assertIn('120,50',self.page.locator('#v96DrillTotal').inner_text())
        self.assertIn('Fictional second',self.page.locator('#v84DrillEntries').inner_text())

    def test_person_home_context_survives_recipient_change(self):
        self.prepare();self.page.set_viewport_size({'width':390,'height':844})
        self.open_drill(mode='person',source='home');self.edit_first()
        self.page.locator('#xBeneficiary').select_option('Виктория');self.save()
        self.assertEqual(self.page.locator('#v84DrillTitle').inner_text(),'Сергей')
        self.assertEqual(self.page.locator('#homeMonth').input_value(),self.period)
        self.assertNotIn('Fictional first',self.page.locator('#v84DrillEntries').inner_text())
        self.assertIn('Fictional second',self.page.locator('#v84DrillEntries').inner_text())
        self.assertEqual(self.page.evaluate('v96DrillContext.source'),'home')
        self.assertEqual(self.page.evaluate('v96DrillContext.mode'),'person')

    def test_last_record_moved_to_another_month_keeps_original_empty_period(self):
        self.prepare()
        self.page.evaluate("state.entries=state.entries.filter(e=>e.id!=='fictional-second'&&e.id!=='fictional-other');renderAll()")
        self.open_drill();self.edit_first()
        self.page.locator('#xDate').fill(self.page.evaluate('month()')+'-09');self.save()
        self.assertEqual(self.page.locator('#analyticsMonth').input_value(),self.period)
        self.assertEqual(self.page.evaluate('v96DrillContext.month'),self.period)
        self.assertEqual(self.page.locator('#v84DrillEntries .v85-drill-entry').count(),0)
        self.assertIn('Записей пока нет',self.page.locator('#v84DrillEntries').inner_text())

    def test_malicious_id_is_data_and_invalid_amount_or_cancel_does_not_save(self):
        self.prepare(malicious=True);self.open_drill();self.edit_first()
        self.assertFalse(self.page.evaluate('window.__drillInjected'))
        self.assertEqual(self.page.locator('#drill-injected').count(),0)
        self.page.locator('#xAmount').fill('12,345')
        self.page.locator('#editModal').get_by_role('button',name='Сохранить',exact=True).click()
        self.assertTrue(self.page.locator('#editModal').is_visible())
        self.assertEqual(self.snapshot(),self.before)
        self.page.locator('#editModal').get_by_role('button',name='Отмена',exact=True).click()
        self.assertTrue(self.page.locator('#v84DrillModal').is_visible())
        self.assertFalse(self.page.evaluate('window.__drillInjected'))
        self.assertEqual(self.snapshot(),self.before)

    def test_failed_local_storage_never_claims_cloud_or_durable_success(self):
        self.prepare();self.open_drill();self.edit_first()
        self.page.evaluate("""() => {
          const native=Storage.prototype.setItem;
          Storage.prototype.setItem=function(key,value){
            if(key===KEYS.state||key===KEYS.pending)throw new DOMException('Synthetic quota','QuotaExceededError');
            return native.call(this,key,value);
          };
        }""")
        self.page.locator('#xAmount').fill('88,25');self.save()
        self.assertIn('Не удалось надёжно сохранить',self.page.locator('#v96DrillSaveStatus').inner_text())
        self.assertNotIn('Изменения сохранены',self.page.locator('#v96DrillSaveStatus').inner_text())

    def test_late_ack_does_not_reopen_a_drill_closed_by_user(self):
        self.prepare();self.open_drill();self.edit_first()
        self.page.evaluate("""() => {
          const native=saveAll;
          saveAll=function(){native();return new Promise(resolve=>window.__resolveDrillSave=resolve)};
        }""")
        self.page.locator('#xAmount').fill('21,50');self.save()
        self.page.get_by_role('button',name='Закрыть расшифровку',exact=True).click()
        self.page.evaluate("window.__resolveDrillSave(false)")
        self.page.wait_for_timeout(50)
        self.assertFalse(self.page.locator('#v84DrillModal').is_visible())
        self.assertFalse(self.page.locator('#editModal').is_visible())

    def test_ordinary_history_editor_does_not_open_drill(self):
        self.prepare();self.page.evaluate("openEdit('fictional-first')")
        self.page.locator('#xAmount').fill('19,50')
        self.page.locator('#editModal').get_by_role('button',name='Сохранить',exact=True).click()
        self.page.wait_for_function("!document.getElementById('editModal').classList.contains('open')")
        self.assertFalse(self.page.locator('#v84DrillModal').is_visible())
        self.assertEqual(self.page.evaluate('state.entries[0].amount'),19.5)


if __name__=='__main__':
    unittest.main()
