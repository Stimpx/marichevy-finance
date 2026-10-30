"""Synthetic owner-requested analytics delete regressions; external requests blocked."""
import json
import re
import unittest
import test_analytics_edit as edit
import test_local_data_safety as harness

class AnalyticsDelete(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)
    setUp=harness.LocalDataSafety.setUp
    tearDown=harness.LocalDataSafety.tearDown
    open=harness.LocalDataSafety.open
    snapshot=harness.LocalDataSafety.snapshot
    prepare=edit.AnalyticsEdit.prepare
    open_drill=edit.AnalyticsEdit.open_drill

    def delete_first(self):
        row=self.page.locator('#v84DrillEntries .v85-drill-entry').filter(has_text='Fictional first')
        row.get_by_role('button',name=re.compile('^Удалить операцию:')).click()
        self.page.wait_for_function("document.getElementById('v96DrillSaveStatus').textContent.length>0")

    def test_deletes_exact_id_preserves_unrelated_and_refreshes_totals(self):
        self.prepare();self.open_drill();self.delete_first()
        current=json.loads(self.snapshot()['state']);original=json.loads(self.before['state'])
        self.assertEqual(current['entries'],original['entries'][1:])
        self.assertTrue(current['deletedEntries'][self.first_id])
        self.assertEqual(self.page.locator('#v84DrillEntries .v85-drill-entry').count(),1)
        self.assertIn('Fictional second',self.page.locator('#v84DrillEntries').inner_text())
        self.assertEqual(self.page.locator('#v96DrillCount').inner_text(),'1')
        self.assertIn('120,50',self.page.locator('#v96DrillTotal').inner_text())
        self.assertIn('120,50',self.page.locator('#v96DrillAverage').inner_text())
        self.assertEqual(self.page.locator('#analyticsMonth').input_value(),self.period)
        self.assertIn('Облако пока не подтвердило',self.page.locator('#v96DrillSaveStatus').inner_text())
        pending=json.loads(self.page.evaluate('localStorage.getItem(KEYS.pending)'))
        self.assertIn(self.first_id,pending['deletedEntries'])
        self.assertNotIn(self.first_id,[e['id'] for e in pending['entries']])
        self.assertIn('120,50',self.page.locator('#aCats').inner_text())

    def test_cancel_keeps_state_storage_filter_and_modal(self):
        self.prepare();self.open_drill()
        self.page.locator('#v84DrillBody button[data-v84-sub]').filter(has_text='Сергей').click()
        self.page.remove_listener('dialog',self.page.listeners('dialog')[0]) if hasattr(self.page,'listeners') else None
        self.page.evaluate('window.confirm=()=>false')
        row=self.page.locator('#v84DrillEntries .v85-drill-entry').filter(has_text='Fictional first')
        row.get_by_role('button',name=re.compile('^Удалить операцию:')).click()
        self.assertEqual(self.snapshot(),self.before)
        self.assertTrue(self.page.locator('#v84DrillModal').is_visible())
        self.assertEqual(self.page.evaluate('v96DrillContext.sub'),'Сергей')
        self.assertEqual(self.page.locator('#v96DrillCount').inner_text(),'2')

    def test_delete_last_record_keeps_original_month_and_empty_summary(self):
        self.prepare()
        self.page.evaluate("state.entries=state.entries.filter(e=>e.id!=='fictional-second'&&e.id!=='fictional-other');renderAll()")
        self.open_drill();self.delete_first()
        self.assertEqual(self.page.evaluate('v96DrillContext.month'),self.period)
        self.assertEqual(self.page.locator('#analyticsMonth').input_value(),self.period)
        self.assertEqual(self.page.locator('#v84DrillEntries .v85-drill-entry').count(),0)
        self.assertEqual(self.page.locator('#v96DrillCount').inner_text(),'0')
        self.assertIn('0,00',self.page.locator('#v96DrillTotal').inner_text())
        self.assertIn('0,00',self.page.locator('#v96DrillAverage').inner_text())
        self.assertIn('Записей пока нет',self.page.locator('#v84DrillEntries').inner_text())

    def test_filtered_delete_keeps_selection_and_all_operations_recover_other_person(self):
        self.prepare()
        self.page.evaluate("state.entries[1].beneficiary='Виктория';renderAll()")
        self.open_drill()
        self.page.locator('#v84DrillBody button[data-v84-sub]').filter(has_text='Сергей').click()
        self.delete_first()
        self.assertEqual(self.page.evaluate('v96DrillContext.sub'),'Сергей')
        self.assertEqual(self.page.locator('#v96DrillCount').inner_text(),'0')
        self.assertIn('0,00',self.page.locator('#v96DrillTotal').inner_text())
        self.assertIn('0,00',self.page.locator('#v96DrillAverage').inner_text())
        self.page.locator('#v84DrillBody').get_by_role('button',name='Все операции',exact=True).click()
        self.assertEqual(self.page.locator('#v96DrillCount').inner_text(),'1')
        self.assertIn('120,50',self.page.locator('#v96DrillTotal').inner_text())
        self.assertIn('Fictional second',self.page.locator('#v84DrillEntries').inner_text())

    def test_malicious_id_remains_data_and_only_selected_tombstone_is_created(self):
        self.prepare(malicious=True);self.open_drill();self.delete_first()
        self.assertFalse(self.page.evaluate('window.__drillInjected'))
        self.assertEqual(self.page.locator('#drill-injected').count(),0)
        current=json.loads(self.snapshot()['state'])
        self.assertIn(self.first_id,current['deletedEntries'])
        self.assertNotIn(self.first_id,[e['id'] for e in current['entries']])
        self.assertEqual([e['id'] for e in current['entries']],['fictional-second','fictional-other','fictional-current'])

    def test_late_ack_never_reopens_closed_drill(self):
        self.prepare();self.open_drill()
        self.page.evaluate("() => {const native=saveAll;saveAll=function(){native();return new Promise(resolve=>window.__resolveDeleteSave=resolve)}}")
        self.delete_first()
        self.page.get_by_role('button',name='Закрыть расшифровку',exact=True).click()
        self.page.evaluate('window.__resolveDeleteSave(false)')
        self.page.wait_for_timeout(50)
        self.assertFalse(self.page.locator('#v84DrillModal').is_visible())
        self.assertFalse(self.page.locator('#editModal').is_visible())

    def test_failed_local_storage_reports_failure_without_cloud_success(self):
        self.prepare();self.open_drill()
        self.page.evaluate("""() => {
          const native=Storage.prototype.setItem;
          Storage.prototype.setItem=function(key,value){
            if(key===KEYS.state||key===KEYS.pending)throw new DOMException('Synthetic quota','QuotaExceededError');
            return native.call(this,key,value);
          };
        }""")
        self.delete_first()
        self.assertIn('Не удалось надёжно сохранить',self.page.locator('#v96DrillSaveStatus').inner_text())
        self.assertNotIn('Удаление сохранено',self.page.locator('#v96DrillSaveStatus').inner_text())

    def test_mobile_buttons_visible_and_inside_dialog(self):
        self.prepare();self.page.set_viewport_size({'width':390,'height':844});self.open_drill()
        result=self.page.locator('#v84DrillEntries .v85-drill-entry').first.evaluate("""row=>{
          const bounds=document.querySelector('#v84DrillModal .v84-modal').getBoundingClientRect();
          return [...row.querySelectorAll('button')].map(b=>{
            const r=b.getBoundingClientRect();return {label:b.textContent,height:r.height,inside:r.left>=bounds.left&&r.right<=bounds.right};
          });
        }""")
        self.assertEqual([x['label'] for x in result],['Изменить','Повторить','Удалить'])
        self.assertTrue(all(x['height']>=44 and x['inside'] for x in result))

if __name__=='__main__':unittest.main()
