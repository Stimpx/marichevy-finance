"""Release candidate layout sweep: fictional demo only, never production.

Run: python -m unittest discover -s tests -p test_release_ui.py
Optional: RELEASE_UI_REPORT=/workspace/artifacts/release-ui-report.json
"""
from datetime import date, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import build_bundle

WIDTHS=(320,360,390,430,768,1024,1280,1512,1920)
SECTIONS=('home','today','history','analytics','income','car','loans','goals','chores','dates','settings')


def rich_fixture():
    """Synthetic, stable identifiers; all dates derived from today's test period."""
    today=date.today()
    stamp=today.isoformat()+'T12:00:00.000Z'
    def tagged(identifier,**fields):
        return dict(id=identifier,created_at=stamp,updated_at=stamp,**fields)
    people=['Алексей','Елена','София','Илья','Бим','Рыжик','Общее']
    categories=['Продукты','Вкусняшки','Школа и занятия','Животные','Авто и транспорт','Дом','Подарки','Рестораны и кафе','Аптека и медицина','Кредит','Одежда']
    entries=[]
    for month_offset in (0,1,2):
        period=today.replace(day=1)-timedelta(days=month_offset*31)
        day=period.replace(day=10).isoformat()
        for i,category in enumerate(categories):
            entries.append(tagged(f'qa-expense-{month_offset}-{i}',type='expense',date=day,amount=1250+i*475,category=category,who=people[i%len(people)],beneficiary=people[i%len(people)],store='Учебный магазин семейных покупок',pay='Карта',comment='Синтетическая покупка для проверки читаемости длинной подписи',subcategory=''))
        entries.append(tagged(f'qa-income-{month_offset}',type='income',date=day,amount=120000,category='Зарплата',who='Алексей',store='Демоработодатель',pay='Карта',comment='Учебный доход'))
        entries.append(tagged(f'qa-transfer-{month_offset}',type='transfer',date=day,amount=5000,category='Перевод',who='Общее',store='',pay='Карта',comment='Учебный перевод',**{'from':'Карта','to':'Накопления'}))
    return dict(entries=entries,
        goals=[tagged('qa-goal',name='Большое семейное путешествие на каникулы',target=250000,saved=75000,monthly=10000,deposits=[tagged('qa-deposit',amount=5000,date=today.isoformat(),who='Елена')])],
        birthdays=[tagged('qa-birthday',name='Фиктивный друг семьи',date='1994-12-18',phone='',group='Друзья',note='Только вымышленная запись')],
        boardItems=[tagged('qa-board',type='note',text='Обсудить план выходных и список покупок для семьи',author='Елена')],
        chores=[tagged('qa-chore',title='Купить учебные принадлежности для следующей недели',assignee='Алексей',dueDate=today.isoformat(),recurrence='weekly',lastDone='')],
        installments=[tagged('qa-installment',kind='split',title='Учебная покупка бытовой техники',provider='Демомагазин',amount=12000,period='monthly',links={},parts=[dict(id=f'qa-part-{i}',date=(today+timedelta(days=30*i)).isoformat(),amount=3000,paid=False) for i in range(4)])],
        settings={'loans':{'loanBank':'Демобанк','loan1':11000},'notifications':{'enabled':False,'telegram':False}},
        intelligence={'budgets':[tagged('qa-budget',group='Покупки и еда',amount=25000)],'recurring':[tagged('qa-recurring',title='Учебная связь и интернет',name='Учебная связь и интернет',category='ЖКХ',amount=1200,day=15,enabled=True)],'accounts':[tagged('qa-account',name='Учебный семейный счёт',amount=64000)],'deleted':{'budgets':{},'recurring':{},'accounts':{}}})


class ReleaseUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory(prefix='fictional-release-')
        directory=Path(cls.temporary.name)
        # Serve ONLY sanitized files, never the sibling private installation bundle.
        demo=directory/'safe-demo';demo.mkdir()
        source=(ROOT/'index.html').read_text()
        cls.source_sha256=hashlib.sha256(source.encode()).hexdigest()
        (demo/'index.html').write_text(build_bundle.transform_demo(source))
        (demo/'favicon.svg').write_text(build_bundle.ICON)
        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self,*_args):pass
            def end_headers(self):
                self.send_header('Content-Security-Policy',build_bundle.CSP)
                super().end_headers()
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(demo)))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}/'
        cls.playwright=sync_playwright().start()
        cls.browser=cls.playwright.chromium.launch(executable_path='/usr/bin/chromium',headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.playwright.stop();cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temporary.cleanup()

    def test_all_sections_and_major_modals(self):
        report={'source_sha256':self.source_sha256,'widths':list(WIDTHS),'sections':list(SECTIONS),'checks':[],'issues':[],'limitations':['Chromium only; Safari/Yandex require owner checks','No production, authenticated backend, RLS or Telegram validation']}
        for width in WIDTHS:
            with self.subTest(width=width):
                context=self.browser.new_context(viewport={'width':width,'height':900 if width>=768 else 844},timezone_id='Europe/Moscow',service_workers='block')
                page=context.new_page();page.set_default_timeout(5000)
                errors=[];outbound=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('console',lambda message:errors.append(message.text) if message.type=='error' else None)
                def route_request(route):
                    if route.request.url.startswith(self.base):route.continue_()
                    else:outbound.append(route.request.url);route.abort()
                context.route('**/*',route_request)
                storage=json.dumps(json.dumps(rich_fixture(),ensure_ascii=False))
                context.add_init_script("localStorage.setItem('marichevy_demo_state_v10',"+storage+");")
                page.goto(self.base,wait_until='load')
                page.wait_for_function("typeof state==='object' && !document.getElementById('appRoot').classList.contains('auth-locked')")
                self.assertIsNone(page.evaluate('session'))
                page.add_style_tag(content='*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}')
                for section in SECTIONS:
                    page.evaluate('(section)=>{go(section);window.scrollTo(0,0)}',section)
                    page.wait_for_timeout(40)
                    self._layout_check(page,report,width,section)
                page.evaluate("go('today');document.getElementById('v90Extra').open=true")
                self._layout_check(page,report,width,'today/details')
                page.evaluate("go('loans');v77Form(true);toggleLoanSchedule();addEarlyPaymentRow()")
                self._layout_check(page,report,width,'loans/forms-and-schedule')
                for label,open_script,selector,close_script in [
                    ('edit','openEdit("qa-expense-0-0")','#editModal .modal','closeEdit()'),
                    ('analytics drill','v84Drill("person","Общее")','#v84DrillModal .v84-modal','v84CloseDrill()'),
                    ('auth presentation','openAuth()','#authModal .modal','closeAuth()')]:
                    page.evaluate(open_script)
                    modal=page.locator(selector);self.assertTrue(modal.is_visible(),label)
                    self._layout_check(page,report,width,'modal/'+label,selector)
                    page.evaluate(close_script)
                if errors:report['issues'].append({'width':width,'kind':'console/page errors','messages':sorted(set(errors))})
                if outbound:report['issues'].append({'width':width,'kind':'nonlocal requests','count':len(outbound)})
                context.close()
        report['passed']=not report['issues']
        output=Path(os.environ.get('RELEASE_UI_REPORT','/workspace/artifacts/release-ui-report.json'))
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        self.assertFalse(report['issues'],json.dumps(report['issues'],ensure_ascii=False)[:16000])

    def _layout_check(self,page,report,width,label,modal_selector=None):
        size=page.evaluate('''() => ({viewport:innerWidth,document:document.documentElement.scrollWidth,body:document.body.scrollWidth,offenders:[...document.querySelectorAll('body *')].filter(el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&(r.right>innerWidth+2||r.left < -2)&&!el.closest('[hidden]')}).slice(0,8).map(el=>({tag:el.tagName,id:el.id,classes:String(el.className).slice(0,100),width:Math.round(el.getBoundingClientRect().width)}))})''')
        check={'width':width,'view':label,'documentWidth':size['document'],'bodyWidth':size['body']};report['checks'].append(check)
        if max(size['document'],size['body'])>width+2:
            report['issues'].append({**check,'kind':'horizontal overflow','offenders':size['offenders']})
        if modal_selector:
            rect=page.locator(modal_selector).bounding_box()
            if rect and (rect['x'] < -2 or rect['x']+rect['width']>width+2):
                report['issues'].append({**check,'kind':'modal outside viewport','rect':rect})

if __name__=='__main__':unittest.main()
