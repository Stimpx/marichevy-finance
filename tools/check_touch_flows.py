#!/usr/bin/env python3
"""Offline fictional-demo device approximations. No production or external I/O.

Usage: python3 tools/check_touch_flows.py --require-v97 --report /tmp/touch-flows.json
Produces a source-bound JSON report; a successful run is Chromium evidence only.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import traceback

from playwright.sync_api import sync_playwright


PROFILES = (
    dict(name='desktop-keyboard', width=1280, height=900, touch=False),
    dict(name='touch-portrait', width=390, height=844, touch=True),
    dict(name='touch-landscape', width=844, height=390, touch=True),
    dict(name='touch-compact', width=320, height=740, touch=True),
    dict(name='touch-text150-reduced-motion', width=390, height=844,
         touch=True, text_scale=1.5, reduced_motion=True),
    dict(name='touch-inset-and-short-height-approximation', width=390,
         height=430, touch=True, inset_approximation=True),
)


class Checks:
    def __init__(self, page, profile, report):
        self.page, self.profile, self.report = page, profile, report
        self.dismiss_next_dialog = False
        self.dialogs = []

    def dialog(self, dialog):
        self.dialogs.append(dialog.message)
        if self.dismiss_next_dialog:
            self.dismiss_next_dialog = False
            dialog.dismiss()
        else:
            dialog.accept()

    @contextmanager
    def step(self, name):
        row = dict(profile=self.profile['name'], check=name)
        self.report['checks'].append(row)
        try:
            yield row
            row['status'] = 'passed'
        except Exception as exc:
            row.update(status='failed', error=f'{type(exc).__name__}: {exc}')
            self.report['failures'].append(row.copy())
            # Keep a layout failure in one dialog from causing spurious blocked
            # tap failures in every later, otherwise independent check.
            try:
                self.page.evaluate("if(document.getElementById('v96Calculator')?.open)v96CloseCalculator()")
            except Exception:
                pass

    def activate(self, locator):
        locator.scroll_into_view_if_needed()
        if self.profile['touch']:
            locator.tap()
        else:
            locator.click()

    def navigate(self, section):
        # Use actual displayed navigation; landscape may expose desktop side bar.
        button = self.page.locator(
            f'#nav button[data-page="{section}"]:visible,'
            f'#mobileNav button[data-page="{section}"]:visible').first
        if button.count():
            self.activate(button)
        else:
            # Settings/secondary pages use the existing More UI, not always a tab.
            self.page.evaluate('(name)=>go(name)', section)
        self.page.wait_for_function(
            '(name)=>document.getElementById(name).classList.contains("active")',
            arg=section)

    def readonly_snapshot(self):
        return self.page.evaluate('''() => ({state:JSON.stringify(state),
          storage:Object.fromEntries(Object.keys(localStorage).sort()
              .map(key=>[key,localStorage.getItem(key)]))})''')

    def entries(self):
        return self.page.evaluate('JSON.stringify(state.entries)')

    def stress(self):
        if self.profile.get('text_scale') and not self.page.evaluate('!!window.__v97TextScaleApplied'):
            enlarge_text(self.page,self.profile['text_scale'])
            self.page.evaluate('window.__v97TextScaleApplied=true')
        if self.profile.get('inset_approximation') and not self.page.locator('#v97TestInset').count():
            self.page.add_style_tag(content='#mobileNav{bottom:34px!important}.main{padding-bottom:150px!important}').evaluate("el=>el.id='v97TestInset'")

    def layout(self, view, selectors=()):
        row = self.page.evaluate('''selectors => {
          const dim={viewport:innerWidth,document:document.documentElement.scrollWidth,
            body:document.body.scrollWidth};
          const fields=selectors.map(selector=>{
            const el=document.querySelector(selector),r=el?.getBoundingClientRect();
            return {selector,visible:!!r?.width&&!!r?.height,left:r?.left,
              right:r?.right,height:r?.height};
          });
          const offenders=[...document.querySelectorAll('body *')].filter(el=>{
            const r=el.getBoundingClientRect(),s=getComputedStyle(el);
            return r.width>0&&r.height>0&&s.visibility!=='hidden'&&
              (r.right>innerWidth+2||r.left< -2)&&!el.closest('#mobileNav');
          }).slice(0,8).map(el=>({tag:el.tagName,id:el.id,
            classes:String(el.className).slice(0,100),text:el.textContent.trim().slice(0,60),
            parent:String(el.parentElement?.className||el.parentElement?.id||''),
            width:el.getBoundingClientRect().width,right:el.getBoundingClientRect().right}));
          return {...dim,fields,offenders};
        }''', list(selectors))
        self.report['layout'].append(dict(profile=self.profile['name'], view=view, **row))
        assert max(row['document'], row['body']) <= row['viewport'] + 2, row
        for field in row['fields']:
            assert field['visible'], field
            assert field['left'] >= -2 and field['right'] <= row['viewport'] + 2, field

    def unobscured(self, selector):
        node = self.page.locator(selector)
        node.scroll_into_view_if_needed()
        assert node.evaluate('''el=>{
          const r=el.getBoundingClientRect();
          const y=Math.max(1,Math.min(innerHeight-1,r.top+r.height/2));
          const front=document.elementFromPoint(r.left+r.width/2,y);
          return r.height>0&&el.contains(front);
        }'''), f'{selector} covered at its visible center'


def enlarge_text(page, scale):
    # Browser/OS text-size preferences are unavailable in headless Chromium.
    # Snapshot all font sizes before setting any: no inherited multiplication.
    page.evaluate('''scale=>{
      const nodes=[...document.querySelectorAll('body,body *')]
        .filter(el=>!['SCRIPT','STYLE','SVG','PATH'].includes(el.tagName));
      const sizes=nodes.map(el=>parseFloat(getComputedStyle(el).fontSize));
      nodes.forEach((el,i)=>{if(sizes[i])el.style.setProperty('font-size',sizes[i]*scale+'px','important')});
    }''', scale)


def quick_entry_checks(q):
    """Exercise actual buttons rather than only calling the prefill helpers."""
    page=q.page
    source_id='fictional-v97-repeat-source'
    merchant='Вымышленный повтор v97'
    def source_button(action):
        return page.locator('#historyBody').locator(
            f'button[data-record-action="{action}"][data-record-args*="{source_id}"]')
    with q.step('repeat button prepares today without saving or copying source metadata'):
        q.navigate('today')
        page.evaluate('''({id,merchant})=>{
          clearEntry();
          state.entries.push({id,type:'expense',amount:12.35,date:'2025-01-02',
            category:'Продукты',subcategory:'',who:'Не указано',beneficiary:'Общее',
            store:merchant,pay:'Карта',comment:'Исходник не изменять',
            created_at:'2025-01-02T12:00:00Z',updated_at:'2025-01-02T12:00:00Z',
            futureSyntheticMetadata:{preserve:true}});
          saveLocal();savePendingLocal();renderAll();
        }''',dict(id=source_id,merchant=merchant))
        before=q.entries()
        q.navigate('history')
        q.activate(page.get_by_role('button',name='Все даты',exact=True))
        q.activate(source_button('entry-repeat'))
        assert page.locator('#today').is_visible()
        assert page.evaluate('eDate.value===today()')
        assert page.locator('#eAmount').input_value()=='12,35'
        assert page.locator('#eStore').input_value()==merchant
        assert q.entries()==before
        assert 'новый черновик' in page.locator('#v97DraftStatus').inner_text()
        q.layout('repeat draft',('#eAmount','#eStore','#v90Save'))
    with q.step('cancel replacement preserves every dirty draft field and durable record'):
        page.locator('#eAmount').fill('99,50')
        page.locator('#eStore').fill('Черновик с другим магазином')
        page.evaluate("v90Extra.open=true")
        page.locator('#eComment').fill('Не терять при отмене')
        draft=page.evaluate('JSON.stringify(v97DraftFields())')
        q.navigate('history')
        before=q.readonly_snapshot()
        prompt_count=len(q.dialogs)
        q.dismiss_next_dialog=True
        q.activate(source_button('entry-repeat'))
        assert len(q.dialogs)==prompt_count+1 and 'черновик' in q.dialogs[-1].lower()
        assert page.evaluate('JSON.stringify(v97DraftFields())')==draft
        assert q.readonly_snapshot()==before
        q.navigate('today')
        assert page.locator('#eAmount').input_value()=='99,50'
        # A separate explicit repeat then Save is a new operation with a new ID.
        page.evaluate('clearEntry()')
        q.navigate('history')
        q.activate(source_button('entry-repeat'))
        original=page.evaluate('(id)=>JSON.stringify(state.entries.find(e=>e.id===id))',source_id)
        count=page.evaluate('state.entries.length')
        q.activate(page.locator('#v90Save'))
        page.wait_for_function('(n)=>state.entries.length===n+1',arg=count)
        created=page.evaluate('state.entries.at(-1)')
        assert created['id']!=source_id and created['amount']==12.35
        assert page.evaluate('state.entries.at(-1).date===today()')
        assert 'futureSyntheticMetadata' not in created
        assert not any(key in created for key in ('installmentId','installmentPartId','recurringId','paymentKey'))
        assert page.evaluate('(id)=>JSON.stringify(state.entries.find(e=>e.id===id))',source_id)==original
    with q.step('favorite actual form and touch buttons never create an operation by selection'):
        page.evaluate('clearEntry()')
        q.navigate('history')
        before=q.entries()
        q.activate(source_button('favorite-from-entry'))
        assert page.locator('#v97FavoriteEditor').is_visible()
        assert q.entries()==before
        page.locator('#v97FavoriteName').fill('Вымышленный вариант v97')
        q.layout('favorite editor',('#v97FavoriteName',))
        q.activate(page.get_by_role('button',name='Сохранить избранное',exact=True))
        page.wait_for_function('v97FavoriteSaving===false && v97FavoriteRows().length===1')
        assert q.entries()==before
        favorite=page.evaluate('v97FavoriteRows()[0]')
        assert favorite['amount']==12.35 and favorite['name']=='Вымышленный вариант v97'
        assert 'futureSyntheticMetadata' not in favorite
        page.reload(wait_until='load')
        page.wait_for_function('typeof v97FavoriteRows==="function"')
        q.stress()
        assert page.evaluate('(id)=>v97FavoriteRows().some(f=>f.id===id)',favorite['id'])
        q.navigate('today')
        page.evaluate('clearEntry()')
        q.activate(page.locator('#v97FavoriteList').get_by_role('button',name='Заполнить',exact=True))
        assert page.locator('#eAmount').input_value()=='12,35'
        assert page.evaluate('eDate.value===today()')
        assert q.entries()==before
        # Removing a favorite removes no historical or freshly saved operation.
        q.activate(page.locator('#v97FavoriteList').get_by_role('button',name='Убрать',exact=True))
        page.wait_for_function('v97FavoriteSaving===false && v97FavoriteRows().length===0')
        assert q.entries()==before
        assert page.evaluate('(id)=>!!v84Data().deleted.favorites[id]',favorite['id'])
        page.evaluate('clearEntry()')
    with q.step('linked regular payment refuses repeat without changing history or draft'):
        page.evaluate('''() => {
          state.entries.push({id:'fictional-v97-linked',type:'expense',date:today(),amount:3.25,
            category:'Продукты',who:'Общее',beneficiary:'Общее',store:'Вымышленный связанный v97',
            comment:'',recurringId:'fictional-recurring',recurringPeriod:month()});
          saveLocal();savePendingLocal();renderAll();clearEntry();
        }''')
        q.navigate('history')
        before=q.readonly_snapshot()
        draft=page.evaluate('JSON.stringify(v97DraftFields())')
        q.dismiss_next_dialog=True
        button=page.locator('#historyBody tr').filter(has_text='Вымышленный связанный v97').locator('button[data-record-action="entry-repeat"]')
        q.activate(button)
        assert 'регулярный' in q.dialogs[-1].lower()
        assert q.readonly_snapshot()==before
        assert page.evaluate('JSON.stringify(v97DraftFields())')==draft


def run_profile(browser, base, profile, report, temporary):
    context = browser.new_context(viewport=dict(width=profile['width'], height=profile['height']),
        is_mobile=profile['touch'], has_touch=profile['touch'],
        device_scale_factor=3 if profile['touch'] else 1,
        reduced_motion='reduce' if profile.get('reduced_motion') else 'no-preference',
        timezone_id='Europe/Moscow', service_workers='block', accept_downloads=True)
    outbound, errors = [], []
    def route_request(route):
        if route.request.url.startswith(base):
            route.continue_()
        else:
            outbound.append(route.request.url)
            route.abort()
    context.route('**/*', route_request)
    page = context.new_page()
    page.set_default_timeout(5000)
    page.on('pageerror', lambda error: errors.append(str(error)))
    # Harmless destructive confirmations are not dismissed silently in tests.
    # Each test checks the resulting draft/data state independently.
    q = Checks(page, profile, report)
    page.on('dialog', q.dialog)
    try:
        page.goto(base, wait_until='load')
        page.wait_for_function("typeof state==='object' && !appRoot.classList.contains('auth-locked')")
        assert page.evaluate('session===null && CONFIG.url==="" && CONFIG.household==="offline-demo"')
        q.stress()
        with q.step('home layout and actual controls'):
            q.navigate('home')
            q.layout('home', ('#home .hero',))
            visible_actions = page.locator('#home button:visible')
            assert visible_actions.count() > 0
            # Record touch target dimensions without pretending all tiny links
            # are blockers; primary Save is asserted separately below.
            report['touch_targets'].append(dict(profile=profile['name'],
                items=visible_actions.evaluate_all('els=>els.slice(0,12).map(e=>({text:e.textContent.trim().slice(0,60),height:e.getBoundingClientRect().height,width:e.getBoundingClientRect().width}))')))
            if profile.get('reduced_motion'):
                assert page.evaluate('matchMedia("(prefers-reduced-motion: reduce)").matches')
                assert page.locator('#home .hero').evaluate('el=>getComputedStyle(el).transitionDuration') == '0s'
        with q.step('dirty entry survives navigation without saving'):
            q.navigate('today')
            page.evaluate("clearEntry();v90Choose('Продукты')")
            baseline = q.entries()
            page.locator('#eAmount').fill('17,25')
            page.locator('#eStore').fill('Вымышленная лавка v97')
            page.evaluate("document.getElementById('v90Extra').open=true")
            page.locator('#eComment').fill('Черновик не становится расходом сам')
            expected = page.evaluate("[eAmount.value,eStore.value,eComment.value,eCategory.value,eBeneficiary.value,eDate.value]")
            q.navigate('home')
            assert q.entries() == baseline
            q.navigate('today')
            assert page.evaluate("[eAmount.value,eStore.value,eComment.value,eCategory.value,eBeneficiary.value,eDate.value]") == expected
            assert q.entries() == baseline
            page.evaluate("document.getElementById('v90Extra').open=false")
            q.layout('today draft', ('#eAmount','#v90Search','#eBeneficiary','#eStore','#v90Save'))
            q.unobscured('#v90Save')
            assert page.locator('#v90Save').bounding_box()['height'] >= 40
        with q.step('denied clipboard retains amount and provides native-menu fallback'):
            before = q.readonly_snapshot()
            page.evaluate('''() => Object.defineProperty(navigator,'clipboard',{
              configurable:true,value:{readText:async()=>{throw Error('DENIED_TEST_ONLY')},
                writeText:async()=>{throw Error('DENIED_TEST_ONLY')}}})''')
            q.activate(page.get_by_role('button', name='Вставить сумму', exact=True))
            assert page.locator('#eAmount').input_value() == '17,25'
            assert 'Вставить' in page.locator('#eAmountClipboardStatus').inner_text()
            q.activate(page.get_by_role('button', name='Копировать сумму', exact=True))
            assert 'Копировать' in page.locator('#eAmountClipboardStatus').inner_text()
            assert page.locator('#eAmount').evaluate('e=>e.value.slice(e.selectionStart,e.selectionEnd)') == '17,25'
            assert 'DENIED_TEST_ONLY' not in page.locator('#eAmountClipboardStatus').inner_text()
            assert q.readonly_snapshot() == before
        with q.step('calculator keyboard and focus return without creating operation'):
            before = q.entries()
            button = page.get_by_role('button', name='Калькулятор', exact=True)
            button.focus()
            page.keyboard.press('Enter')
            assert page.locator('#v96Calculator').is_visible()
            assert page.locator('#v96CalcExpression').evaluate('e=>document.activeElement===e')
            page.locator('#v96CalcExpression').fill('0,10+0,20')
            assert page.locator('#v96CalcResult').input_value() == '0,30'
            q.layout('calculator', ('#v96Calculator','#v96CalcExpression','#v96CalcApply'))
            page.keyboard.press('Tab')
            assert page.evaluate('v96Calculator.contains(document.activeElement)')
            page.keyboard.press('Escape')
            assert not page.locator('#v96Calculator').is_visible()
            assert page.evaluate('document.activeElement!==document.body && !!document.activeElement.getBoundingClientRect().height')
            assert q.entries() == before
            assert page.locator('#eAmount').input_value() == '17,25'
        with q.step('explicit save persists cents and old history after reload'):
            previous = json.loads(q.entries())
            q.activate(page.locator('#v90Save'))
            page.wait_for_function('(count)=>state.entries.length===count+1', arg=len(previous))
            saved = page.evaluate('JSON.parse(JSON.stringify(state.entries.at(-1)))')
            assert saved['amount'] == 17.25 and saved['store'] == 'Вымышленная лавка v97', saved
            assert page.evaluate('JSON.stringify(state.entries.slice(0,-1))') == json.dumps(previous,ensure_ascii=False,separators=(',',':'))
            page.reload(wait_until='load')
            page.wait_for_function('typeof state==="object"')
            q.stress()
            persisted = page.evaluate('(id)=>state.entries.find(e=>e.id===id)',saved['id'])
            assert persisted == saved, (saved,persisted)
            assert page.evaluate('session===null')
            q.navigate('today')
        with q.step('rapid double-save appends once; no generated payment linkage'):
            before = page.evaluate('state.entries.length')
            page.evaluate("clearEntry();v90Choose('Продукты')")
            page.locator('#eAmount').fill('23,45')
            page.locator('#eStore').fill('Только синтетический двойной щелчок')
            page.evaluate('v90Save.click();v90Save.click()')
            page.wait_for_function('(count)=>state.entries.length===count+1',arg=before)
            page.wait_for_function('v90Saving===false')
            assert page.evaluate('state.entries.length') == before+1
            entry=page.evaluate('state.entries.at(-1)')
            assert entry['amount'] == 23.45
            assert not any(key in entry for key in ('installmentId','partId','recurringId','paymentKey'))
            assert page.evaluate('new Set(state.entries.map(e=>e.id)).size===state.entries.length')
        available=page.evaluate('typeof v97RepeatEntry==="function" && typeof v97FavoriteRows==="function"')
        report.setdefault('v97_features',[]).append(dict(profile=profile['name'],available=available))
        if available:
            quick_entry_checks(q)
        with q.step('read-only full copy and retained manual touch download'):
            q.navigate('settings')
            # Only synthetic local records and a session sentinel are seeded.
            page.evaluate('''() => {
              localStorage.setItem(KEYS.state+'_cloud_conflict_v1','{"syntheticConflict":"v97"}');
              localStorage.setItem(KEYS.session,'DO_NOT_EXPORT_SYNTHETIC_SESSION');
              window.__blockedDownloads=0;
              HTMLAnchorElement.prototype.click=function(){window.__blockedDownloads++};
            }''')
            before=q.readonly_snapshot()
            q.activate(page.get_by_role('button',name='↓ Полная копия устройства',exact=True))
            page.wait_for_function('window.__blockedDownloads>0')
            link=page.get_by_role('link',name='Скачать подготовленную копию устройства',exact=True)
            assert link.is_visible()
            with page.expect_download() as pending:
                q.activate(link)
            path=Path(temporary)/f'{profile["name"]}-fictional-device.json'
            pending.value.save_as(path)
            capture=json.loads(path.read_text())
            assert capture['format']=='marichevy-local-queue-capture-v1'
            assert capture['session_included'] is False and capture['server_backup_included'] is False
            assert capture['memory_state_json']==before['state']
            records={record['key']:record['raw'] for record in capture['records']}
            keys=page.evaluate('({pending:KEYS.pending,conflict:KEYS.state+"_cloud_conflict_v1",session:KEYS.session})')
            assert records[keys['pending']]==before['storage'][keys['pending']]
            assert records[keys['conflict']]=='{"syntheticConflict":"v97"}'
            assert keys['session'] not in records
            assert 'DO_NOT_EXPORT_SYNTHETIC_SESSION' not in path.read_text()
            for record in capture['records']:
                assert record['sha256_utf16le']==hashlib.sha256(record['raw'].encode('utf-16le',errors='surrogatepass')).hexdigest()
            assert q.readonly_snapshot()==before
            assert link.is_visible()
        with q.step('no real authentication, outbound requests, or uncaught errors') as row:
            row.update(outbound=outbound,page_errors=errors)
            assert page.evaluate('session===null')
            assert outbound==[],outbound
            assert errors==[],errors
    finally:
        context.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('/workspace/marichevy-finance'))
    parser.add_argument('--html',type=Path,help='Optional explicitly prepared candidate source; default ROOT/index.html')
    parser.add_argument('--report',type=Path,default=Path('/tmp/v97-device-report.json'))
    parser.add_argument('--profile',action='append',choices=[p['name'] for p in PROFILES],help='Run only selected profile; repeat option for several')
    parser.add_argument('--require-v97',action='store_true',help='Fail if integrated repeat/favorites APIs are missing')
    args=parser.parse_args()
    root=args.root.resolve()
    sys.path.insert(0,str(root/'tools'))
    import build_bundle
    source_path=args.html.resolve() if args.html else root/'index.html'
    source=source_path.read_bytes()
    profiles=tuple(p for p in PROFILES if not args.profile or p['name'] in args.profile)
    report=dict(status='running',source_path=str(source_path),source_sha256=hashlib.sha256(source).hexdigest(),
        recorded_at=datetime.now(timezone.utc).isoformat(),profiles=list(profiles),
        checks=[],failures=[],layout=[],touch_targets=[],
        limitations=[
          'Chromium on Linux only; touch/viewport emulation is not real iPhone, Safari, Android or Yandex.',
          'No WebKit install attempted; previous CDN restrictions are not bypassed.',
          '150% font styling is a reflow stress test, not OS/browser accessibility text-size validation.',
          '34px bottom inset and 390x430 viewport are approximations, not iOS safe-area or on-screen keyboard.',
          'No authentication, production backend, mail, payment, cloud sync or real financial data.',
          'Draft navigation is checked; unsaved draft survival across full reload is not implied.',
          'Repeat/favorites checks run only when their actual implementation is present; v97_features records availability.',
        ])
    with tempfile.TemporaryDirectory(prefix='fictional-v97-devices-') as temporary:
        demo=Path(temporary)/'demo';demo.mkdir()
        (demo/'index.html').write_text(build_bundle.transform_demo(source.decode()))
        (demo/'favicon.svg').write_text(build_bundle.ICON)
        class Handler(SimpleHTTPRequestHandler):
            def log_message(self,*args):pass
            def end_headers(self):
                self.send_header('Content-Security-Policy',build_bundle.CSP)
                super().end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(demo)))
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        base=f'http://127.0.0.1:{server.server_port}/'
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
                report['browser']=dict(engine='Chromium',version=browser.version,platform='Linux')
                for profile in profiles:
                    try:
                        run_profile(browser,base,profile,report,temporary)
                    except Exception as exc:
                        report['failures'].append(dict(profile=profile['name'],check='profile startup',
                            status='failed',error=f'{type(exc).__name__}: {exc}'))
                    print(profile['name'], 'complete', flush=True)
                browser.close()
        finally:
            server.shutdown();server.server_close();worker.join()
    report['source_still_same']=hashlib.sha256(source_path.read_bytes()).hexdigest()==report['source_sha256']
    if args.require_v97 and (len(report.get('v97_features',[]))!=len(profiles) or not all(row['available'] for row in report.get('v97_features',[]))):
        report['failures'].append(dict(check='required integrated v97 features',status='failed',error='Repeat/favorites not available in every profile'))
    report['status']='passed' if not report['failures'] and report['source_still_same'] else 'failed'
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'],source_sha256=report['source_sha256'],
        checks=len(report['checks']),failures=len(report['failures']),report=str(args.report)),ensure_ascii=False))
    for failure in report['failures']:
        print(json.dumps(failure,ensure_ascii=False))
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
