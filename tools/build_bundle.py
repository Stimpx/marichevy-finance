#!/usr/bin/env python3
"""Build private installation and offline fictional demo archives; never publish."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile
from serve_staging import CONFIG_RE

ROOT = Path(__file__).resolve().parents[1]
CSP = "default-src 'self' data: blob:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'"
ICON = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="#315fc7"/><path d="M14 30 32 16 50 30M20 29v20h24V29M28 49V36h8v13" fill="none" stroke="white" stroke-width="4"/></svg>'
# Explicit source-to-fiction mapping; generated demo only, never changes personal state.
NAMES = {'Сергеем':'Алексеем','Сергея':'Алексея','Сергею':'Алексею','Сергее':'Алексее','Сергей':'Алексей','Викторией':'Еленой','Виктории':'Елены','Викторию':'Елену','Виктория':'Елена','Алисы':'Софии','Алисе':'Софии','Алису':'Софию','Алиса':'София','Майи':'Ильи','Майе':'Илье','Майю':'Илью','Майя':'Илья','Денни':'Рыжик','Дени':'Рыжик','Макса':'Бима','Макс':'Бим','Маричевы':'Семейный Банк · демо','Маричевых':'демосемьи','Маричев':'Демосемья','marichev.coach@gmail.com':'alexey@example.invalid','chebotareva.web@gmail.com':'elena@example.invalid','sergey':'alexey','sergei':'alexey','serg':'alex','victoria':'elena','viktor':'elena','vika':'elena','виктор':'елена','серг':'алекс','УралСиба':'Демобанка','УралСиб':'Демобанк'}


def exact_sub(source: str, pattern: str, replacement: str, label: str) -> str:
    result, count = re.subn(pattern, lambda _: replacement, source, flags=re.S)
    if count != 1:
        raise ValueError(f'Expected one {label}; found {count}. Review transform before shipping.')
    return result


def transform_demo(source: str) -> str:
    """Pure fail-closed transformation of known configuration/data blocks."""
    config = CONFIG_RE.search(source)
    if not config or len(CONFIG_RE.findall(source)) != 1:
        raise ValueError('Expected exactly one CONFIG block')
    original_values = re.findall(r"(?:url|key|household):'([^']*)'", config.group())
    html = CONFIG_RE.sub("const CONFIG=Object.freeze({url:'',key:'',household:'offline-demo'});", source)
    html = exact_sub(html, r'const TELEGRAM_CHAT_IDS=Object\.freeze\(\{[^\n]*\}\);', 'const TELEGRAM_CHAT_IDS=Object.freeze({sergey:"",victoria:""});', 'Telegram IDs')
    births = "const FAMILY_BIRTHS=[{name:'Алексей',date:'1990-04-12',time:'',group:'Семья',note:''},{name:'Елена',date:'1992-07-21',time:'',group:'Семья',note:''},{name:'София',date:'2015-03-16',time:'',group:'Семья',note:''},{name:'Илья',date:'2020-08-09',time:'',group:'Семья',note:''}];"
    html = exact_sub(html, r'const FAMILY_BIRTHS=\[.*?\];', births, 'family dates')
    html = exact_sub(html, r'const FAMILY_WEDDING=\{[^\n]*\};', "const FAMILY_WEDDING={id:'family-wedding',name:'Годовщина свадьбы',date:'2012-06-15',group:'Семья',kind:'wedding',family:true,note:''};", 'wedding')
    rows = [[i, f'15.{i:02d}.2027', 10000, 1000, 11000, 120000-i*10000] for i in range(1,13)]
    html = exact_sub(html, r'const BANK_LOAN_SCHEDULE=\[.*?\];', 'const BANK_LOAN_SCHEDULE='+json.dumps(rows)+';', 'loan schedule')
    info = dict(contractDate='15.12.2026',principal=120000,rate=.1,scheduledPayment=11000,averagePayment=11000,psk=10,fullCost=132000,totalPrincipal=120000,totalInterest=12000,creditPayments=132000,appraisal=0,propertyInsurance=0,personalInsurance=0,endDate='15.12.2027')
    html = exact_sub(html, r'const BANK_LOAN_INFO=Object\.freeze\(\{.*?\}\);', 'const BANK_LOAN_INFO=Object.freeze('+json.dumps(info)+');', 'loan info')
    # Preserve functional tags/IDs while clearing the personal contract's static prose.
    start = html.index('<div class="card credit-hero-card">')
    end = html.index('<section class="section" id="goals">', start)
    region = html[start:end]
    region = re.sub(r'>([^<>]+)<', lambda m: '>'+re.sub(r'\d[\d\s.,%№/A-Z-]*', '—', m[1])+'<', region)
    html = html[:start]+region+html[end:]
    html = html.replace('4500000','120000').replace('85885','11000').replace('90000','11000').replace('2026-09-02','2026-12-15')
    for old, new in sorted(NAMES.items(), key=lambda p: -len(p[0])):
        html = html.replace(old, new).replace(old.upper(), new.upper())
    for old,new in {'alice':'sofia','maya':'ilya','deni':'ginger','marichevy-finance':'family-demo','11.10.2026':'15.01.2027','2026-09-01':'2026-12-15','2041-09-02':'2027-12-15'}.items():
        html=html.replace(old,new)
    html = html.replace('marichevy_', 'marichevy_demo_')
    html = html.replace('class="brand-heading">Семейный Банк · демо<small>Траты.Банк', 'class="brand-heading">Семейный Банк<small>Демоверсия')
    # Disable every remote literal, retaining only the SVG namespace (not a request).
    html = re.sub(r'https?://[^\s\x27"<>`]+', lambda m: m[0] if m[0]=='http://www.w3.org/2000/svg' else 'about:blank', html)
    html = re.sub(r'<link\b[^>]*href=["\x27](?:about:blank|[^"\x27]*\.png|[^"\x27]*\.ico)[^>]*>', '', html)
    guard = '''<meta http-equiv="Content-Security-Policy" content="'''+CSP+'''">
<link rel="icon" href="favicon.svg"><script>
(() => {
 const denied=()=>{throw new Error('Демо: интеграции отключены')};
 window.fetch=()=>Promise.reject(new Error('Демо: сеть отключена'));
 window.WebSocket=window.EventSource=window.Worker=window.SharedWorker=window.RTCPeerConnection=window.WebTransport=denied;
 XMLHttpRequest.prototype.open=denied;
 navigator.sendBeacon=()=>false; navigator.share=()=>Promise.reject(new Error('Демо: отправка отключена')); window.open=()=>null;
 if(navigator.serviceWorker)navigator.serviceWorker.register=()=>Promise.reject(new Error('Демо'));
 try {localStorage.removeItem('marichevy_demo_session_v10');
 if(localStorage.getItem('marichevy_demo_state_v10')===null && localStorage.getItem('marichevy_demo_pending_v10')===null && !Object.keys(localStorage).some(k=>k.startsWith('marichevy_demo_')&&/backup|corrupt/.test(k))) {
 const stamp=new Date().toISOString(),date=new Date().toISOString().slice(0,10);
 const entries=[['demo-income',80000,'income','Зарплата','Алексей','Демоработодатель'],['demo-food',1250,'expense','Продукты','Общее','Магазин у дома'],['demo-school',350,'expense','Школа и занятия','София','Школьная столовая'],['demo-pet',600,'expense','Животные','Бим','Зоомагазин']].map(([id,amount,type,category,who,store])=>({id,amount,type,category,who,beneficiary:who,store,date,pay:'Карта',comment:'Фиктивный пример',created_at:stamp,updated_at:stamp}));
 localStorage.setItem('marichevy_demo_state_v10',JSON.stringify({entries,settings:{loans:{loanBank:'Демобанк',loan1:11000},notifications:{enabled:false,telegram:false}}}));
 }}catch(_){}
})();</script>'''
    html = exact_sub(html, r'<head>', '<head>'+guard, 'head')
    footer = '''<script>
(()=>{session=null;stopCloudSync();startCloudSync=()=>{};loadWeather=async()=>{};
 sendTelegramMessage=async()=>{throw new Error('Демо: отключено')};
 v88SendFeedback=async()=>{toast('Демо: отправка отключена')};
 v881OpenEmail=()=>{toast('Демо: отправка отключена');return false};
 v88ShareFeedback=async()=>{toast('Демо: отправка отключена')};
 testTelegram=async()=>{toast('Демо: Telegram отключён')};
 document.querySelectorAll('.telegram-settings-card button,.telegram-settings-card input,#loginBtn').forEach(el=>{el.disabled=true;el.title='Демо: интеграция отключена'});
 showApp();setStatus('ДЕМО · только на устройстве',false);
 const authButton=document.getElementById('authBtn');if(authButton){authButton.disabled=true;authButton.textContent='Без аккаунта'}
 const status=document.getElementById('syncStatus');if(status)status.textContent='ДЕМО · фиктивная семья · облако и интеграции отключены';
 const banner=document.createElement('div');banner.textContent='ДЕМО · Фиктивные данные · Не опубликовано · Реальный аккаунт не нужен';banner.style='position:sticky;top:0;z-index:999;background:#e8f0ff;color:#24467a;padding:10px;text-align:center;font:12px system-ui';document.body.prepend(banner);
 document.querySelectorAll('a[href^="mailto:"],a[href^="about:"],a[href^="tel:"]').forEach(a=>a.removeAttribute('href'));
})();</script>'''
    html = exact_sub(html, r'</body>', footer+'</body>', 'body end')
    for value in original_values:
        if value and value in html:
            raise ValueError('Original CONFIG value survived')
    for value in ['9946-WZ3/00067','1985-11-27','1988-12-04','2018-01-13','2026-05-17','2023-10-07','666991984','247264029','gmail.com','supabase.co','МАРИЧЕВ','Маричев','Сергей','Виктория','Алиса','Майя']:
        if value in html:
            raise ValueError('Personal marker survived transformation')
    return html


def write_bundle(directory: Path, files: dict[str, bytes]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    unexpected={str(path.relative_to(directory)) for path in directory.rglob('*') if path.is_file()} - set(files) - {'MANIFEST.json'}
    if unexpected:
        raise ValueError('Output contains unexpected files; use a fresh directory before serving or distributing')
    manifest = {name:hashlib.sha256(body).hexdigest() for name,body in sorted(files.items())}
    files = {**files,'MANIFEST.json':(json.dumps(manifest,indent=2,sort_keys=True)+'\n').encode()}
    for name, body in files.items():
        (directory/name).parent.mkdir(parents=True,exist_ok=True)
        (directory/name).write_bytes(body)
    with zipfile.ZipFile(directory.with_suffix('.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
        for name, body in sorted(files.items()):
            entry=zipfile.ZipInfo(name,(2020,1,1,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED;entry.external_attr=0o600<<16
            archive.writestr(entry,body)


def build(output: Path) -> None:
    output=output.resolve()
    if output==ROOT or ROOT in output.parents:
        raise ValueError('Output must be outside repository')
    output.mkdir(parents=True,exist_ok=True)
    (output/'expense-proposal.html').write_bytes((ROOT/'tools'/'expense_proposal.html').read_bytes())
    source=(ROOT/'index.html').read_text()
    demo=transform_demo(source)
    metadata=(json.dumps({'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'status':'NOT PUBLISHED','server_sync':'production schema/RLS/backup/activation pending; see source-bound staging evidence in docs/RELEASE_CANDIDATE.md'},sort_keys=True,indent=2)+'\n').encode()
    write_bundle(output/'safe-demo',{'OWNER_REVIEW_RU.md':(ROOT/'docs'/'OWNER_REVIEW_RU.md').read_bytes(),'BUILD.json':metadata,'index.html':demo.encode(),'favicon.svg':ICON.encode(),'_headers':('/*\n  Content-Security-Policy: '+CSP+'\n  Referrer-Policy: no-referrer\n').encode(),'README.txt':'НЕ ОПУБЛИКОВАНО. Откройте index.html или запустите локальный статический сервер. Только фиктивные данные. Изменения хранятся на этом устройстве; облако, Telegram и отправка отзывов отключены. Это не доказательство работы production или серверной синхронизации.\n'.encode()})
    filenames=['index.html','favicon.svg','favicon.ico','favicon-32.png','apple-touch-icon.png','CNAME']
    filenames += ['docs/SYNC_SERVER.md','docs/PR2_SYNC.md','docs/RELEASE_CANDIDATE.md','docs/OWNER_REVIEW_RU.md','server/001_family_state_cas.sql','server/activate_household.sql','server/rollback_household.sql']
    personal={name:(ROOT/name).read_bytes() for name in filenames}
    personal['BUILD.json']=metadata
    personal['INSTALL_PRIVATE.txt']='ЛИЧНАЯ УСТАНОВКА — НЕ ДЕМО — НЕ ОПУБЛИКОВАНО\nСодержит точную текущую конфигурацию личного клиента. Не распространять публично как демо. Ничего не развернуто автоматически.\nПеред ручной установкой: скачайте резервный JSON из действующего приложения; сохраните прежние index.html, иконки и CNAME отдельно. Проверьте кандидат на отдельном адресе и дождитесь разрешения владельца на production. CNAME включён только для сохранения личного адреса, не для публикации демо.\nОткат: верните сохранённые прежние статические файлы. Этот пакет не изменяет схему БД и не содержит экспорта семейных операций, сессий или токенов. Не импортируйте JSON автоматически.\nВНИМАНИЕ: НЕ УСТАНАВЛИВАТЬ КАК ОБЫЧНОЕ ОБНОВЛЕНИЕ. Новые облачные записи заблокированы, пока согласованный серверный CAS-протокол не проверен и не активирован. Изменения останутся локально в очереди. SQL и инструкции включены только для review/staging, не для автоматического выполнения. Рабочий Supabase не изменён. Серверная синхронизация требует отдельной проверки; готовность архива её не доказывает.\n'.encode()
    write_bundle(output/'personal-installation-PRIVATE',personal)
    print('Built safe-demo.zip and personal-installation-PRIVATE.zip (NOT PUBLISHED)')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-dir',type=Path,default=Path('/workspace/artifacts'));args=parser.parse_args();build(args.output_dir)
