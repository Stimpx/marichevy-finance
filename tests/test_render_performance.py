"""Offline render regressions: fixed work budgets and live financial state.

Run: python -m unittest discover -s tests -p test_render_performance.py
Requires Playwright and Chromium; CHROMIUM_EXECUTABLE may override the browser.
No authenticated account or external network is used. Timings are reported only;
assertions use deterministic call counts and financial outputs.
"""
from pathlib import Path
import json, os, shutil, unittest
from playwright.sync_api import sync_playwright

HTML = (Path(__file__).resolve().parents[1] / 'index.html').read_text()
BASE = 'http://127.0.0.1:9894/'


class RenderPerformance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = sync_playwright().start()
        executable = os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium') or shutil.which('chromium-browser')
        cls.browser = cls.p.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.p.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width':1280, 'height':1000}, timezone_id='Europe/Moscow', service_workers='block')
        self.context.add_init_script('''(() => {
          window.__clockMs=Date.parse('2026-11-02T12:00:00.000Z');
          const NativeDate=Date;
          window.Date=class extends NativeDate {
            constructor(...args){super(...(args.length?args:[window.__clockMs]))}
            static now(){return window.__clockMs}
          };
        })();''')
        self.context.route('**/*', lambda r: r.fulfill(status=200, content_type='text/html', body=HTML) if r.request.url == BASE else r.abort())
        self.page = self.context.new_page()
        self.errors=[]; self.page.on('pageerror', lambda error:self.errors.append(str(error)))
        self.page.goto(BASE, wait_until='domcontentloaded')
        self.page.wait_for_function("typeof v128OpenBankHistory==='function'")
        self.page.evaluate('''() => {
          session=null;localStorage.clear();state=blankState();localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
          state.entries=[{id:'synthetic-income',type:'income',date:'2026-11-02',amount:345626,category:'Зарплата',who:'Общее',store:'Synthetic employer'}];
          showApp();go('home');
        }''')

    def tearDown(self):
        self.context.close()

    def evaluate(self, code):
        return self.page.evaluate('async () => {'+code+'}')

    def test_moscow_day_cache_tracks_midnight_month_and_backward_clock(self):
        result=self.evaluate('''
          const moments=['2026-11-02T20:59:59.999Z','2026-11-02T21:00:00.000Z','2026-11-02T20:59:59.999Z','2026-11-30T20:59:59.999Z','2026-11-30T21:00:00.000Z'];
          return moments.map(value=>{window.__clockMs=Date.parse(value);return {day:today(),month:month()}});
        ''')
        self.assertEqual(result,[
            {'day':'2026-11-02','month':'2026-11'},
            {'day':'2026-11-03','month':'2026-11'},
            {'day':'2026-11-02','month':'2026-11'},
            {'day':'2026-11-30','month':'2026-11'},
            {'day':'2026-12-01','month':'2026-12'},
        ])

    def test_formatters_match_native_outputs_and_bank_date_validation(self):
        result=self.evaluate('''
          const values=[0,1,12.5,-1250.45,1000000,Infinity,NaN,'123.40'];
          const moneyParity=values.every(input=>{const value=Number(input)||0;return money(input)===new Intl.NumberFormat('ru-RU',{minimumFractionDigits:Number.isInteger(value)?0:2,maximumFractionDigits:2}).format(value)+' ₽'&&money2(input)===new Intl.NumberFormat('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2}).format(value)+' ₽'});
          const dateParity=['2026-11-02','2026-12-31','2028-02-29','2026-02-30'].every(date=>v77DateLabel(date)===new Date(date+'T12:00:00').toLocaleDateString('ru-RU',{day:'numeric',month:'short',year:'numeric'}));
          const invalid=['2026-99-99','n/a',null].map(date=>v77DateLabel(date));
          const make=(dueDate,amount=1)=>({id:'synthetic-validation',type:'expense',date:'2026-11-02',amount,mortgageAllocation:{version:1,kind:'regular',date:'2026-11-02',amount,principal:0,interest:0,charges:amount,extraPrincipal:0,dueDate}});
          const scheduled=BANK_LOAN_CURRENT_SCHEDULE.every(row=>!!v125MortgageRecord(make(row[1].split('.').reverse().join('-'))));
          const charges=BANK_LOAN_CURRENT_CHARGES.every(row=>!!v125MortgageRecord(make(row.payDate,row.payment)));
          return {moneyParity,dateParity,invalid,scheduled,charges,outside:!!v125MortgageRecord(make('2026-11-03'))};
        ''')
        self.assertEqual(result,{'moneyParity':True,'dateParity':True,'invalid':['—','—','—'],'scheduled':True,'charges':True,'outside':False})
        self.assertFalse(self.errors,self.errors)

    def test_large_history_full_render_has_bounded_bank_schedule_work(self):
        result=self.evaluate('''
          const stamp='2026-11-02T12:00:00.000Z';
          state.entries.push(...Array.from({length:999},(_,index)=>({id:'synthetic-expense-'+index,type:'expense',date:'2026-10-15',amount:1,category:'Продукты',who:'Общее',store:'Synthetic shop',created_at:stamp,updated_at:stamp})));
          const source=BANK_LOAN_RECONCILIATION,entry={id:'synthetic-mortgage',type:'expense',date:source.date,amount:source.regularPayment,category:'Кредит',who:'Общее',store:'Synthetic mortgage'};
          entry.mortgageAllocation=v128BankAllocation('regular',entry,source);state.entries.push(entry);renderAll();
          const before=JSON.stringify(state),cash=v111MonthBalance('2026-11').closing,debt=v125MortgageProgress().balance,original=v125BankScheduleData;
          let calls=0,elapsed;
          v125BankScheduleData=function(...args){calls++;return original.apply(this,args)};
          try{const started=performance.now();renderAll();elapsed=performance.now()-started}finally{v125BankScheduleData=original}
          const ob=v78Obligations('2026-11');
          return {entries:state.entries.length,calls,elapsed,unchanged:JSON.stringify(state)===before,cash,cashAfter:v111MonthBalance('2026-11').closing,debt,debtAfter:v125MortgageProgress().balance,paid:ob.paid,bank:ob.bankConfirmed,remaining:ob.remaining};
        ''')
        self.assertEqual(result['entries'],1001)
        self.assertLess(result['calls'],500,result)
        self.assertTrue(result['unchanged'],result)
        self.assertEqual(result['cashAfter'],result['cash'])
        self.assertEqual(result['debtAfter'],result['debt'])
        self.assertEqual((result['paid'],result['bank'],result['remaining']),(161830.21,0,85885))
        self.assertFalse(self.errors,self.errors)
        print('Large render: '+json.dumps({'entries':result['entries'],'bankScheduleCalls':result['calls'],'elapsedMs':round(result['elapsed'],2)}),flush=True)

    def test_editing_actual_payment_recomputes_cash_allocation_and_missing_amount(self):
        result=self.evaluate('''
          v128OpenBankHistory();await v128ApplyBankHistory();
          const entry=state.entries.find(e=>e.paymentKey===v128BankPaymentId('regular'));
          const before={cash:v111MonthBalance('2026-11').closing,paid:v78Obligations('2026-11').paid,missing:v128BankHistoryState().missingAmount,debt:v125MortgageProgress().balance};
          entry.amount=Math.round((entry.amount-1)*100)/100;
          const invalid={cash:v111MonthBalance('2026-11').closing,paid:v78Obligations('2026-11').paid,missing:v128BankHistoryState().missingAmount,valid:!!v125MortgageRecord(entry)};
          entry.mortgageAllocation.amount=entry.amount;entry.mortgageAllocation.interest=Math.round((entry.mortgageAllocation.interest-1)*100)/100;
          const repaired={cash:v111MonthBalance('2026-11').closing,paid:v78Obligations('2026-11').paid,missing:v128BankHistoryState().missingAmount,valid:!!v125MortgageRecord(entry),debt:v125MortgageProgress().balance};
          return {before,invalid,repaired};
        ''')
        self.assertEqual(result['before'],{'cash':143795.79,'paid':161830.21,'missing':0,'debt':4458197.19})
        self.assertEqual(result['invalid'],{'cash':143796.79,'paid':0,'missing':161830.21,'valid':False})
        self.assertEqual(result['repaired'],{'cash':143796.79,'paid':161829.21,'missing':1,'valid':True,'debt':4458197.19})
        self.assertFalse(self.errors,self.errors)


if __name__=='__main__':
    unittest.main(verbosity=2)
