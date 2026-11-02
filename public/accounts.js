/* Public account shell. Financial state belongs exclusively to FinanceLedger. */
(() => {
  'use strict';
  const root = document.getElementById('main');
  const accountActions = document.getElementById('account-actions');
  const notice = document.getElementById('notice');
  const app = {config:null,session:null,household:null,households:[],epoch:0,authGeneration:0,authAttempt:0,controllers:new Set(),ledger:null,ledgerRoot:null,refreshing:null,pendingEmail:'',pendingInvite:null,authView:'login',storageKey:null,noticeTimer:null};
  class Superseded extends Error {}
  const isStale = error => error instanceof Superseded || error?.name === 'AbortError';
  function rotateAuth(){app.authGeneration+=1;app.refreshing=null;}
  function node(tag, props = {}, ...children) {
    const element = document.createElement(tag);
    for (const [key,value] of Object.entries(props)) {
      if (key === 'class') element.className = value;
      else if (key === 'text') element.textContent = value;
      else if (key.startsWith('on') && typeof value === 'function') element.addEventListener(key.slice(2), value);
      else if(key.startsWith('aria-') && typeof value==='boolean')element.setAttribute(key,String(value));
      else if (value !== false && value != null) element.setAttribute(key,value === true ? '' : String(value));
    }
    for (const child of children.flat(Infinity)) if (child != null) element.append(child instanceof Node ? child : document.createTextNode(String(child)));
    return element;
  }
  const button = (label, action, kind = 'secondary', props = {}) => node('button',{type:'button',class:`btn btn-${kind}`,onclick:action,...props},label);
  function field(label,id,type='text',props={},hint='') {
    const input = node(type === 'textarea' ? 'textarea' : type === 'select' ? 'select' : 'input',{id,name:id,...(type !== 'textarea' && type !== 'select' ? {type} : {}),...props});
    return {input,element:node('div',{class:'field'},node('label',{for:id},label),input,hint ? node('span',{class:'hint',id:`${id}-hint`},hint) : null)};
  }
  const errorBox = () => node('div',{class:'form-error',role:'alert',tabindex:'-1',hidden:true});
  function errorMessage(error) {
    const code = String(error?.code || '');
    if (code==='invite_accept_rejected')return 'Приглашение недоступно. Войдите с почтой, на которую его отправили. Если адрес верный, попросите владельца отправить новое.';
    if (/email_not_confirmed|email_unverified/.test(code)) return 'Подтвердите адрес почты по ссылке из письма. Затем войдите ещё раз.';
    if (/invalid_credentials|invalid_grant|bad_jwt|invalid_login|authentication_failed/.test(code)) return 'Не удалось войти. Проверьте почту и пароль.';
    if (/invite_email|email_mismatch|wrong_email/.test(code)) return 'Приглашение адресовано другой почте. Войдите с адресом, на который его отправили.';
    if (/invite_expired|invite_invalid|invalid_invite|invite_not_found/.test(code)) return 'Срок приглашения истёк или оно отозвано. Попросите владельца отправить новое.';
    if (/invite_already|already_member/.test(code)) return 'Этот доступ уже оформлен. Обновите список семей.';
    if (/rate|429/.test(code)) return 'Слишком много попыток. Подождите немного и попробуйте снова.';
    if (/weak_password/.test(code)) return 'Выберите более надёжный пароль: не меньше 8 символов.';
    if (/forbidden|42501|permission|not_member|access_denied/.test(code)) return 'Доступ изменился. Обновите список семей или обратитесь к владельцу.';
    if (/token|link|otp|expired/.test(code)) return 'Ссылка недействительна или её срок истёк. Запросите новое письмо.';
    if (/network/.test(code) || error instanceof TypeError) return 'Нет соединения с сервером. Проверьте интернет и повторите попытку.';
    if (/unavailable|disabled|configuration|503/.test(code)) return 'Сервис временно недоступен. Попробуйте позже.';
    return 'Не удалось выполнить действие. Попробуйте ещё раз.';
  }
  function toast(message) {
    clearTimeout(app.noticeTimer); notice.textContent = message; notice.hidden = false;
    app.noticeTimer = setTimeout(() => {notice.hidden = true;},6500);
  }
  function advanceScope() {
    app.epoch += 1;
    for (const controller of app.controllers) controller.abort();
    app.controllers.clear();
    if (app.ledger) {try {app.ledger.unmount();} catch (_) {}}
    app.ledger = null; app.ledgerRoot = null;
    return app.epoch;
  }
  const checkEpoch = epoch => {if (epoch !== app.epoch) throw new Superseded();};
  function persistedSession(value) {
    if (!value || typeof value.access_token !== 'string' || typeof value.refresh_token !== 'string' || !value.user?.id) return null;
    return {access_token:value.access_token,refresh_token:value.refresh_token,expires_at:value.expires_at,expires_in:value.expires_in,token_type:'bearer',user:{id:value.user.id,email:value.user.email || '',email_confirmed_at:value.user.email_confirmed_at || null,confirmed_at:value.user.confirmed_at || null}};
  }
  function setSession(value, persist = true) {
    const session = persistedSession(value);
    if (session && app.session && session.user.id !== app.session.user.id) {advanceScope();app.household = null;rotateAuth();}
    app.session = session;
    if (persist && app.storageKey) {try {if (session) localStorage.setItem(app.storageKey,JSON.stringify(session)); else localStorage.removeItem(app.storageKey);} catch (_) {}}
    renderAccount(); return session;
  }
  const verified = () => Boolean(app.session?.user?.email_confirmed_at || app.session?.user?.confirmed_at);
  async function raw(path,body,{token=null,signal=null}={}) {
    const options = {method:body === undefined ? 'GET' : 'POST',headers:{'Accept':'application/json'},credentials:'same-origin',cache:'no-store',redirect:'error',signal};
    if (body !== undefined) {options.headers['Content-Type'] = 'application/json';options.body = JSON.stringify(body);}
    if (token) options.headers.Authorization = `Bearer ${token}`;
    let response;
    try {response = await fetch(path,options);} catch (error) {if (error.name === 'AbortError') throw error; throw Object.assign(new Error('Network request failed'),{code:'network'});}
    let result; try {result = await response.json();} catch (_) {result = {};}
    if (!response.ok) {const details = result.error || result;throw Object.assign(new Error('Request failed'),{code:details.code || String(response.status),status:response.status});}
    return result;
  }
  async function refresh() {
    if (app.refreshing) return app.refreshing;
    const generation = app.authGeneration, refreshToken = app.session?.refresh_token;
    if (!refreshToken) throw Object.assign(new Error('No session'),{code:'session_expired',status:401});
    const pending = (async () => {
      let result;try{result=await raw('/api/auth/refresh',{refresh_token:refreshToken});}catch(error){if(generation!==app.authGeneration || app.session?.refresh_token!==refreshToken)throw new Superseded();throw error;}
      if (generation !== app.authGeneration || app.session?.refresh_token !== refreshToken) throw new Superseded();
      if (!persistedSession(result.session)) throw Object.assign(new Error('Invalid session'),{code:'session_expired',status:401});
      setSession(result.session); return app.session;
    })();
    app.refreshing = pending;
    try {return await pending;} finally {if (app.refreshing === pending) app.refreshing = null;}
  }
  function rpcPath(path) {
    const name = String(path).replace(/^\/rest\/v1\/rpc\//,'').replace(/^\/api\/rpc\//,'');
    if (!/^finance_[a-z_]+$/.test(name)) throw new Error('Unsupported operation');
    return `/api/rpc/${name}`;
  }
  async function request(path,body = {},epoch = app.epoch) {
    checkEpoch(epoch);
    const url = path === '/api/invites/create' ? path : rpcPath(path);
    const controller = new AbortController(); app.controllers.add(controller);
    try {
      let result;
      try {result = await raw(url,body,{token:app.session?.access_token,signal:controller.signal});}
      catch (error) {
        checkEpoch(epoch);
        if (error.status !== 401) throw error;
        try {await refresh();} catch (refreshError) {if (!isStale(refreshError)) expireSession();throw refreshError;}
        checkEpoch(epoch);
        result = await raw(url,body,{token:app.session?.access_token,signal:controller.signal});
      }
      checkEpoch(epoch); return result;
    } finally {app.controllers.delete(controller);}
  }
  function expireSession() {
    advanceScope(); rotateAuth();app.household = null;setSession(null);renderAuth('login');toast('Сессия завершилась. Войдите снова.');
  }
  async function logout() {
    const token = app.session?.access_token;
    advanceScope(); rotateAuth();app.household = null;app.households = [];setSession(null);renderAuth('login');
    if (token) {try {await raw('/api/auth/logout',{}, {token});} catch (_) {toast('Вы вышли на этом устройстве. Сервер пока недоступен.');}}
  }
  function renderAccount() {
    accountActions.replaceChildren();
    if (app.session) accountActions.append(node('span',{class:'account-email'},app.session.user.email),button('Выйти',logout,'plain',{id:'logout'}));
  }
  function formRunner(form,box,action) {
    form.addEventListener('submit',async event => {
      event.preventDefault(); if (form.dataset.busy) return;
      const epoch = app.epoch;form.dataset.busy = 'true';box.hidden = true;
      const submits = [...form.querySelectorAll('[type=submit]')];submits.forEach(el => {el.disabled = true;});form.setAttribute('aria-busy','true');
      try {await action();} catch (error) {if (!isStale(error) && epoch === app.epoch) {box.textContent = errorMessage(error);box.hidden = false;box.focus();}}
      finally {delete form.dataset.busy;form.removeAttribute('aria-busy');submits.forEach(el => {el.disabled = false;});}
    });
  }
  function authStory() {
    return node('section',{class:'auth-story','aria-label':'Семейные финансы'},node('div',{class:'eyebrow'},'Деньги · Планы · Семья'),node('h1',{},'Ваши финансы. ',node('br'), 'Общие планы.'),node('p',{class:'lead'},'Покупки, цели и повседневные дела — в одном спокойном пространстве для вашей семьи.'),node('div',{class:'story-art','aria-hidden':'true'},node('div',{class:'art-heading'},'Всё важное — рядом',node('span',{class:'art-pill'},'Вместе проще')),['⌂','↗','✓'].map(icon => node('div',{class:'art-row'},node('span',{class:'art-icon'},icon),node('span',{class:'art-line'}),node('span',{class:'art-line short'}))),node('div',{class:'art-footer'},Array.from({length:5},()=>node('div',{class:'art-bar'})))),node('div',{class:'privacy-note'},node('span',{'aria-hidden':'true'},'◇'),node('span',{},'Каждая семья начинает с чистого листа. Доступ к её данным получают только приглашённые участники.')));
  }
  function renderAuth(view = 'login') {
    const attempt=++app.authAttempt;app.authView = view; renderAccount();
    const card = node('section',{class:'card auth-card','aria-labelledby':'auth-heading'});
    const layout = node('div',{class:'auth-layout'},authStory(),card);root.replaceChildren(layout);
    if (view === 'pending') return renderPending(card);
    if (view === 'reset') return renderReset(card);
    if (view === 'recover') return renderRecover(card);
    const signup = view === 'signup';
    const tabs = node('div',{class:'auth-tabs',role:'tablist','aria-label':'Доступ к аккаунту'},button('Войти',()=>renderAuth('login'),'plain',{id:'auth-login',role:'tab','aria-selected':!signup}),button('Создать аккаунт',()=>renderAuth('signup'),'plain',{id:'auth-signup',role:'tab','aria-selected':signup}));
    const email = field('Электронная почта','auth-email','email',{autocomplete:'email',required:true,maxlength:254,placeholder:'you@example.com',value:app.pendingEmail});
    const password = field('Пароль','auth-password','password',{autocomplete:signup?'new-password':'current-password',required:true,minlength:signup?8:1,maxlength:128},signup?'Не меньше 8 символов. Не используйте пароль от почты.':'');
    const box = errorBox(); const submit = node('button',{class:'btn btn-primary full-width',id:'auth-submit',type:'submit'},signup?'Создать аккаунт':'Войти');
    const form = node('form',{class:'form-stack'},email.element,password.element,box,submit);
    card.append(tabs,node('h2',{id:'auth-heading'},signup?'Начнём с вашего аккаунта':'Рады вас видеть'),node('p',{},signup?'Создайте аккаунт, подтвердите почту и заведите свою семью.':'Войдите, чтобы продолжить вести семейные дела.'),form);
    if (!signup) card.append(node('div',{class:'auth-bottom'},button('Не помню пароль',()=>renderAuth('recover'),'plain',{id:'auth-recover'})));
    else card.append(node('p',{class:'auth-bottom'},'После регистрации понадобится подтвердить адрес по ссылке из письма.'));
    if (app.pendingInvite) card.append(node('p',{class:'auth-bottom'},'У вас есть приглашение. Войдите с адресом, на который его отправили.'));
    formRunner(form,box,async () => {
      const epoch = app.epoch,generation=app.authGeneration;app.pendingEmail = email.input.value.trim();
      const result = await raw(`/api/auth/${signup?'signup':'login'}`,{email:app.pendingEmail,password:password.input.value});
      checkEpoch(epoch);if(attempt!==app.authAttempt||generation!==app.authGeneration)throw new Superseded();password.input.value = '';
      if (signup) {renderAuth('pending');return;}
      if (!persistedSession(result.session)) throw Object.assign(new Error('Invalid session'),{code:'invalid_credentials'});
      rotateAuth();setSession(result.session);
      if (!verified()) {renderAuth('pending');return;}
      await loadHouseholds();
    });
  }
  function renderPending(card) {
    card.append(node('div',{class:'status-icon','aria-hidden':'true'},'✉'),node('h2',{id:'auth-heading'},'Подтвердите почту'),node('p',{},'Проверьте входящие и папку «Спам». Для продолжения нужна ссылка подтверждения. Если письмо не появилось, запросите его ещё раз.'),node('p',{class:'pending-email'},app.pendingEmail || app.session?.user.email || ''),node('p',{class:'hint'},'Пока адрес не подтверждён, семейные данные недоступны. После перехода по ссылке вернитесь сюда.'));
    const box = errorBox(),status = node('div',{class:'form-success',role:'status',hidden:true});
    const form = node('form',{class:'form-stack'},box,status,node('button',{class:'btn btn-secondary full-width',id:'auth-resend',type:'submit'},'Запросить письмо ещё раз'));
    card.append(form,button('Перейти ко входу',()=>renderAuth('login'),'plain',{id:'pending-login'}));
    formRunner(form,box,async()=>{await raw('/api/auth/resend',{email:app.pendingEmail || app.session?.user.email,type:'signup'});status.textContent = 'Запрос принят. Проверьте почту и папку «Спам».';status.hidden = false;});
  }
  function renderRecover(card) {
    const email = field('Электронная почта','recover-email','email',{autocomplete:'email',required:true,maxlength:254,value:app.pendingEmail});
    const box = errorBox(),status = node('div',{class:'form-success',role:'status',hidden:true});
    const form = node('form',{class:'form-stack'},email.element,box,status,node('button',{class:'btn btn-primary',type:'submit',id:'recover-submit'},'Запросить ссылку'));
    card.append(node('h2',{id:'auth-heading'},'Восстановление доступа'),node('p',{},'Укажите почту своего аккаунта, чтобы запросить ссылку для нового пароля.'),form,button('Вернуться ко входу',()=>renderAuth('login'),'plain',{id:'recover-back'}));
    formRunner(form,box,async()=>{app.pendingEmail=email.input.value.trim();await raw('/api/auth/recover',{email:app.pendingEmail});status.textContent='Запрос принят. Проверьте почту и папку «Спам». Ответ одинаков для любого адреса.';status.hidden=false;});
  }
  function renderReset(card) {
    if (!app.session) {renderAuth('recover');return;}
    const password = field('Новый пароль','reset-password','password',{autocomplete:'new-password',required:true,minlength:8,maxlength:128});
    const repeat = field('Повторите пароль','reset-repeat','password',{autocomplete:'new-password',required:true,minlength:8,maxlength:128});
    const box = errorBox();const form=node('form',{class:'form-stack'},password.element,repeat.element,box,node('button',{class:'btn btn-primary',type:'submit',id:'reset-submit'},'Сохранить пароль'));
    card.append(node('h2',{id:'auth-heading'},'Новый пароль'),node('p',{},'Придумайте пароль для следующего входа. Не меньше 8 символов.'),form);
    formRunner(form,box,async()=>{
      if(password.input.value!==repeat.input.value){repeat.input.setCustomValidity('Пароли должны совпадать');repeat.input.reportValidity();repeat.input.addEventListener('input',()=>repeat.input.setCustomValidity(''),{once:true});return;}
      const epoch=app.epoch;await raw('/api/auth/reset',{password:password.input.value},{token:app.session.access_token});checkEpoch(epoch);password.input.value='';repeat.input.value='';toast('Пароль сохранён.');await loadHouseholds();
    });
  }
  const record = result => Array.isArray(result) ? result[0] : result?.data ?? result;
  const rows = result => Array.isArray(result) ? result : Array.isArray(result?.data) ? result.data : [];
  const householdId = household => household?.household_id || household?.id;
  const roleLabel = role => ({owner:'Владелец',editor:'Редактор',viewer:'Просмотр'})[role] || 'Участник';
  const requestId = () => crypto.randomUUID();
  function workspace() {const content=node('div',{class:'workspace'});root.replaceChildren(content);return content;}
  function invitationBanner(content) {
    if(!app.pendingInvite)return;
    const box=errorBox();const form=node('form',{class:'invitation-banner'},node('p',{},'По этой ссылке вам доступно приглашение в семью. Подтвердите его для текущего адреса: ',node('strong',{},app.session.user.email)),node('button',{class:'btn btn-primary',type:'submit',id:'accept-invite'},'Принять приглашение'),box);
    content.append(form);
    formRunner(form,box,async()=>{let result;try{result=record(await request('finance_accept_invite',{p_token:app.pendingInvite}));}catch(error){if(error.code==='request_rejected'||error.code==='22023')throw Object.assign(new Error('Invitation unavailable'),{code:'invite_accept_rejected'});throw error;}app.pendingInvite=null;toast('Вы присоединились к семье.');await loadHouseholds();const id=householdId(result);if(id)await selectHousehold(id);});
  }
  async function loadHouseholds() {
    if(!app.session)return renderAuth('login');if(!verified())return renderAuth('pending');
    const epoch=app.epoch;root.replaceChildren(node('div',{class:'boot-state',role:'status'},node('span',{class:'spinner'}),'Загружаем ваши семьи…'));
    try{app.households=rows(await request('finance_list_households',{},epoch));checkEpoch(epoch);renderHouseholds();}
    catch(error){if(isStale(error))return;const content=workspace();content.append(node('section',{class:'card fatal'},node('h1',{},'Не удалось загрузить семьи'),node('p',{},errorMessage(error)),button('Повторить',()=>loadHouseholds(),'primary')));}
  }
  function renderHouseholds(showCreate=false) {
    app.household=null;renderAccount();const content=workspace();invitationBanner(content);
    if(!app.households.length){content.append(node('section',{class:'empty-hero'},node('div',{class:'family-symbol','aria-hidden':'true'},'⌂'),node('h1',{},'Здесь начнётся ваша семья'),node('p',{},'Создайте общее пространство с чистого листа. Название, участники и категории будут только ваши.')));content.append(createFamilyForm());return;}
    content.append(node('div',{class:'workspace-top'},node('div',{},node('div',{class:'eyebrow'},'Ваше пространство'),node('h1',{},'Мои семьи'),node('p',{},'Выберите семью, чтобы открыть её финансы.')),button(showCreate?'Отменить':'Новая семья',()=>renderHouseholds(!showCreate),'secondary',{id:'show-create-family'})));
    if(showCreate)content.append(createFamilyForm());
    content.append(node('div',{class:'household-grid'},app.households.map(household=>node('button',{class:'household-card',type:'button','data-household':householdId(household),onclick:()=>selectHousehold(householdId(household))},node('span',{class:'family-symbol','aria-hidden':'true'},'⌂'),node('span',{class:'household-name'},household.name),node('span',{class:'household-meta'},`${roleLabel(household.role)} · ${household.timezone || 'UTC'}`),node('span',{class:'household-open'},'Открыть семью →')))));
  }
  function timezoneField(id,value) {return field('Часовой пояс',id,'text',{required:true,maxlength:100,value:value || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',list:'timezone-options'},'Например: Europe/Moscow. Даты и напоминания будут учитывать этот пояс.');}
  function timezoneOptions(){return node('datalist',{id:'timezone-options'},['Europe/Moscow','Europe/Kaliningrad','Europe/Samara','Asia/Yekaterinburg','Asia/Novosibirsk','Asia/Vladivostok','UTC'].map(value=>node('option',{value})));}
  function createFamilyForm(){
    const name=field('Название семьи','family-name','text',{required:true,maxlength:120,placeholder:'Например, наша семья'}),timezone=timezoneField('family-timezone');
    const box=errorBox();const form=node('form',{class:'card form-stack create-section'},node('h2',{},'Новая семья'),name.element,timezone.element,timezoneOptions(),box,node('button',{type:'submit',class:'btn btn-primary',id:'create-family'},'Создать семью'),node('span',{class:'hint'},'Вы станете владельцем и сможете пригласить близких. Финансовые записи пока пусты. Базовые категории можно изменить в настройках.'));
    const id=requestId();formRunner(form,box,async()=>{const result=record(await request('finance_create_household',{p_name:name.input.value.trim(),p_timezone:timezone.input.value.trim(),p_request_id:id}));await loadHouseholds();if(householdId(result))await selectHousehold(householdId(result));});return form;
  }
  async function selectHousehold(id){
    const epoch=advanceScope();app.household=null;root.replaceChildren(node('div',{class:'boot-state',role:'status'},node('span',{class:'spinner'}),'Открываем семью…'));
    try{const household=record(await request('finance_get_household',{p_household_id:id},epoch));checkEpoch(epoch);if(!householdId(household))throw Object.assign(new Error('No membership'),{code:'not_member'});app.household=household;renderFamily();}
    catch(error){if(isStale(error))return;toast(errorMessage(error));await loadHouseholds();}
  }
  function renderFamily(){
    const household=app.household,epoch=app.epoch,content=workspace();
    content.append(node('div',{class:'family-toolbar'},node('div',{class:'family-title'},node('h1',{},household.name),node('p',{},`${roleLabel(household.role)} · ${household.timezone || 'UTC'} · Бесплатный план`)),button('Мои семьи',()=>{advanceScope();app.household=null;loadHouseholds();},'outline',{id:'back-to-families'})));
    const nav=node('nav',{class:'family-nav','aria-label':'Разделы семьи'});const financeButton=button('Финансы',()=>switchTab('finances'),'plain',{id:'nav-finances','aria-current':'page'}),settingsButton=button('Настройки семьи',()=>switchTab('settings'),'plain',{id:'nav-settings'});nav.append(financeButton,settingsButton);content.append(nav);
    const ledgerPanel=node('section',{'aria-label':'Финансы семьи'}),settingsPanel=node('section',{'aria-label':'Настройки семьи',hidden:true});
    if(household.role==='viewer')ledgerPanel.append(node('div',{class:'read-only-note'},'У вас доступ для просмотра. Изменять финансовые записи могут владелец и редакторы.'));
    if(household.role==='owner')ledgerPanel.append(node('p',{class:'hint'},'Базовые категории можно изменить в настройках.'));
    const container=node('div',{class:'ledger-container',id:'ledger-container'});container.append(node('div',{class:'ledger-loading',role:'status'},'Загружаем финансовые разделы…'));ledgerPanel.append(container);content.append(ledgerPanel,settingsPanel);app.ledgerRoot=container;
    let settingsLoaded=false;
    function switchTab(tab){checkEpoch(epoch);ledgerPanel.hidden=tab!=='finances';settingsPanel.hidden=tab!=='settings';financeButton.toggleAttribute('aria-current',tab==='finances');if(tab==='finances')financeButton.setAttribute('aria-current','page');settingsButton.toggleAttribute('aria-current',tab==='settings');if(tab==='settings'){settingsButton.setAttribute('aria-current','page');if(!settingsLoaded){settingsLoaded=true;renderSettings(settingsPanel,epoch);}}}
    mountLedger(container,household,epoch);
  }
  function accessLost(epoch){if(epoch!==app.epoch)return;advanceScope();app.household=null;toast('Доступ к семье изменился. Список семей обновлён.');loadHouseholds();}
  async function mountLedger(container,household,epoch){
    try{
      if(!window.FinanceLedger?.mount)throw Object.assign(new Error('Ledger unavailable'),{code:'unavailable'});
      const instance=await window.FinanceLedger.mount(container,{config:app.config,session:app.session,household,request:(path,body)=>request(path,body,epoch),refresh:async()=>{checkEpoch(epoch);const result=await refresh();checkEpoch(epoch);return result;},onAccessLost:()=>accessLost(epoch),onSession:session=>{if(epoch===app.epoch)setSession(session);}});
      if(epoch!==app.epoch){instance?.unmount?.();return;}app.ledger=instance;
      if(instance?.ready)await instance.ready;checkEpoch(epoch);
    }catch(error){if(isStale(error))return;if(epoch!==app.epoch)return;container.replaceChildren(node('div',{class:'ledger-loading'},node('p',{},'Финансовые разделы пока недоступны.'),button('Повторить',()=>mountLedger(container,household,epoch),'secondary')));}
  }
  async function renderSettings(panel,epoch){
    const household=app.household,owner=household.role==='owner',id=householdId(household);
    panel.replaceChildren(node('div',{class:'boot-state',role:'status'},'Загружаем настройки…'));
    try{
      const [members,invites]=await Promise.all([request('finance_list_members',{p_household_id:id},epoch),owner?request('finance_list_invites',{p_household_id:id},epoch):Promise.resolve([])]);checkEpoch(epoch);
      const grid=node('div',{class:'settings-grid'});panel.replaceChildren(grid);
      if(!owner)grid.append(node('div',{class:'read-only-note wide'},'Название семьи, списки и доступы меняет владелец. Ваши права проверяются сервером при каждом действии.'));
      grid.append(settingsForm(household,owner,epoch),membersCard(rows(members),owner,epoch));
      if(owner)grid.append(invitesCard(rows(invites),epoch));
    }catch(error){if(isStale(error))return;panel.replaceChildren(node('div',{class:'card'},node('p',{},errorMessage(error)),button('Повторить',()=>renderSettings(panel,epoch),'secondary')));}
  }
  function catalogEditor(label,id,values,owner){
    const items=(Array.isArray(values)?values:[]).map(value=>typeof value==='string'?{id:requestId(),name:value,archived:false}:{id:value.id || requestId(),name:value.name || '',archived:Boolean(value.archived)});
    const list=node('div',{class:'catalog-list'}),heading=node('h3',{id:`${id}-heading`},label),empty=node('p',{class:'hint'},'Список пока пуст. Добавьте то, что нужно вашей семье.');
    const section=node('section',{class:'catalog-editor',id,'aria-labelledby':`${id}-heading`},heading,node('p',{class:'hint'},'Переименование сохраняет историю записей. Ненужное можно убрать в архив.'),list);
    function draw(){list.replaceChildren();items.forEach((item,index)=>{
      const input=node('input',{id:`${id}-${index}`,type:'text',value:item.name,maxlength:120,required:!item.archived,disabled:!owner || item.archived,'aria-label':`${label}: название ${index+1}`});
      input.addEventListener('input',()=>{item.name=input.value;});
      const row=node('div',{class:`catalog-row${item.archived?' archived':''}`},input);
      if(owner)row.append(button(item.archived?'Вернуть':'В архив',()=>{item.archived=!item.archived;draw();},'plain',{'aria-label':`${item.archived?'Вернуть':'В архив'}: ${item.name || label}`}));
      else if(item.archived)row.append(node('span',{class:'badge'},'В архиве'));list.append(row);
    });if(!items.length)list.append(empty);}
    if(owner)section.append(button('Добавить',()=>{items.push({id:requestId(),name:'',archived:false});draw();document.getElementById(`${id}-${items.length-1}`)?.focus();},'secondary',{id:`${id}-add`,'aria-label':`Добавить: ${label}`}));
    draw();return {element:section,value:()=>items.map(item=>({...item,name:item.name.trim()}))};
  }
  function settingsForm(household,owner,epoch){
    const name=field('Название семьи','settings-name','text',{required:true,maxlength:120,value:household.name,disabled:!owner}),timezone=timezoneField('settings-timezone',household.timezone);timezone.input.disabled=!owner;
    const people=catalogEditor('Люди','settings-people',household.settings?.people,owner),categories=catalogEditor('Категории расходов','settings-categories',household.settings?.categories,owner);
    const box=errorBox();const form=node('form',{class:'card form-stack'},node('div',{class:'section-heading'},node('div',{},node('h2',{},'О вашей семье'),node('p',{},'Название, часовой пояс и ваши списки.')),node('span',{class:'badge'},'Бесплатно')),name.element,timezone.element,timezoneOptions(),people.element,categories.element,box,owner?node('button',{type:'submit',id:'settings-save',class:'btn btn-primary'},'Сохранить настройки'):null);
    if(owner)formRunner(form,box,async()=>{const result=record(await request('finance_update_settings',{p_household_id:householdId(household),p_name:name.input.value.trim(),p_timezone:timezone.input.value.trim(),p_people:people.value(),p_categories:categories.value(),p_request_id:requestId()},epoch));checkEpoch(epoch);app.household=result;toast('Настройки семьи сохранены.');const id=householdId(result);await selectHousehold(id);document.getElementById('nav-settings')?.click();});return form;
  }
  function membersCard(members,owner,epoch){
    const card=node('section',{class:'card'},node('div',{class:'section-heading'},node('div',{},node('h2',{},'Участники'),node('p',{},'У каждого свой аккаунт и уровень доступа.')),node('span',{class:'badge'},String(members.length))));
    const list=node('div',{class:'member-list'});card.append(list);
    for(const member of members){
      const email=member.email || 'Участник',me=member.user_id===app.session.user.id,box=errorBox();
      const row=node('div',{class:'member-row'},node('span',{class:'member-avatar','aria-hidden':'true'},email.slice(0,1).toUpperCase()),node('div',{class:'member-info'},node('div',{class:'member-email'},email,me?' (вы)':''),node('div',{class:'member-detail'},roleLabel(member.role)),box));
      if(owner&&member.role!=='owner'){
        const select=node('select',{'aria-label':`Роль участника ${email}`},node('option',{value:'editor'},'Редактор'),node('option',{value:'viewer'},'Просмотр'));select.value=member.role;
        select.addEventListener('change',async()=>{select.disabled=true;box.hidden=true;try{await request('finance_set_member_role',{p_household_id:householdId(app.household),p_user_id:member.user_id,p_role:select.value},epoch);checkEpoch(epoch);member.role=select.value;row.querySelector('.member-detail').textContent=roleLabel(member.role);toast('Роль участника изменена.');}catch(error){if(!isStale(error)){select.value=member.role;box.textContent=errorMessage(error);box.hidden=false;}}finally{select.disabled=false;}});
        const remove=button('Удалить',async()=>{remove.disabled=true;box.hidden=true;try{await request('finance_remove_member',{p_household_id:householdId(app.household),p_user_id:member.user_id},epoch);checkEpoch(epoch);row.remove();toast('Доступ участника закрыт.');}catch(error){if(!isStale(error)){box.textContent=errorMessage(error);box.hidden=false;}}finally{remove.disabled=false;}},'danger',{'aria-label':`Удалить участника ${email}`});
        row.append(node('div',{class:'member-controls'},select,remove));
      }list.append(row);
    }
    if(!members.length)list.append(node('p',{class:'empty-list'},'Список участников пока пуст.'));return card;
  }
  function deliveryLabel(invite){
    if(invite.status==='revoked')return 'Приглашение отозвано';if(invite.status==='accepted')return 'Приглашение принято';if(invite.status==='expired')return 'Срок приглашения истёк';
    return ({sent:'Провайдер принял письмо',provider_accepted:'Провайдер принял письмо',accepted:'Провайдер принял письмо',failed:'Провайдер не принял письмо. Отзовите приглашение и создайте новое.',pending:'Письмо ожидает отправки',queued:'Письмо ожидает отправки',leased:'Письмо готовится к отправке',cancelled:'Отправка отменена',disabled:'Отправка почты не настроена'})[invite.mail_status] || 'Статус отправки пока не подтверждён';
  }
  function invitesCard(invites,epoch){
    const card=node('section',{class:'card wide'}),heading=node('div',{class:'section-heading'},node('div',{},node('h2',{},'Пригласить в семью'),node('p',{},'Редактор может менять записи. Участник с просмотром видит данные семьи.')));card.append(heading);
    const email=field('Почта участника','invite-email','email',{required:true,maxlength:254,autocomplete:'off',placeholder:'name@example.com'}),role=field('Уровень доступа','invite-role','select');role.input.append(node('option',{value:'editor'},'Редактор'),node('option',{value:'viewer'},'Только просмотр'));
    const box=errorBox(),status=node('div',{class:'form-success',role:'status',hidden:true});let id=requestId();
    const form=node('form',{class:'invite-form'},email.element,role.element,box,status,node('div',{class:'form-actions'},node('button',{type:'submit',id:'invite-send',class:'btn btn-primary'},'Отправить приглашение'),node('span',{class:'hint'},'Доступ появится после подтверждения этой почты и принятия приглашения.')));
    const list=node('div',{class:'invite-list'});card.append(form,list);
    const update=button('Обновить статус',async()=>{update.disabled=true;try{const fresh=rows(await request('finance_list_invites',{p_household_id:householdId(app.household)},epoch));checkEpoch(epoch);invites.splice(0,invites.length,...fresh);draw();status.hidden=true;}catch(error){if(!isStale(error))toast(errorMessage(error));}finally{update.disabled=false;}},'plain',{id:'invite-refresh'});heading.append(update);
    function draw(){list.replaceChildren();for(const invite of invites){const active=!['revoked','accepted','expired'].includes(invite.status);const row=node('div',{class:'invite-row'},node('div',{class:'member-info'},node('div',{class:'member-email'},invite.email),node('div',{class:'member-detail'},`${roleLabel(invite.role)} · ${deliveryLabel(invite)}`)));
      if(active){const revoke=button('Отозвать',async()=>{revoke.disabled=true;try{await request('finance_revoke_invite',{p_household_id:householdId(app.household),p_invite_id:invite.id},epoch);checkEpoch(epoch);invite.status='revoked';draw();toast('Приглашение отозвано.');}catch(error){if(!isStale(error))toast(errorMessage(error));}finally{revoke.disabled=false;}},'outline',{'aria-label':`Отозвать приглашение ${invite.email}`});row.append(node('div',{class:'member-controls'},revoke));}list.append(row);}if(!invites.length)list.append(node('p',{class:'empty-list'},'Приглашений пока нет.'));}
    draw();formRunner(form,box,async()=>{const result=record(await request('/api/invites/create',{household_id:householdId(app.household),email:email.input.value.trim(),role:role.input.value,request_id:id},epoch));checkEpoch(epoch);if(result){const index=invites.findIndex(invite=>invite.id===result.id);if(index>=0)invites[index]=result;else invites.unshift(result);}status.textContent=result?deliveryLabel(result):'Запрос принят. Статус письма пока не подтверждён.';status.hidden=false;email.input.value='';id=requestId();draw();});return card;
  }
  function parseLink(){
    const hash=new URLSearchParams(location.hash.slice(1)),query=new URLSearchParams(location.search),link={};
    for(const key of ['access_token','refresh_token','token_hash','type','error','error_code','code','code_verifier','invite_token']){const value=hash.get(key)||query.get(key);if(value)link[key]=value;query.delete(key);}
    if(location.hash || query.toString()!==location.search.slice(1))history.replaceState(null,'',location.pathname+(query.toString()?`?${query}`:''));
    if(/^[a-f0-9]{64}$/i.test(link.invite_token || ''))app.pendingInvite=link.invite_token;
    return link;
  }
  window.addEventListener('hashchange',()=>{
    // Email links can navigate an already open page without loading it again.
    // Consume the URL synchronously; invitation navigation keeps the Auth session.
    const incoming=parseLink();
    if(!incoming.invite_token)return;
    if(!/^[a-f0-9]{64}$/i.test(incoming.invite_token)){app.pendingInvite=null;toast('Ссылка приглашения недействительна. Попросите владельца отправить новую.');return;}
    for(const key of Object.keys(incoming))delete incoming[key];
    if(!app.config?.enabled)return;
    advanceScope();app.household=null;
    if(app.session&&verified())loadHouseholds();else renderAuth(app.session?'pending':app.authView==='signup'?'signup':'login');
  });
  const link=parseLink();
  async function boot(){
    const bootGeneration=app.authGeneration;
    try{
      app.config=await raw('/api/config');if(!app.config.enabled)throw Object.assign(new Error('Not configured'),{code:'configuration'});
      app.storageKey=`finance.auth.v1:${app.config.supabaseUrl || location.origin}`;
      const generation=app.authGeneration;const currentAuth=()=>{if(generation!==app.authGeneration)throw new Superseded();};
      let saved;try{saved=JSON.parse(localStorage.getItem(app.storageKey)||'null');}catch(_){saved=null;}
      if(link.error)throw Object.assign(new Error('Link failed'),{code:'invalid_link'});
      if(link.token_hash || link.code){
        const body=link.token_hash?{token_hash:link.token_hash,type:link.type || 'signup'}:{code:link.code,code_verifier:link.code_verifier};
        const result=await raw('/api/auth/confirm',body);currentAuth();if(!persistedSession(result.session))throw Object.assign(new Error('Invalid link'),{code:'invalid_link'});setSession(result.session);if(link.type==='recovery'){renderAuth('reset');return;}
      }else if(link.access_token && link.refresh_token){
        const result=await raw('/api/auth/refresh',{refresh_token:link.refresh_token});currentAuth();if(!persistedSession(result.session))throw Object.assign(new Error('Invalid link'),{code:'invalid_link'});setSession(result.session);if(link.type==='recovery'){renderAuth('reset');return;}
      }else if(persistedSession(saved)){setSession(saved,false);try{await refresh();}catch(error){if(isStale(error))return;setSession(null);toast('Сессия завершилась. Войдите снова.');}}
      if(app.session)await loadHouseholds();else renderAuth('login');
    }catch(error){
      if(isStale(error)||bootGeneration!==app.authGeneration)return;
      if(app.config?.enabled){setSession(null);renderAuth('login');toast(errorMessage(error));}
      else{root.replaceChildren(node('section',{class:'card fatal'},node('div',{class:'eyebrow'},'Семейные финансы'),node('h1',{},'Сервис пока недоступен'),node('p',{},'Подключение не настроено или сервер временно не отвечает. Попробуйте вернуться позже.'),button('Обновить',()=>location.reload(),'primary')));}
    }finally{for(const key of Object.keys(link))delete link[key];}
  }
  window.addEventListener('storage',event=>{
    if(event.key!==app.storageKey)return;advanceScope();rotateAuth();const generation=app.authGeneration;app.household=null;setSession(null,false);
    let saved;try{saved=JSON.parse(event.newValue || 'null');}catch(_){}
    if(persistedSession(saved)){setSession(saved,false);refresh().then(()=>{if(generation===app.authGeneration)loadHouseholds();}).catch(error=>{if(generation===app.authGeneration&&!isStale(error))expireSession();});}else renderAuth('login');
  });
  boot();
})();
