"""Synthetic feedback drafts and mocked receipts; never emails or contacts servers."""
import json
import time
import unittest
from urllib.parse import parse_qs, urlsplit
import test_local_data_safety as harness


class FeedbackRequests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open

    def prepare(self):
        weather={'at':int(time.time()*1000),'source':'Fictional weather fixture',
                 'data':{'temperature_2m':0,'apparent_temperature':0,'weather_code':0,'wind_speed_10m':0}}
        self.open({'marichevy_weather_last_good_v74':json.dumps(weather)})
        self.page.evaluate("""() => {
          session=null;state=blankState();localStorage.clear();showApp();go('settings');
          state.futureFinancialMarker='PRIVATE_FINANCIAL_ROWS_MUST_NOT_BE_INCLUDED';
          window.__feedbackCalls=[];window.__drafts=[];
          v96OpenFeedbackDraft=url=>window.__drafts.push(url);
          window.fetch=async()=>{throw Error('No network permitted in feedback fixture')};
        }""")

    def fill(self, message='  Fictional feedback message with Unicode: функция ✓\nSecond line.  '):
        self.page.locator('#v88FeedbackMessage').fill(message)
        self.page.locator('#v88FeedbackSection').select_option('history')
        return message

    def fake_server(self, mode):
        self.page.evaluate("""mode => {
          session={access_token:'FICTIONAL_SESSION_MUST_NOT_BE_IN_BODY'};
          window.fetch=async(url,options)=>{
            const fields=Object.fromEntries(options.body.entries());
            window.__feedbackCalls.push({url,fields});
            const receipt={ok:true,saved:true,request_id:fields.request_id,
              receipt_id:'fictional-receipt-1',emailNotified:false};
            let reply=receipt;
            if(mode==='bare')reply={ok:true};
            if(mode==='wrong-request')reply={...receipt,request_id:'wrong-request'};
            if(mode==='truthy-email')reply={...receipt,emailNotified:'true'};
            if(mode==='accepted-email')reply={...receipt,emailNotified:true};
            return new Response(JSON.stringify(reply),{status:200,headers:{'Content-Type':'application/json'}});
          };
        }""",mode)

    def test_two_explicit_purposes_preserve_text_without_sending(self):
        self.prepare();message=self.fill()
        before=self.page.evaluate('JSON.stringify(state)')
        self.page.get_by_role('button',name='Сообщить об ошибке',exact=True).click()
        self.assertEqual(self.page.locator('#v88FeedbackType').input_value(),'bug')
        self.assertEqual(self.page.locator('#v88FeedbackMessage').input_value(),message)
        self.page.get_by_role('button',name='Предложить функцию',exact=True).click()
        self.assertEqual(self.page.locator('#v88FeedbackType').input_value(),'idea')
        self.assertEqual(self.page.locator('#v88FeedbackMessage').input_value(),message)
        self.assertEqual(self.page.evaluate('window.__feedbackCalls'),[])
        self.assertEqual(self.page.evaluate('window.__drafts'),[])
        self.assertEqual(self.page.evaluate('JSON.stringify(state)'),before)

    def test_both_email_drafts_target_trusted_owner_with_type_section_build_only(self):
        self.prepare();message=self.fill()
        recipient=self.page.evaluate('V88_FEEDBACK_SUPPORT_EMAIL')
        build=self.page.evaluate('v88FeedbackPayload().appVersion')
        for button,type_label in [('Сообщить об ошибке','Ошибка'),('Предложить функцию','Новая функция')]:
            with self.subTest(purpose=button):
                self.page.get_by_role('button',name=button,exact=True).click()
                self.page.locator('#v881MailLink').click()
                url=self.page.evaluate('window.__drafts.at(-1)')
                parts=urlsplit(url);query=parse_qs(parts.query)
                self.assertEqual(parts.scheme,'mailto');self.assertEqual(parts.path,recipient)
                self.assertIn(type_label,query['subject'][0]);self.assertIn('История операций',query['subject'][0])
                self.assertIn(build,query['subject'][0]);self.assertIn(build,query['body'][0])
                self.assertIn(type_label,query['body'][0]);self.assertIn('История операций',query['body'][0])
                self.assertIn(message,query['body'][0])
                self.assertNotIn('PRIVATE_FINANCIAL_ROWS_MUST_NOT_BE_INCLUDED',url)
                self.assertNotIn('FICTIONAL_SESSION_MUST_NOT_BE_IN_BODY',url)
                self.assertEqual(self.page.locator('#v88FeedbackMessage').input_value(),message)
                self.assertIn('ещё не отправлено',self.page.locator('#v88FeedbackStatus').inner_text())
                self.assertEqual(self.page.locator('#v88FeedbackStatus').get_attribute('data-kind'),'info')
        self.assertEqual(self.page.evaluate('window.__feedbackCalls'),[])

    def test_missing_session_does_not_fake_server_delivery_or_discard_message(self):
        self.prepare();message=self.fill()
        self.page.evaluate('v88SendFeedback()')
        self.assertEqual(self.page.evaluate('window.__feedbackCalls'),[])
        self.assertEqual(self.page.locator('#v88FeedbackMessage').input_value(),message)
        self.assertIn('войдите',self.page.locator('#v88FeedbackStatus').inner_text().lower())
        self.assertEqual(self.page.locator('#v88FeedbackStatus').get_attribute('data-kind'),'error')

    def test_bare_success_and_wrong_receipt_cannot_claim_delivery(self):
        for mode in ['bare','wrong-request']:
            with self.subTest(mode=mode):
                self.prepare();message=self.fill();self.fake_server(mode)
                before=self.page.evaluate('JSON.stringify(state)')
                self.page.evaluate('v88SendFeedback()')
                self.assertEqual(self.page.locator('#v88FeedbackStatus').get_attribute('data-kind'),'error')
                self.assertIn('не подтвердил приём',self.page.locator('#v88FeedbackStatus').inner_text())
                self.assertEqual(self.page.locator('#v88FeedbackMessage').input_value(),message)
                self.assertEqual(self.page.evaluate('JSON.stringify(state)'),before)

    def test_saved_receipt_without_boolean_email_ack_is_not_email_success(self):
        self.prepare();message=self.fill();self.fake_server('truthy-email')
        self.page.evaluate('v88SendFeedback()')
        self.assertEqual(self.page.locator('#v88FeedbackStatus').get_attribute('data-kind'),'info')
        self.assertIn('отправка письма владельцу не подтверждена',self.page.locator('#v88FeedbackStatus').inner_text())
        self.assertEqual(self.page.locator('#v88FeedbackMessage').input_value(),message)
        fields=self.page.evaluate('window.__feedbackCalls[0].fields')
        self.assertEqual(set(fields),{'request_id','type','section','message','appVersion','familyEdition'})
        self.assertEqual(fields['message'],message)
        encoded=json.dumps(fields)
        self.assertNotIn('PRIVATE_FINANCIAL_ROWS_MUST_NOT_BE_INCLUDED',encoded)
        self.assertNotIn('FICTIONAL_SESSION_MUST_NOT_BE_IN_BODY',encoded)

    def test_matching_receipt_distinguishes_provider_acceptance_and_retains_retry_identity(self):
        self.prepare();message=self.fill();self.fake_server('accepted-email')
        self.page.evaluate('v88SendFeedback()')
        self.assertEqual(self.page.locator('#v88FeedbackStatus').get_attribute('data-kind'),'success')
        status=self.page.locator('#v88FeedbackStatus').inner_text()
        self.assertIn('Почтовый сервис принял письмо',status)
        self.assertIn('доставка во входящие ещё не подтверждена',status)
        self.assertEqual(self.page.locator('#v88FeedbackMessage').input_value(),message)
        self.page.evaluate('v88SendFeedback()')
        ids=self.page.evaluate('window.__feedbackCalls.map(call=>call.fields.request_id)')
        self.assertEqual(len(ids),2);self.assertEqual(ids[0],ids[1])


if __name__=='__main__':
    unittest.main()
