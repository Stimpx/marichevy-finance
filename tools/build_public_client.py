#!/usr/bin/env python3
"""Generate the public, unconfigured full ledger from the private UI source.

This file only reads index.html.  The generated template has no account, family,
contract or integration configuration.  ledger.js supplies a verified scope and
owns authentication; the personal client and its storage are never modified.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.parse import quote
from build_bundle import ICON, MERCHANT_PLACEHOLDER, detach_merchant_catalog, exact_sub, transform_demo
from serve_staging import CONFIG_RE

ROOT = Path(__file__).resolve().parents[1]
CSP = ("default-src 'self' data: blob:; script-src 'self' 'unsafe-inline'; "
       "style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
       "img-src 'self' data: blob:; connect-src 'self'; form-action 'none'; "
       "base-uri 'none'; object-src 'none'")
RUNTIME_MARKER = '<script src="/ledger.js" data-finance-runtime></script>'
CONFIG_MARKER = 'window.__FINANCE_BRIDGE__.config'
STORAGE_MARKER = '__FINANCE_STORAGE__'


def remove_demo_wrappers(html: str) -> str:
    """Remove exactly the generator's network/fixture and offline-auth wrappers."""
    guard = '<meta http-equiv="Content-Security-Policy"'
    footer = '<script>\n(()=>{session=null;stopCloudSync();startCloudSync=()=>{};'
    if html.count(guard) != 1 or html.count(footer) != 1:
        raise ValueError('Demo wrappers changed; review public transformation')
    start = html.index(guard)
    end = html.index('</script>', start) + len('</script>')
    block = html[start:end]
    if "window.fetch=()=>Promise.reject" not in block or "localStorage.setItem('marichevy_demo_state_v10'" not in block:
        raise ValueError('Unexpected demo fixture/network wrapper')
    html = html[:start] + html[end:]
    start = html.index(footer)
    end = html.index('</script>', start) + len('</script>')
    block = html[start:end]
    if "showApp();setStatus('ДЕМО" not in block or 'testTelegram=async()=>' not in block:
        raise ValueError('Unexpected demo authentication wrapper')
    return html[:start] + html[end:]


def replace_function(html: str, name: str, replacement: str) -> str:
    """Replace a known top-level function without accidentally matching callers."""
    pattern = r'(?:async )?function ' + re.escape(name) + r'\([^\n]*?\)\{.*?\n\}'
    return exact_sub(html, pattern, replacement, 'function ' + name)


def transform_public(source: str) -> str:
    html = remove_demo_wrappers(transform_demo(source))
    html, merchant_catalog = detach_merchant_catalog(html)
    # The source embeds personal installation artwork as data URLs too.
    html = re.sub(r'<link\b[^>]*rel=["\x27](?:icon|apple-touch-icon)["\x27][^>]*>', '', html)
    html, count = CONFIG_RE.subn('const CONFIG=Object.freeze('+CONFIG_MARKER+');', html)
    if count != 1:
        raise ValueError('Expected one public CONFIG')
    # Every storage key in the delivered application, including archives and
    # quarantine suffixes, is scoped before any of the child scripts execute.
    html = html.replace('marichevy_demo_', STORAGE_MARKER)
    html = re.sub(r"(['\"])__FINANCE_STORAGE__([^'\"\r\n]*)\1",
        lambda match: '(window.__FINANCE_BRIDGE__.namespace+'+json.dumps(match[2])+')', html)
    if STORAGE_MARKER in html:
        raise ValueError('Unscoped public storage marker survived')
    html = exact_sub(html, r'const PEOPLE=\[[^\n]*\];',
        "const PEOPLE=[...new Set([...window.__FINANCE_BRIDGE__.people,'Общее'])];", 'people')
    html = exact_sub(html, r'const INCOME_PEOPLE=\[[^\n]*\];',
        'const INCOME_PEOPLE=window.__FINANCE_BRIDGE__.people.slice();', 'income people')
    html = exact_sub(html, r" const totals=\{'Алексей':0,[^\n]*\};",
        ' const totals=Object.fromEntries(PEOPLE.map(name=>[name,0]));', 'person totals')
    html = exact_sub(html, r'const ACCOUNT_PROFILES=Object\.freeze\(\{.*?\n\}\);.*?(?=function setStatus\()',
        """const ACCOUNT_PROFILES=Object.freeze({});
function profileWithForms(name){
 const value=String(name||'семья');return {name:value,genitive:value,dative:value,accusative:value,instrumental:value,prepositional:value};
}
function currentProfile(){
 const profile=window.__FINANCE_BRIDGE__.profile;
 if(profile&&typeof profile.name==='string'&&profile.name.trim())return {...profileWithForms(profile.name),...profile};
 const meta=session?.user?.user_metadata||{};
 return profileWithForms(String(meta.name||meta.full_name||meta.display_name||'семья').trim());
}
""", 'account profiles')
    html = exact_sub(html, r'const FAMILY_BIRTHS=\[.*?\];', 'const FAMILY_BIRTHS=[];', 'family birthdays')
    html = exact_sub(html, r'const FAMILY_WEDDING=\{[^\n]*\};', 'const FAMILY_WEDDING=null;', 'family wedding')
    html = html.replace(',{...FAMILY_WEDDING}];', ',...(FAMILY_WEDDING?[{...FAMILY_WEDDING}]:[])];')
    html = exact_sub(html, r'const BANK_LOAN_SCHEDULE=\[.*?\];', 'const BANK_LOAN_SCHEDULE=[];', 'loan schedule')
    info = "{contractDate:'',principal:0,rate:0,scheduledPayment:0,averagePayment:0,psk:0,fullCost:0,totalPrincipal:0,totalInterest:0,creditPayments:0,appraisal:0,propertyInsurance:0,personalInsurance:0,endDate:''}"
    html = exact_sub(html, r'const BANK_LOAN_INFO=Object\.freeze\(\{.*?\}\);',
        'const BANK_LOAN_INFO=Object.freeze('+info+');', 'loan info')
    for element_id in ('loanPrincipal', 'loanScheduledPayment', 'loanEndDate'):
        html = exact_sub(html, r'<b id="'+element_id+r'">[^<]*</b>',
            '<b id="'+element_id+'">—</b>', 'blank '+element_id)
    html = exact_sub(html, r'<div class="section-head"><div><h2>Ипотека · Демобанк</h2>[^\n]*',
        '<div class="section-head"><div><h2>Банковский кредит</h2><div class="hint">Банковский график для этой семьи не добавлен. Добавьте своё обязательство в разделе кредитов и рассрочек.</div></div></div>', 'blank contract heading')
    html = exact_sub(html, r'<div class="credit-note" id="loanRateNote">[^\n]*',
        '<div class="credit-note" id="loanRateNote">График не добавлен.</div>', 'blank contract note')
    html = exact_sub(html, r'<div class="card loan-contract-info">[^\n]*',
        '<div class="card loan-contract-info"><h2>Условия договора</h2><p class="hint">Договор не добавлен.</p></div>', 'blank contract conditions')
    html = html.replace('function renderLoanCharts(rows){', "function renderLoanCharts(rows){\n if(!rows.length){const svg=document.getElementById('loanDebtSvg');if(svg)svg.replaceChildren();const split=document.getElementById('loanSplitChart');if(split)split.textContent='График не добавлен';return}")
    # The import change listener closes over an async File read.  A detached
    # iframe must never finish an old import after its account/role was changed.
    html = exact_sub(html, r" const f=e.target.files\?\.\[0\];if\(!f\)return;\n try\{",
        " const f=e.target.files?.[0];if(!f)return;\n const importEpoch=authEpoch;\n if(!window.__FINANCE_BRIDGE__.active||window.__FINANCE_BRIDGE__.role==='viewer')return;\n try{", 'import generation')
    html = exact_sub(html, r'  const raw=validateBackup\(JSON\.parse\(await f\.text\(\)\)\);',
        "  const importText=await f.text();\n  if(importEpoch!==authEpoch||!window.__FINANCE_BRIDGE__.active||window.__FINANCE_BRIDGE__.role==='viewer')return;\n  const raw=validateBackup(JSON.parse(importText));", 'late import guard')
    html = exact_sub(html, r"async function exportDeviceBackup\(\)\{\n  'use strict';",
        "async function exportDeviceBackup(){\n  'use strict';\n  const exportEpoch=authEpoch;\n  if(!window.__FINANCE_BRIDGE__.active)return;", 'backup generation')
    metadata_capture = """    const memoryRaw = JSON.stringify(state);
    const householdMetadataSnapshot = () => {
      const household=window.__FINANCE_BRIDGE__.household;
      const catalog=items=>(Array.isArray(items)?items:[]).map(row=>{
        if(typeof row==='string')return row;
        if(!row||typeof row.id!=='string'||typeof row.name!=='string')fail('metadata-invalid');
        return {id:row.id,name:row.name,archived:row.archived===true};
      });
      return {household_id:CONFIG.household,name:String(household.name||''),timezone:String(household.timezone||'UTC'),
        people:catalog(household.settings?.people),categories:catalog(household.settings?.categories)};
    };
    const householdMetadata=householdMetadataSnapshot(),householdMetadataRaw=JSON.stringify(householdMetadata);"""
    html = exact_sub(html, r'    const memoryRaw = JSON\.stringify\(state\);', metadata_capture, 'device metadata snapshot')
    html = exact_sub(html, r'    const records = \[\];\n    for \(const item of rawValues\)',
        "    const records = [];\n    const householdMetadataHash=hex(await crypto.subtle.digest('SHA-256',encoder.encode(householdMetadataRaw)));\n    for (const item of rawValues)", 'device metadata hash')
    html = exact_sub(html, r'    // Hashing yields to the application\. Refuse a visibly changing capture\.',
        "    if(exportEpoch!==authEpoch||!window.__FINANCE_BRIDGE__.active)return;\n    if(JSON.stringify(householdMetadataSnapshot())!==householdMetadataRaw)fail('metadata-changed-during-capture');\n    // Hashing yields to the application. Refuse a visibly changing capture.", 'late backup guard')
    html = exact_sub(html, r'      memory_state_json: memoryRaw, server_backup_included: false',
        '      memory_state_json: memoryRaw, server_backup_included: false,\n      household_metadata: householdMetadata, household_metadata_sha256_utf8: householdMetadataHash', 'device metadata fields')
    html = exact_sub(html, r"      'storage-changed-during-capture'\]\);",
        "      'storage-changed-during-capture','metadata-invalid','metadata-changed-during-capture']);", 'device metadata failure reasons')
    html = html.replace('Сохраняет историю этой вкладки, локальную очередь и варианты конфликтов.',
        'Сохраняет историю этой вкладки, локальную очередь, варианты конфликтов, название и часовой пояс семьи, списки людей и категорий с их идентификаторами и архивными отметками.')
    html = html.replace('а также текущее состояние памяти вкладки. Сессия входа не включается.',
        'а также текущее состояние памяти вкладки, название и часовой пояс семьи, списки людей и категорий с идентификаторами и архивными отметками. Настройки семьи сохраняются отдельным снимком с контрольной суммой; обычный импорт JSON их не восстанавливает. Сессия входа не включается.')
    html = html.replace('let state=loadLocal();', 'let state=blankState();')
    html = html.replace('state.settings.loans.loan1=11000', 'state.settings.loans.loan1=0')
    html = html.replace("loans:{loanBank:'Демобанк',loan1:11000}", "loans:{loanBank:'',loan1:0}")
    html = html.replace("state.settings.loans.loanBank='Демобанк'", "state.settings.loans.loanBank=''")
    html = html.replace("state.settings.loans.loanBank||'Демобанк'", "state.settings.loans.loanBank||''")
    # Scenario calculators use only a configured schedule, never a seeded balance.
    html = html.replace('120000', 'Number(BANK_LOAN_INFO.principal)||0')
    html = html.replace("'2026-12-15'", "(BANK_LOAN_INFO.contractDate||today())")
    html = html.replace('min="2026-12-15"', 'min="${BANK_LOAN_INFO.contractDate||today()}"')
    html = html.replace("'2027-12-15'", 'today()')
    # The shared direction model uses scoped PEOPLE plus this family's saved
    # custom targets. Do not replace it with fixed demo-family names.
    if html.count('function v81BeneficiaryOptions(){return v99BeneficiaryChoices()}') != 1:
        raise ValueError('Beneficiary model changed; review public scope')
    html = exact_sub(html, r"\['Бим','Рыжик'\]\.includes\(name\)",
        "(window.__FINANCE_BRIDGE__.pets||[]).includes(name)", 'direction pet roles')
    html = exact_sub(html, r" const choices=v81BeneficiaryOptions\(\);if\(!choices.includes\(target\)\)choices.push\(target\);",
        " const choices=v81BeneficiaryOptions();if(!choices.includes(target))choices.push(target);", 'beneficiary choices')
    html = html.replace("['София','Илья','Оба ребёнка'].includes(b)", "(window.__FINANCE_BRIDGE__.children||[]).includes(b)")
    html = exact_sub(html, r'const V84_PERSON_COLORS=Object\.freeze\(\{[^\n]*\}\);',
        "const V84_PERSON_COLORS=Object.freeze(Object.fromEntries(PEOPLE.map((name,i)=>[name,['#3f69e8','#a657db','#f59c1b','#13a780','#617b9b'][i%5]])));", 'person colors')
    # Integrations have no contacts, recipients, connection claims, or credentials.
    html = exact_sub(html, r'const TELEGRAM_CHAT_IDS=Object\.freeze\(\{[^\n]*\}\);',
        'const TELEGRAM_CHAT_IDS=Object.freeze({});', 'Telegram recipients')
    html = replace_function(html, 'telegramRecipients', 'function telegramRecipients(){\n return [];\n}')
    html = replace_function(html, 'sendTelegramMessage', "async function sendTelegramMessage(chatId,text){\n throw new Error('Telegram не настроен для этой семьи');\n}")
    html = replace_function(html, 'testTelegram', "async function testTelegram(person){\n toast('Telegram не настроен для этой семьи');\n}")
    html = exact_sub(html, r"const V88_FEEDBACK_SUPPORT_EMAIL='[^']*';", "const V88_FEEDBACK_SUPPORT_EMAIL='';", 'support email')
    html = exact_sub(html, r'<div class="telegram-people-grid">.*?(?=\n  <div class="telegram-master">)',
        '<div class="telegram-people-grid"><p class="hint">Telegram для этой семьи не настроен.</p></div>\n', 'Telegram people')
    html = exact_sub(html, r'<div class="telegram-recipients">.*?(?=\n  <div class="telegram-test-note">)',
        '<div class="telegram-recipients"></div>\n', 'Telegram recipients display')
    html = exact_sub(html, r'<div class="family-avatars" aria-label="Семья">.*?</div>',
        '<div class="family-avatars" aria-label="Семья"></div>', 'family avatars')
    html = exact_sub(html, r'<div class="board-family-line">.*?</div>',
        '<div class="board-family-line"></div>', 'family list')
    html = exact_sub(html, r'<select id="choreWho">.*?</select>',
        '<select id="choreWho"><option>Семья</option></select>', 'chore people')
    html = html.replace("${/елена/i.test(author)?'elena':/алекс/i.test(author)?'alexey':''}", '')
    html = html.replace('Алексей и Елена используют свои отдельные аккаунты.', 'Участники семьи используют отдельные аккаунты.')
    html = html.replace('Алексей и Елена используют разные аккаунты, а финансовые данные семьи общие.', 'Каждый участник входит в свой аккаунт. Финансовые данные доступны участникам семьи.')
    html = html.replace('Напишите первое сообщение — оно сразу появится у Алексея и Елены.', 'Напишите первое сообщение для участников семьи.')
    html = html.replace('Семейный банк может отправлять персональные уведомления Алексею и Елены.', 'Telegram для этой семьи не настроен.')
    html = html.replace('Например: сегодня забрать Софию и купить продукты на ужин…', 'Например: сегодня купить продукты на ужин…')
    html = html.replace('Например: Алексей Иванов', 'Введите имя')
    html = html.replace('Получатель · alexey@example.invalid', 'Обратная связь')
    html = html.replace("    alexey:true,\n    elena:true,\n", '')
    html = html.replace('   alexey:Boolean(n.alexey??true),\n   elena:Boolean(n.elena??true),\n', '')
    html = html.replace(',telegramAlexey:n.alexey,telegramElena:n.elena', '')
    # Remove family-specific styling class names without changing generic styling.
    for old, new in [('alexey','person-one'),('elena','person-two'),('sofia','person-three'),('ilya','person-four'),('ginger','person-five')]:
        html = html.replace(old, new)
    html = html.replace('Демобанка', 'банка').replace('Демобанк', 'Банк')
    html = html.replace('урал[ -]?сиб|ипотек|uralsib', 'ипотек')
    html = html.replace('английский софии', 'английский язык')
    html = html.replace('СЕМЕЙНЫЙ БАНК · ДЕМО', 'СЕМЕЙНЫЙ БАНК')
    html = html.replace('Семейный Банк · демо', 'Семейный Банк').replace('ДЕМОСЕМЬИ', 'СЕМЬИ')
    html = html.replace('<small>Демоверсия</small>', '<small>Семейный бюджет</small>')
    html = html.replace('family-demo-backup-', 'family-budget-backup-')
    html = html.replace('marichevy-', 'family-budget-')
    html = html.replace('СЕМЕЙНЫЙ БАНК · СЕМЕЙНЫЙ БАНК', 'СЕМЕЙНЫЙ БАНК')
    html = html.replace('Chery Tiggo', 'автомобиля')
    # The demo generator's substring name substitution also touched common words.
    # Restore those words here after all standalone fictional names are removed.
    html = html.replace('рыжик', 'дени').replace('Совпарыжике', 'Совпадение')
    # The runtime supplies a validated household timezone before script execution.
    html = html.replace("'Europe/Moscow'", 'window.__FINANCE_BRIDGE__.timezone')
    html = exact_sub(html, r"boot\(\)\.catch\(err=>console\.error\('boot',err\)\);",
        '/* Public ledger starts only after the shell verifies household membership. */', 'bootstrap')
    html = html.replace('Москва', 'Часовой пояс семьи').replace('Москвы', 'часового пояса семьи')
    html = html.replace('Никаких фиксированных 90 000 ₽.', 'Платежи берутся из ваших графиков.')
    html = html.replace('class="brand-emblem" aria-hidden="true">М</span>', 'class="brand-emblem" aria-hidden="true">С</span>')
    html = html.replace('class="home-opening-mark" aria-hidden="true">М</div>', 'class="home-opening-mark" aria-hidden="true">С</div>')
    html = html.replace('СЕМЬЯ СЕМЬИ · ФИНАНСОВЫЙ ЦЕНТР', 'СЕМЕЙНЫЙ ФИНАНСОВЫЙ ЦЕНТР')
    html = html.replace('FAMILY EDITION <b>PRO</b>', 'СЕМЕЙНЫЙ БЮДЖЕТ <b>FREE</b>')
    html = html.replace('В этой личной версии все разделы открыты для проверки. Платёж не создаётся, покупка сейчас недоступна.',
        'Текущий тариф семьи — FREE. Финансовые разделы доступны участникам семьи с учётом их роли. Оплата не подключена.')
    html = html.replace('Перед публичным запуском: регистрация по подтверждённой почте, своя семья и приглашения участников по email с управлением доступом. Сейчас самостоятельная регистрация и приглашения ещё не доступны.',
        'Регистрация, своя семья и управление приглашениями доступны в личном кабинете. Покупка платного тарифа пока недоступна.')
    bootstrap = '<script>window.__FINANCE_BRIDGE__=parent.FinanceLedger?.bridge(location.hash.slice(1));</script>'
    icon = '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,'+quote(ICON, safe='')+'">'
    html = exact_sub(html, r'<head>', '<head><meta http-equiv="Content-Security-Policy" content="'+CSP+'">'+icon+bootstrap, 'public CSP')
    html = exact_sub(html, r'</body>', RUNTIME_MARKER+'\n</body>', 'runtime marker')
    # Fail closed on every known private and fictional identity/configuration.
    forbidden = ['gmail.com','example.invalid','supabase.co','sb_publishable_',
        'Маричев','МАРИЧЕВ','Сергей','Виктория','Алиса','Майя','УралСиб',
        'Алексей','Алексея','Алексею','Алексеем','Елена','Елены','Елену','Еленой',
        'София','Софии','Софию','Илья','Рыжик','Бим','Демобанк','Демоверсия',
        '1985-11-27','1988-12-04','2018-01-13','2026-05-17','2023-10-07',
        '1990-04-12','1992-07-21','2015-03-16','2020-08-09','2012-06-15',
        '9946-WZ3/00067','666991984','247264029','demo-income','demo-food',
        'marichev', 'софии', 'uralsib', 'урал[ -]?сиб', 'window.fetch=()=>Promise.reject']
    for marker in forbidden:
        if marker in html:
            raise ValueError('Identity or configuration marker survived: '+marker)
    if html.count(CONFIG_MARKER) != 1 or html.count(RUNTIME_MARKER) != 1:
        raise ValueError('Expected exactly one runtime/configuration marker')
    return html.replace(MERCHANT_PLACEHOLDER, merchant_catalog).rstrip() + '\n'


def build(output: Path | None = None) -> Path:
    target = output or ROOT / 'public' / 'ledger-template.html'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(transform_public((ROOT / 'index.html').read_text()))
    return target


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args=parser.parse_args()
    print(build(args.output))
