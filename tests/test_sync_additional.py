"""Targeted client recovery/session regressions. Synthetic routes only."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

import test_sync_protocol as protocol


class AdditionalSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        protocol.SyncProtocol.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        protocol.SyncProtocol.tearDownClass.__func__(cls)

    setUp = protocol.SyncProtocol.setUp
    tearDown = protocol.SyncProtocol.tearDown
    device = protocol.SyncProtocol.device
    start = protocol.SyncProtocol.start
    finish = protocol.SyncProtocol.finish
    pending = protocol.SyncProtocol.pending

    def recover(self, primary, pending):
        page = self.device(primary)
        page.evaluate("""value=>{
            state=normalize(value.primary);saveLocal();
            localStorage.setItem(KEYS.pending,JSON.stringify(value.pending));
        }""", dict(primary=primary, pending=pending))
        page.reload(wait_until='domcontentloaded')
        page.wait_for_function("typeof state==='object' && typeof saveAll==='function'")
        page.evaluate("ensureToken=async()=>true;session={access_token:'synthetic-token',user:{id:'fictional-user'}}")
        return page

    def test_failed_primary_save_slow_clock_pending_edit_survives_reload_and_cas(self):
        base = protocol.fixture();base['entries']=[protocol.entry('shared', updated_at='2099-01-01')]
        self.backend.data=deepcopy(base)
        pending=deepcopy(base);pending['entries'][0].update(amount=99, updated_at='2001-01-01')
        page=self.recover(base,pending)
        reloaded=page.evaluate('state.entries[0].amount')
        self.assertTrue(page.evaluate('pushCloud()'))
        self.assertEqual((reloaded,self.backend.data['entries'][0]['amount']), (99,99))
        self.assertIsNone(self.pending(page))

    def test_failed_pending_save_slow_clock_primary_edit_survives_reload_and_cas(self):
        base=protocol.fixture();base['entries']=[protocol.entry('shared',updated_at='2099-01-01')]
        self.backend.data=deepcopy(base)
        primary=deepcopy(base);primary['entries'][0].update(amount=99,updated_at='2001-01-01')
        page=self.recover(primary,base)
        reloaded=page.evaluate('state.entries[0].amount')
        self.assertTrue(page.evaluate('pushCloud()'))
        self.assertEqual((reloaded,self.backend.data['entries'][0]['amount']), (99,99))

    def test_ambiguous_local_snapshots_keep_both_and_block_cloud_writes(self):
        base=protocol.fixture();base['entries']=[protocol.entry('shared')]
        self.backend.data=deepcopy(base)
        primary=deepcopy(base);primary['entries'][0].update(amount=21,updated_at='2099-01-01')
        pending=deepcopy(base);pending['entries'][0].update(amount=31,updated_at='2001-01-01')
        page=self.recover(primary,pending)
        self.assertTrue(page.evaluate('localRecoveryBlocked'))
        self.assertFalse(page.evaluate('pushCloud()'))
        self.assertEqual(self.backend.calls,[])
        self.assertEqual(page.evaluate('JSON.parse(localStorage.getItem(KEYS.state)).entries[0].amount'),21)
        self.assertEqual(self.pending(page)['entries'][0]['amount'],31)

    def test_refresh_response_after_logout_never_restores_session(self):
        page=self.device();held=[]
        page.route('**/auth/v1/token?grant_type=refresh_token',lambda route:held.append(route))
        page.evaluate("session.refresh_token='synthetic-refresh-token'")
        self.start(page,'refreshSession()')
        for _ in range(100):
            page.wait_for_timeout(10)
            if held:break
        self.assertEqual(len(held),1)
        page.evaluate('logout()')
        held[0].fulfill(json={'access_token':'synthetic-fresh-token','refresh_token':'synthetic-fresh-refresh','user':{'id':'fictional-user'}})
        self.assertFalse(self.finish(page))
        self.assertIsNone(page.evaluate('session'))
        self.assertIsNone(page.evaluate('localStorage.getItem(KEYS.session)'))

    def test_cached_session_verification_after_logout_never_restores_session(self):
        page=self.device();held=[]
        page.route('**/auth/v1/user',lambda route:held.append(route))
        self.start(page,'verifyCachedSession()')
        for _ in range(100):
            page.wait_for_timeout(10)
            if held:break
        self.assertEqual(len(held),1)
        page.evaluate('logout()')
        held[0].fulfill(json={'id':'fictional-user','email':'fixture@example.invalid'})
        self.assertFalse(self.finish(page))
        self.assertIsNone(page.evaluate('session'))
        self.assertIsNone(page.evaluate('localStorage.getItem(KEYS.session)'))

    def test_login_response_after_logout_never_unlocks_cached_finances(self):
        page=self.device();held=[]
        page.route('**/auth/v1/token?grant_type=password',lambda route:held.append(route))
        page.evaluate("gateEmail.value='fixture@example.invalid';gatePassword.value='fictional-password'")
        self.start(page,'gateLogin()')
        for _ in range(100):
            page.wait_for_timeout(10)
            if held:break
        self.assertEqual(len(held),1)
        page.evaluate('logout()')
        held[0].fulfill(json={'access_token':'synthetic-login-token','user':{'id':'fictional-user'}})
        self.finish(page)
        self.assertIsNone(page.evaluate('session'))
        self.assertIsNone(page.evaluate('localStorage.getItem(KEYS.session)'))
        self.assertTrue(page.locator('#appRoot').evaluate("node=>node.classList.contains('auth-locked')"))
        self.assertEqual(self.backend.calls,[])

    def test_distinct_unresolved_cloud_variants_survive_repeated_conflicts(self):
        base=protocol.fixture();base['entries']=[protocol.entry('shared')]
        self.backend.data=deepcopy(base)
        local=deepcopy(base);local['entries'][0]['amount']=31
        page=self.device(local,True)
        for amount in (21,22):
            self.backend.data['entries'][0]['amount']=amount
            self.backend.revision+=1
            self.assertFalse(page.evaluate('pushCloud()'))
        with page.expect_download() as event:
            page.evaluate('downloadSyncConflict()')
        packet=json.loads(Path(event.value.path()).read_text())
        self.assertEqual(packet['cloud']['entries'][0]['amount'],22)
        self.assertEqual(packet['local']['entries'][0]['amount'],31)
        self.assertEqual([p['cloud']['entries'][0]['amount'] for p in packet.get('previous_conflicts',[])],[21])
        before=page.evaluate("Object.keys(localStorage).filter(k=>k.includes('_cloud_conflict_v1_archive_')).length")
        self.assertFalse(page.evaluate('pushCloud()'))
        self.assertEqual(page.evaluate("Object.keys(localStorage).filter(k=>k.includes('_cloud_conflict_v1_archive_')).length"),before)


if __name__=='__main__':
    unittest.main()
