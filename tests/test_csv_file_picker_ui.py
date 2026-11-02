"""CSV picker presentation and real file chooser; fictional data, remote I/O blocked."""
from pathlib import Path
import sys
import unittest

import test_local_data_safety as harness

sys.path.insert(0, str(Path(harness.__file__).resolve().parents[1] / 'tools'))
from check_touch_flows import enlarge_text


class CSVFilePickerUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls): harness.LocalDataSafety.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls): harness.LocalDataSafety.tearDownClass.__func__(cls)
    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open
    snapshot = harness.LocalDataSafety.snapshot

    def prepare(self, width=1280):
        self.page.set_viewport_size({'width': width, 'height': 1000})
        self.open()
        self.page.evaluate("""() => {
          stopCloudSync();session=null;state=blankState();localStorage.clear();
          localRecoveryBlocked=false;
          state.futureCSV={preserve:[null,true,'raw']};
          state.entries=[{id:'fictional-existing',date:today(),type:'expense',amount:17.251,
            category:'Прочее',who:'Вымышленный участник',store:'Учебный магазин',
            futureField:{keep:[true,null,3]}}];
          telegramNotify=async()=>false;showApp();renderAll();go('today');
          document.getElementById('v119OperationTools').open=true;
          window.csvPickerSaves=0;saveAll=async()=>{window.csvPickerSaves++;return false};
        }""")
        self.before = self.snapshot()

    def payload(self, name='Учебная выписка.csv', buffer=None):
        text='Дата;Сумма;Описание\n02.11.2026;-123,45;Учебная покупка\n'
        return {'name':name,'mimeType':'text/csv',
                'buffer':text.encode('utf-8') if buffer is None else buffer}

    def choose(self, payload, keyboard=None):
        button=self.page.locator('#v124CSVChoose')
        button.scroll_into_view_if_needed()
        if keyboard: button.focus()
        with self.page.expect_file_chooser() as chooser:
            button.press(keyboard) if keyboard else button.click()
        chooser.value.set_files(payload)

    def wait_stage(self, name):
        self.page.wait_for_function('(name)=>v119CSV?.name===name',arg=name)

    def assert_no_writes(self):
        self.assertEqual(self.snapshot(),self.before)
        self.assertEqual(self.page.evaluate('csvPickerSaves'),0)

    def test_keyboard_chooser_cancel_and_real_utf8_file_only_stage_a_preview(self):
        self.prepare()
        caption=self.page.locator('#v124CSVFileName').inner_text()
        self.choose([],keyboard='Enter')
        self.assertEqual(self.page.locator('#v124CSVFileName').inner_text(),caption)
        self.assertIsNone(self.page.evaluate('v119CSV'))
        self.assert_no_writes()

        self.choose(self.payload(),keyboard='Space')
        self.wait_stage('Учебная выписка.csv')
        self.assertIn('Учебная выписка.csv',self.page.locator('#v124CSVFileName').inner_text())
        self.assertTrue(self.page.locator('#v119CSVPanel').is_visible())
        self.assertEqual(self.page.locator('#v119CSVFile').input_value(),'')
        self.assertTrue(self.page.locator('#v119CSVConfirm').is_disabled())
        self.assertEqual(self.page.evaluate('v119CSV.raw[1][2]'),'Учебная покупка')
        self.assert_no_writes()

    def test_replace_cancel_and_same_file_reselect_preserve_staging_and_history(self):
        self.prepare()
        self.choose(self.payload())
        self.wait_stage('Учебная выписка.csv')
        staged=self.page.evaluate('JSON.stringify(v119CSV)')
        self.choose([])
        self.assertEqual(self.page.evaluate('JSON.stringify(v119CSV)'),staged)
        self.assertIn('Учебная выписка.csv',self.page.locator('#v124CSVFileName').inner_text())

        self.choose(self.payload('Другая выписка.csv'))
        self.wait_stage('Другая выписка.csv')
        self.assertIn('Другая выписка.csv',self.page.locator('#v124CSVFileName').inner_text())
        self.page.get_by_role('button',name='Отменить импорт',exact=True).click()
        self.assertIsNone(self.page.evaluate('v119CSV'))
        self.assertFalse(self.page.locator('#v119CSVPanel').is_visible())
        self.assertNotIn('Другая выписка.csv',self.page.locator('#v124CSVFileName').inner_text())
        self.choose(self.payload('Другая выписка.csv'))
        self.wait_stage('Другая выписка.csv')
        self.assert_no_writes()

    def test_filename_is_literal_and_picker_fits_small_and_enlarged_text(self):
        filename='Учебная-банковская-выписка-'+('длинное-имя-'*8)+'<img>.csv'
        for width,scale in ((320,1),(390,1),(820,1),(1440,1),(320,2),(390,2)):
            with self.subTest(width=width,scale=scale):
                self.prepare(width)
                self.choose(self.payload(filename))
                self.wait_stage(filename)
                self.assertEqual(self.page.locator('#v124CSVFileName img').count(),0)
                self.assertIn(filename,self.page.locator('#v124CSVFileName').inner_text())
                if scale!=1: enlarge_text(self.page,scale)
                picker=self.page.locator('#v124CSVPicker')
                picker.scroll_into_view_if_needed()
                geometry=picker.evaluate("""root=>({viewport:innerWidth,doc:document.documentElement.scrollWidth,
                  rows:[root,...root.querySelectorAll('button,[id="v124CSVFileName"]')].map(el=>{
                    const r=el.getBoundingClientRect(),s=getComputedStyle(el);
                    return {id:el.id,left:r.left,right:r.right,height:r.height,lineHeight:parseFloat(s.lineHeight),sw:el.scrollWidth,cw:el.clientWidth,
                      overflow:s.overflowX,ellipsis:s.textOverflow,title:el.title,text:el.textContent};
                  })})""")
                self.assertLessEqual(geometry['doc'],width+1,geometry)
                for row in geometry['rows']:
                    self.assertGreaterEqual(row['left'],-1,geometry)
                    self.assertLessEqual(row['right'],width+1,geometry)
                    if row['id']=='v124CSVChoose':
                        self.assertGreaterEqual(row['height'],44,geometry)
                        self.assertLessEqual(row['sw'],row['cw']+1,geometry)
                    elif row['id']=='v124CSVFileName':
                        self.assertLessEqual(row['height'],row['lineHeight']*2+1,geometry)
                        self.assertEqual(row['title'],filename,geometry)
                        if row['sw']>row['cw']+1:
                            self.assertEqual(row['ellipsis'],'ellipsis',geometry)
                native=self.page.locator('#v119CSVFile').evaluate("""el=>{
                  const r=el.getBoundingClientRect(),s=getComputedStyle(el);
                  return {hidden:el.hidden||s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0,
                    tab:el.tabIndex,aria:el.getAttribute('aria-hidden')};
                }""")
                self.assertTrue(native['hidden'],native)
                self.assertEqual(native['tab'],-1,native)
                self.assertEqual(native['aria'],'true',native)
                self.assert_no_writes()

    def test_invalid_file_displays_error_and_never_claims_ready_or_writes(self):
        self.prepare()
        self.choose(self.payload('Некорректная кодировка.csv',bytes([255,254,253])))
        self.page.wait_for_function("document.getElementById('v119ToolsStatus').textContent.includes('UTF-8')")
        self.assertIsNone(self.page.evaluate('v119CSV'))
        self.assertFalse(self.page.locator('#v119CSVPanel').is_visible())
        self.assertTrue(self.page.locator('#v124CSVChoose').is_enabled())
        self.assertEqual(self.page.locator('#v119CSVFile').input_value(),'')
        self.assert_no_writes()

    def test_failed_import_keeps_filename_and_blocks_replacement_until_successful_retry(self):
        self.prepare()
        self.choose(self.payload('Выписка для повторного сохранения.csv'))
        self.wait_stage('Выписка для повторного сохранения.csv')
        original=self.page.evaluate('JSON.stringify(state.entries[0])')
        self.page.evaluate("""() => {
          v119CSVPreview();window.pendingCSVPickerStage=v119CSV;
          saveAll=async()=>{csvPickerSaves++;v89StorageFailed=true;return false};
        }""")
        self.page.locator('#v119CSVConfirm').click()
        self.page.wait_for_function('!v119Busy&&!!v119CSV?.committed')
        identifiers=self.page.evaluate('state.entries.map(row=>row.id)')
        self.assertEqual(len(identifiers),2)
        self.assertTrue(self.page.evaluate('v119CSV===pendingCSVPickerStage'))
        self.assertIn('Выписка для повторного сохранения.csv',
                      self.page.locator('#v124CSVFileName').inner_text())
        self.assertTrue(self.page.locator('#v124CSVChoose').is_disabled())
        self.assertTrue(self.page.locator('#v119CSVConfirm').is_enabled())
        self.assertEqual(self.page.evaluate('csvPickerSaves'),1)

        self.page.evaluate('()=>{saveAll=async()=>{csvPickerSaves++;v89StorageFailed=false;return true}}')
        self.page.locator('#v119CSVConfirm').click()
        self.page.wait_for_function('!v119Busy&&v119CSV===null')
        self.assertNotIn('Выписка для повторного сохранения.csv',
                         self.page.locator('#v124CSVFileName').inner_text())
        self.assertTrue(self.page.locator('#v124CSVChoose').is_enabled())
        self.assertFalse(self.page.locator('#v119CSVPanel').is_visible())
        self.assertEqual(self.page.evaluate('state.entries.map(row=>row.id)'),identifiers)
        self.assertEqual(self.page.evaluate('state.entries[1].amount'),123.45)
        self.assertEqual(self.page.evaluate('JSON.stringify(state.entries[0])'),original)
        self.assertEqual(self.page.evaluate('csvPickerSaves'),2)
        self.assertEqual(self.snapshot()['storage'],self.before['storage'])

    def test_logout_during_file_read_clears_filename_and_rejects_late_result(self):
        self.prepare()
        self.page.evaluate("""() => {
          const original=File.prototype.arrayBuffer;
          File.prototype.arrayBuffer=function(){return new Promise(resolve=>{
            window.finishCSVPickerRead=()=>original.call(this).then(resolve);
          })};
        }""")
        self.choose(self.payload('Частная учебная выписка.csv'))
        self.page.wait_for_function("typeof finishCSVPickerRead==='function'")
        self.page.evaluate('authEpoch++;showGate()')
        self.page.evaluate('async()=>{await finishCSVPickerRead();await Promise.resolve()}')
        self.assertIsNone(self.page.evaluate('v119CSV'))
        self.assertNotIn('Частная учебная выписка.csv',self.page.locator('#v124CSVFileName').inner_text())
        self.assertFalse(self.page.locator('#v119CSVPanel').is_visible())
        self.assertEqual(self.page.evaluate('state.entries.length'),1)
        self.assertEqual(self.page.evaluate('csvPickerSaves'),0)


if __name__=='__main__': unittest.main()
