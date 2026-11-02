"""Full device download from real UI; fictional data, external requests blocked."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import test_local_data_safety as harness

class DeviceBackupUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)
    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open

    def test_ui_preserves_raw_queue_conflicts_and_unsaved_memory_without_session(self):
        self.open()
        before = json.loads(self.page.evaluate('''() => {
          session=null;showApp();localStorage.clear();
          state=blankState();state.entries=[{id:'fictional-memory',amount:1250.50}];
          const values={
            [KEYS.state]:'{"entries":[]}',[KEYS.pending]:'{broken pending\\ud800',
            [KEYS.state+'_cloud_base_v1']:'{"data":{"entries":[]}}',
            [KEYS.state+'_cloud_conflict_v1']:'{"local":1,"cloud":2}',
            [KEYS.state+'_cloud_conflict_v1_archive_old']:'{old raw conflict',
            [KEYS.pending+'_corrupt_v1']:'raw quarantine',
            [LOCAL_BACKUP_KEY]:'raw backup', [LOCAL_PREIMPORT_KEY]:'raw before import'};
          for(const [key,value] of Object.entries(values))localStorage.setItem(key,value);
          localStorage.setItem(KEYS.session,'NEVER_READ_SESSION');
          const native=Storage.prototype.getItem;
          Storage.prototype.getItem=function(key){if(key===KEYS.session)throw Error('session read');return native.call(this,key)};
          v74Go('settings');
          return JSON.stringify({values,memory:JSON.stringify(state)});
        }'''))
        button=self.page.get_by_role('button',name='↓ Полная копия устройства',exact=True,include_hidden=True)
        # Hidden sections are navigation controlled; reveal the actual containing section.
        self.page.evaluate("v74Go('settings')")
        with self.page.expect_download() as download:
            button.click()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'device.json';download.value.save_as(path)
            data=json.loads(path.read_text())
        self.assertEqual(data['format'],'marichevy-local-queue-capture-v1')
        self.assertEqual(data['memory_state_json'],before['memory'])
        self.assertFalse(data['session_included']);self.assertFalse(data['server_backup_included'])
        self.assertEqual({r['key']:r['raw'] for r in data['records']},before['values'])
        for record in data['records']:
            self.assertEqual(record['sha256_utf16le'],hashlib.sha256(record['raw'].encode('utf-16le',errors='surrogatepass')).hexdigest())
        after=json.loads(self.page.evaluate('(keys)=>JSON.stringify(Object.fromEntries(keys.map(k=>[k,localStorage.getItem(k)])))',list(before['values'])))
        self.assertEqual(after,before['values'])

    def test_manual_download_survives_blocked_auto_download_and_replacement(self):
        self.open(); self.page.clock.install()
        downloads=[];self.page.on('download',lambda d: downloads.append(d))
        expected=json.loads(self.page.evaluate("""() => {
          session=null;showApp();localStorage.clear();state=blankState();
          state.entries=[{id:'fictional-memory',amount:1250.50}];
          const values={
            [KEYS.pending]:'{unsent raw queue',
            [KEYS.state+'_cloud_conflict_v1']:'{"local":1,"cloud":2}'
          };
          for(const [key,value] of Object.entries(values))localStorage.setItem(key,value);
          window.__blockedAutoDownloads=0;
          HTMLAnchorElement.prototype.click=function(){window.__blockedAutoDownloads+=1};
          window.__backupRevoked=[];
          const revoke=URL.revokeObjectURL.bind(URL);
          URL.revokeObjectURL=url=>{window.__backupRevoked.push(url);revoke(url)};
          v74Go('settings');
          return JSON.stringify({values,memory:JSON.stringify(state)});
        }"""))
        button=self.page.get_by_role('button',name='↓ Полная копия устройства',exact=True)
        button.click()
        self.page.wait_for_function('window.__blockedAutoDownloads===1')
        link=self.page.get_by_role('link',name='Скачать подготовленную копию устройства',exact=True)
        self.assertTrue(link.is_visible());self.assertEqual(downloads,[])
        first_url=link.get_attribute('href')
        self.page.clock.fast_forward(3000)
        self.assertEqual(self.page.evaluate('window.__backupRevoked'),[])
        with self.page.expect_download() as download:
            link.click()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'first.json';download.value.save_as(path)
            data=json.loads(path.read_text())
        self.assertEqual(data['memory_state_json'],expected['memory'])
        self.assertEqual({r['key']:r['raw'] for r in data['records']},expected['values'])
        self.assertFalse(data['session_included']);self.assertFalse(data['storage_modified'])
        self.page.evaluate("state.entries[0].amount=777")
        button.click()
        self.page.wait_for_function('window.__blockedAutoDownloads===2')
        current_url=link.get_attribute('href')
        self.assertNotEqual(first_url,current_url)
        self.assertEqual(self.page.get_by_role('link',name='Скачать подготовленную копию устройства',exact=True).count(),1)
        self.assertEqual(self.page.evaluate('window.__backupRevoked'),[])
        self.page.clock.fast_forward(16000)
        self.assertIn(first_url,self.page.evaluate('window.__backupRevoked'))
        self.assertNotIn(current_url,self.page.evaluate('window.__backupRevoked'))
        with self.page.expect_download() as download:
            link.click()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'second.json';download.value.save_as(path)
            replacement=json.loads(path.read_text())
        self.assertEqual(json.loads(replacement['memory_state_json'])['entries'][0]['amount'],777)
        self.assertEqual({r['key']:r['raw'] for r in replacement['records']},expected['values'])

    def test_changed_memory_refuses_download(self):
        self.open();downloads=[];self.page.on('download',lambda d: downloads.append(d))
        result=self.page.evaluate('''async () => {
          localStorage.setItem(KEYS.pending,'fictional raw queue');
          const digest=crypto.subtle.digest.bind(crypto.subtle);
          crypto.subtle.digest=async(...args)=>{state.futureField='changed-during-hash';return digest(...args)};
          return await exportDeviceBackup();
        }''')
        self.assertEqual(result,{'outcome':'blocked','reason':'storage-changed-during-capture'})
        self.assertEqual(downloads,[])

    def test_denied_storage_does_not_download_or_clear_queue(self):
        self.open(); downloads=[];self.page.on('download',lambda d: downloads.append(d))
        result=self.page.evaluate("""async () => {
          localStorage.setItem(KEYS.pending,'fictional queue');
          const native=Storage.prototype.getItem;
          Storage.prototype.getItem=function(key){if(key===KEYS.pending)throw Error('PRIVATE');return native.call(this,key)};
          const result=await exportDeviceBackup();
          return {result,raw:native.call(localStorage,KEYS.pending)};
        }""")
        self.assertEqual(result,{'result':{'outcome':'blocked','reason':'capture-failed'},'raw':'fictional queue'})
        self.assertEqual(downloads,[])

if __name__=='__main__':unittest.main()
