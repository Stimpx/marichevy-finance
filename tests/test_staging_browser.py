"""Offline staging browser sanitizer/bridge guards; no hosted request is made."""
import base64
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import staging_browser as helper


HOUSE = "11111111-1111-4111-8111-111111111111"
KEY = "sb_publishable_synthetic_unit_key"


class SanitizedStagingClient(unittest.TestCase):
    def test_personal_source_is_sanitized_without_bypassing_actual_auth_sync(self):
        source = (ROOT / "index.html").read_text()
        original = helper.CONFIG_RE.search(source).group()
        html = helper.sanitized_client(source, KEY, HOUSE)
        self.assertNotIn(original, html)
        self.assertIn(helper.PROJECT_URL, html)
        self.assertIn(KEY, html)
        self.assertIn(HOUSE, html)
        self.assertIn(helper.STATE_KEY, html)
        self.assertIn(helper.PENDING_KEY, html)
        for private in ["gmail.com", "Сергей", "Виктория", "1985-11-27", "9946-WZ3/00067"]:
            self.assertNotIn(private, html)
        for bypass in ["window.fetch=()=>Promise.reject", "startCloudSync=()=>{}", "showApp();setStatus('ДЕМО"]:
            self.assertNotIn(bypass, html)
        for actual in ["async function gateLogin()", "async function verifyCachedSession(",
                       "async function pushCloud(", "function reconcileCloudSnapshot("]:
            self.assertIn(actual, html)
        self.assertEqual(html.count('http-equiv="Content-Security-Policy"'), 1)
        self.assertIn("connect-src " + helper.PROJECT_URL, html)

    def test_admin_or_injectable_keys_never_enter_html(self):
        source = (ROOT / "index.html").read_text()
        payload = base64.urlsafe_b64encode(json.dumps({"role": "service_role"}).encode()).decode().rstrip("=")
        for key in ["sb_secret_private_value", "x.';alert(1);//", "x." + payload + ".x", "arbitrary-string"]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                helper.sanitized_client(source, key, HOUSE)

    def test_existing_anon_jwt_is_accepted_as_public_key(self):
        payload = base64.urlsafe_b64encode(json.dumps({"role": "anon"}).encode()).decode().rstrip("=")
        key = "x." + payload + ".x"
        html = helper.sanitized_client((ROOT / "index.html").read_text(), key, HOUSE)
        self.assertIn("key:'" + key + "'", html)

    def test_changed_or_duplicate_wrappers_fail_closed(self):
        source = (ROOT / "index.html").read_text()
        demo = helper.transform_demo(source)
        variants = [demo.replace("window.fetch=()=>Promise.reject", "window.fetch=changed"),
                    demo + '<meta http-equiv="Content-Security-Policy" content="none">',
                    demo.replace("startCloudSync=()=>{};", "startCloudSync=changed;", 1)]
        for value in variants:
            with self.subTest(variant=len(value)), patch.object(helper, "transform_demo", return_value=value), self.assertRaises(ValueError):
                helper.sanitized_client(source, KEY, HOUSE)


class FakeRequest:
    def __init__(self, url, method="GET", body=None):
        self.url, self.method = url, method
        self.post_data = None if body is None else json.dumps(body)
        self.headers = {"authorization": "Bearer synthetic-user-token", "apikey": KEY,
                        "cookie": "must-not-forward", "content-type": "application/json"}


class FakeRoute:
    def __init__(self, request):
        self.request = request
        self.result, self.aborted, self.continued = None, False, False
    def fulfill(self, **kwargs):
        self.result = kwargs
    def abort(self):
        self.aborted = True
    def continue_(self):
        self.continued = True


class FakeTransport:
    def __init__(self, response):
        self.response, self.calls = response, []
    def request(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        return self.response


class BridgeBoundary(unittest.TestCase):
    def test_only_staging_auth_rest_is_forwarded_and_response_is_not_synthesized(self):
        transport = FakeTransport((200, {"status": "conflict", "revision": 42}))
        bridge = helper.RouteBridge(transport, "http://127.0.0.1:1234/")
        payload = {"p_expected_revision": 41, "p_data": {"fictional": True}}
        route = FakeRoute(FakeRequest(helper.PROJECT_URL + "/rest/v1/rpc/family_state_cas", "POST", payload))
        bridge.route(route, "a")
        self.assertEqual(json.loads(route.result["body"]), transport.response[1])
        self.assertEqual(transport.calls[0][3], payload)
        self.assertNotIn("cookie", transport.calls[0][2])
        self.assertEqual(bridge.cas_conflicts, 1)
        self.assertEqual(bridge.forwarded, 1)
        for url in ["https://production.supabase.co/rest/v1/family_state", "https://example.invalid/", helper.PROJECT_URL + "/functions/v1/test"]:
            denied = FakeRoute(FakeRequest(url))
            bridge.route(denied, "a")
            self.assertTrue(denied.aborted)
        self.assertEqual(len(transport.calls), 1)

    def test_offline_aborts_without_forwarding_or_inventing_a_response(self):
        transport = FakeTransport((200, []))
        bridge = helper.RouteBridge(transport, "http://127.0.0.1:1234/")
        bridge.offline.add("a")
        route = FakeRoute(FakeRequest(helper.PROJECT_URL + "/rest/v1/family_state"))
        bridge.route(route, "a")
        self.assertTrue(route.aborted)
        self.assertIsNone(route.result)
        self.assertEqual(transport.calls, [])

    def test_read_barrier_obtains_two_real_transport_snapshots_before_releasing(self):
        transport = FakeTransport((200, [{"sync_revision": 7}]))
        bridge = helper.RouteBridge(transport, "http://127.0.0.1:1234/")
        bridge.hold_reads = True
        routes = [FakeRoute(FakeRequest(helper.PROJECT_URL + "/rest/v1/family_state")) for _ in range(2)]
        bridge.route(routes[0], "a")
        self.assertIsNone(routes[0].result)
        bridge.route(routes[1], "b")
        self.assertEqual(len(transport.calls), 2)
        self.assertTrue(all(route.result is not None for route in routes))
        self.assertFalse(bridge.hold_reads)


if __name__ == "__main__":
    unittest.main()
