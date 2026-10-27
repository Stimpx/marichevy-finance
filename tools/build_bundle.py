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


MERCHANT_PLACEHOLDER = '/* V99_CHECKED_NEUTRAL_MERCHANT_CATALOG */'


def detach_merchant_catalog(source: str) -> tuple[str, str]:
    """Protect checked public brand names/artwork from family-name redaction.

    For example, the supermarket «Виктория» is not a family member. Only the
    exact generated public catalogue may bypass the family text replacements.
    """
    if '/* V99_MERCHANT_CATALOG_BEGIN' not in source:
        return source, ''
    from build_merchant_catalog import compile_catalog
    block = compile_catalog()
    if source.count(block) != 1 or MERCHANT_PLACEHOLDER in source:
        raise ValueError('Expected the exact checked neutral merchant catalogue')
    return source.replace(block, MERCHANT_PLACEHOLDER), block


def transform_demo(source: str) -> str:
    """Pure fail-closed transformation of known configuration/data blocks."""
    source, merchant_catalog = detach_merchant_catalog(source)
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
    # Replace complete personal display fields with coherent fictional values.
    # Redacting numeric fragments also swallowed spaces and damaged dates,
    # currency units and the functional 1/3-year chart controls.
    start = html.index('<div class="card credit-hero-card">')
    end = html.index('<section class="section" id="goals">', start)
    region = html[start:end]
    region = exact_sub(region,
        r'<div class="section-head"><div><h2>Ипотека · [^<]+</h2>[^\n]*',
        '<div class="section-head"><div><h2>Ипотека · Демобанк</h2><div class="hint">Учебный пример кредита. Все суммы и даты вымышлены.</div></div><span class="contract-badge">10% годовых</span></div>',
        'fictional loan heading')
    for element_id, value in {'loanPrincipal':'120 000 ₽', 'loanScheduledPayment':'11 000 ₽',
                              'loanEndDate':'15.12.2027'}.items():
        region = exact_sub(region, r'<b id="'+element_id+r'">[^<]*</b>',
            '<b id="'+element_id+'">'+value+'</b>', 'fictional '+element_id)
    region = exact_sub(region, r'<div class="credit-note" id="loanRateNote">[^<]*</div>',
        '<div class="credit-note" id="loanRateNote">Учебный график: 12 платежей по 11 000 ₽ с 15 января по 15 декабря 2027 года. Основной долг — 120 000 ₽, проценты — 12 000 ₽. Дополнительные расходы в примере не предусмотрены.</div>',
        'fictional loan note')
    region = exact_sub(region, r'<div class="hint">Вместо [^<]*</div>',
        '<div class="hint">Учебный график с ежемесячными платежами.</div>',
        'fictional loan chart hint')
    region = exact_sub(region, r'<h2>График платежей</h2><div class="hint">[^<]*</div>',
        '<h2>График платежей</h2><div class="hint">Дата — срок платежа в учебном графике. Суммы, проценты и остаток вымышлены.</div>',
        'fictional loan schedule hint')
    contract = [('Договор','Учебный пример'), ('Дата','15 декабря 2026'),
        ('Программа','Учебный кредит'), ('Срок','12 месяцев'), ('ПСК','10% годовых'),
        ('Полная стоимость','132 000 ₽'), ('Всего процентов по графику','12 000 ₽'),
        ('Платёж по графику','11 000 ₽'), ('Средний платёж','11 000 ₽'),
        ('Дата платежа','15-го числа по учебному графику'),
        ('Имущественное страхование','0 ₽'), ('Личное страхование','0 ₽'), ('Оценка','0 ₽')]
    region = exact_sub(region, r'<div class="card loan-contract-info">[^\n]*',
        '<div class="card loan-contract-info"><h2>Условия договора</h2><div class="contract-grid">'+
        ''.join('<div><span>'+label+'</span><b>'+value+'</b></div>' for label,value in contract)+
        '</div></div>', 'fictional contract conditions')
    html = html[:start]+region+html[end:]
    html = html.replace('4500000','120000').replace('85885','11000').replace('90000','11000').replace('2026-09-02','2026-12-15')
    for old, new in sorted(NAMES.items(), key=lambda p: -len(p[0])):
        html = html.replace(old, new).replace(old.upper(), new.upper()).replace(old.lower(), new.lower()).replace(old.title(), new.title())
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
 const stamp=new Date().toISOString(),parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()),pick=type=>parts.find(p=>p.type===type).value,date=pick('year')+'-'+pick('month')+'-'+pick('day');
 const entries=[['demo-income',80000,'income','Зарплата','Алексей','Демоработодатель'],['demo-food',285.40,'expense','Продукты','Общее','КБ'],['demo-pyaterochka',253.80,'expense','Продукты','Общее','Пятёрочка'],['demo-dixy',318.25,'expense','Продукты','Общее','Дикси'],['demo-vkusvill',425.70,'expense','Продукты','Общее','ВкусВилл'],['demo-pharmacy',239.90,'expense','Аптека и медицина','Общее','Горздрав'],['demo-diapers',1199.90,'expense','Дом','София','Детский мир'],['demo-clothes',975.25,'expense','Одежда','Елена','фамилия'],['demo-service',790.10,'expense','Развлечения','Алексей','OpenAI'],['demo-subscription',349.90,'expense','Подписки','Общее','Учебный онлайн-сервис'],['demo-work',260,'expense','Работа','Алексей','Учебный рабочий сервис'],['demo-unclear',225,'expense','Вкусняшки','Общее','КБ'],['demo-school',350,'expense','Школа и занятия','София','Школьная столовая'],['demo-pet',600,'expense','Животные','Бим','Зоомагазин']].map(([id,amount,type,category,who,store])=>({id,amount,type,category,who,beneficiary:who,store,date,pay:'Карта',comment:id==='demo-diapers'?'Подгузники для ребёнка':id==='demo-service'?'Подписка ChatGPT':id==='demo-unclear'?'':'Фиктивный пример',created_at:stamp,updated_at:stamp}));
 // Fictional monthly slices for the family dashboard; never copied from real history.
 entries.push(...[
  {id:'demo-pilates',amount:1450.50,category:'Спорт и здоровье',beneficiary:'Елена',store:'Учебная студия',comment:'Пилатес'},
  {id:'demo-vitamins',amount:650.25,category:'Спорт и здоровье',beneficiary:'Алексей',store:'Горздрав',comment:'Витамин D'},
  {id:'demo-glasses',amount:2150.75,category:'Аптека и медицина',beneficiary:'Елена',store:'Учебная оптика',comment:'Очки'},
  {id:'demo-taxi-one',amount:345.20,category:'Транспорт',subcategory:'Такси',beneficiary:'Елена',store:'Учебное такси',comment:'Поездка на работу'},
  {id:'demo-taxi-two',amount:420.15,category:'Транспорт',subcategory:'Такси',beneficiary:'Алексей',store:'Учебное такси',comment:'Поездка домой'},
  {id:'demo-hosting',amount:750.35,category:'Подписки',subcategory:'Хостинг и домены',beneficiary:'Алексей',store:'Учебный хостинг',comment:'Хостинг'},
  {id:'demo-gift',amount:995.45,category:'Подарки',beneficiary:'София',store:'Детский мир',comment:'Подарок на праздник'},
  {id:'demo-utilities',amount:1650.65,category:'ЖКХ',beneficiary:'Общее',store:'Учебные коммунальные услуги',comment:'Электричество'},
  {id:'demo-car',amount:1290.30,category:'Авто и транспорт',subcategory:'Бензин',beneficiary:'Алексей',store:'ЛУКОЙЛ',comment:'Заправка'},
  {id:'demo-split-unlinked',amount:460.80,category:'Кредит',subcategory:'Рассрочка / Сплит',beneficiary:'Общее',store:'Учебный Сплит',comment:'Платёж без привязки к графику'},
  {id:'demo-purpose-review',amount:399.40,category:'Аптека и медицина',beneficiary:'Елена',store:'Учебная студия',comment:'Пилатес'}
 ].map(e=>({type:'expense',date,pay:'Карта',who:e.beneficiary,created_at:stamp,updated_at:stamp,...e})));
 localStorage.setItem('marichevy_demo_state_v10',JSON.stringify({entries,intelligence:{budgets:[{id:'demo-old-budget',group:'Досуг и привычки',amount:3000,created_at:stamp,updated_at:stamp}]},settings:{loans:{loanBank:'Демобанк',loan1:11000},notifications:{enabled:false,telegram:false}}}));
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
 const banner=document.createElement('div');banner.textContent='ДЕМО · Вымышленные покупки с учебными ошибками · Без аккаунта';banner.style='position:sticky;top:0;z-index:1;background:#e8f0ff;color:#24467a;padding:10px;text-align:center;font:12px system-ui';document.body.prepend(banner);
 if(typeof v98OpenCategoryReview==='function'){const review=document.createElement('button');review.type='button';review.textContent='Проверить учебные категории';review.style='margin:6px 0 0 12px;min-height:44px;max-width:100%;padding:8px 12px;border:1px solid #b5c8ed;border-radius:10px;background:#fff;color:#24467a;font:inherit;cursor:pointer';review.addEventListener('click',()=>v98OpenCategoryReview());banner.append(review)}
 document.querySelectorAll('a[href^="mailto:"],a[href^="about:"],a[href^="tel:"]').forEach(a=>a.removeAttribute('href'));
})();</script>'''
    html = exact_sub(html, r'</body>', footer+'</body>', 'body end')
    for value in original_values:
        if value and value in html:
            raise ValueError('Original CONFIG value survived')
    for value in ['9946-WZ3/00067','1985-11-27','1988-12-04','2018-01-13','2026-05-17','2023-10-07','666991984','247264029','gmail.com','supabase.co','МАРИЧЕВ','Маричев','Сергей','Виктория','Алиса','Майя','алисы','Sergey','Victoria']:
        if value in html:
            raise ValueError('Personal marker survived transformation')
    return html.replace(MERCHANT_PLACEHOLDER, merchant_catalog)


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
    metadata=(json.dumps({'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'status':'NOT PUBLISHED','server_sync':'production protocol activation and coordinated release pending; current catalog, private restore and fictional staging evidence in docs/RELEASE_CANDIDATE.md'},sort_keys=True,indent=2)+'\n').encode()
    write_bundle(output/'safe-demo',{'OWNER_REVIEW_RU.md':(ROOT/'docs'/'OWNER_REVIEW_RU.md').read_bytes(),'BUILD.json':metadata,'index.html':demo.encode(),'favicon.svg':ICON.encode(),'_headers':('/*\n  Content-Security-Policy: '+CSP+'\n  Referrer-Policy: no-referrer\n').encode(),'README.txt':'НЕ ОПУБЛИКОВАНО. Откройте index.html или запустите локальный статический сервер. Только фиктивные данные. Изменения хранятся на этом устройстве; облако, Telegram и отправка отзывов отключены. Это не доказательство работы production или серверной синхронизации.\n'.encode()})
    filenames=['index.html','favicon.svg','favicon.ico','favicon-32.png','apple-touch-icon.png','CNAME']
    filenames += ['docs/SYNC_SERVER.md','docs/PR2_SYNC.md','docs/RELEASE_CANDIDATE.md',
                  'docs/RELEASE_RUNBOOK.md','docs/PRODUCTION_SCHEMA_FINDINGS.md',
                  'docs/OWNER_REVIEW_RU.md','docs/LOCAL_QUEUE_BACKUP_RU.md',
                  'docs/PRIVATE_RESTORE_ACCEPTANCE.md','docs/DEVICE_QUEUE_CAPTURE_MAC_RU.md',
                  'docs/CATEGORY_MODEL_RU.md','docs/HOSTING_PLAN_RU.md','docs/PRODUCT_FREE_PRO_RU.md',
                  'docs/PAYMENTS_PLAN_RU.md','docs/FEEDBACK_DELIVERY.md','docs/ACCOUNT_ACCESS_PLAN_RU.md','docs/UX_ACCEPTANCE_RU.md',
                  'docs/DEVICE_ACCEPTANCE_V97_RU.md','tools/check_touch_flows.py',
                  'tools/capture_local_queue.js',
                  'tools/export_private_server_backup.py','tools/verify_private_backup.py',
                  'tools/restore_private_backup.py','server/001_family_state_cas.sql',
                  'server/002_restrict_table_capabilities.sql','server/003_bound_membership_lookup.sql',
                  'server/activate_household.sql','server/rollback_household.sql']
    personal={name:(ROOT/name).read_bytes() for name in filenames}
    personal['BUILD.json']=metadata
    personal['INSTALL_PRIVATE.txt']='ЛИЧНАЯ УСТАНОВКА — НЕ ДЕМО — НЕ ОПУБЛИКОВАНО\nСодержит точную текущую конфигурацию личного клиента. Не распространять публично как демо. Ничего не развернуто автоматически.\nПеред ручной установкой: скачайте резервный JSON из действующего приложения; сохраните прежние index.html, иконки и CNAME отдельно. Проверьте кандидат на отдельном адресе и дождитесь разрешения владельца на production. CNAME включён только для сохранения личного адреса, не для публикации демо.\nОткат: верните сохранённые прежние статические файлы. Этот пакет не изменяет схему БД и не содержит экспорта семейных операций, сессий или токенов. Не импортируйте JSON автоматически.\nВНИМАНИЕ: НЕ УСТАНАВЛИВАТЬ КАК ОБЫЧНОЕ ОБНОВЛЕНИЕ. Новые облачные записи заблокированы, пока согласованный серверный CAS-протокол не проверен и не активирован. Изменения останутся локально в очереди. SQL и инструкции включены только для review/staging, не для автоматического выполнения. Рабочий Supabase не изменён. Серверная синхронизация требует отдельной проверки; готовность архива её не доказывает.\n'.encode()
    write_bundle(output/'personal-installation-PRIVATE',personal)
    print('Built safe-demo.zip and personal-installation-PRIVATE.zip (NOT PUBLISHED)')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-dir',type=Path,default=Path('/workspace/artifacts'));args=parser.parse_args();build(args.output_dir)
