/* Full financial client, isolated by backend, authenticated user and household. */
(() => {
  'use strict';
  if (document.currentScript?.hasAttribute('data-finance-runtime')) { childRuntime(); return; }
  const instances = new Map();
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const clone = value => JSON.parse(JSON.stringify(value));
  const denied = (message, status = 403) => Object.assign(new Error(message), {status});
  const userId = session => String(session?.user?.id || '');
  function backend(config) {
    const parsed = new URL(config.supabaseUrl || config.url);
    if (parsed.protocol !== 'https:' && !(parsed.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname))) throw denied('Invalid backend URL');
    if (parsed.username || parsed.password || parsed.search || parsed.hash || parsed.pathname !== '/') throw denied('Invalid backend URL');
    return parsed.origin;
  }
  function namespace(url, uid, household) {
    return 'finance_v1_' + encodeURIComponent(url) + '_' + uid.toLowerCase() + '_' + household.toLowerCase() + '_';
  }
  function catalog(settings, key) {
    return (Array.isArray(settings?.[key]) ? settings[key] : []).map(row => typeof row === 'string' ? {id: 'legacy-' + key + '-' + encodeURIComponent(row), name: row} : row).filter(row => row && typeof row === 'object' && typeof row.id === 'string' && typeof row.name === 'string');
  }
  function mount(container, options) {
    if (!container || typeof container.replaceChildren !== 'function') throw new TypeError('A ledger container is required');
    const {config, request, refresh, onAccessLost, onSession} = options;
    const url = backend(config), uid = userId(options.session), householdId = String(options.household?.id || options.household?.household_id || '');
    if (!UUID.test(uid) || !UUID.test(householdId) || !options.session?.access_token || typeof request !== 'function') throw denied('Verified account and household required');
    const token = crypto.randomUUID(), prefix = namespace(url, uid, householdId);
    let active = true, verified = false, frame = null, currentSession = clone(options.session), household = null, role = '', generation = 1;
    let resolveReady, rejectReady;
    const ready = new Promise((resolve, reject) => { resolveReady = resolve; rejectReady = reject; });
    // The shell may discard a mount before awaiting it during account switches.
    ready.catch(() => {});
    const current = epoch => active && epoch === generation;
    function loseAccess(error) {
      if (!active) return;
      active = false; verified = false; generation++;
      if (frame) { frame.hidden = true; try { frame.contentWindow.__financeLock?.(); } catch (_) {} }
      rejectReady(error || denied('Household access ended'));
      onAccessLost?.(error || denied('Household access ended'));
    }
    function requireCurrent(epoch) { if (!current(epoch)) throw denied('This ledger is closed', 409); }
    async function membership() {
      const epoch = generation;
      requireCurrent(epoch);
      try {
        const result = await request('/rest/v1/rpc/finance_get_household', {p_household_id: householdId});
        requireCurrent(epoch);
        const found = Array.isArray(result) ? result[0] : result;
        if (!found || String(found.id || found.household_id) !== householdId || !['owner', 'editor', 'viewer'].includes(found.role)) throw denied('Household membership is unavailable');
        household = clone(found); role = found.role; verified = true;
        try { frame?.contentWindow.__financeRole?.(role); } catch (_) {}
        return household;
      } catch (error) {
        if (current(epoch) && (error?.status === 401 || error?.status === 403 || /42501|permission denied|membership|access ended/i.test(String(error?.code || '') + ' ' + String(error?.message || '')))) loseAccess(error);
        throw error;
      }
    }
    async function rpc(name, body, write = false) {
      const epoch = generation;
      await membership(); requireCurrent(epoch);
      if (write && role === 'viewer') throw denied('Viewer accounts cannot change financial data');
      // The immutable household prevents a queued write following a family switch.
      const result = await request('/rest/v1/rpc/' + name, {...body, p_household_id: householdId});
      requireCurrent(epoch);
      return result;
    }
    const bridge = {
      get config() { return {url, key: config.publishableKey || config.key || '', household: householdId}; },
      namespace: prefix,
      get session() { return clone(currentSession); },
      get household() { return clone(household); },
      get role() { return role; },
      get active() { return active && verified; },
      get people() { return catalog(household?.settings, 'people').filter(row => !row.archived).map(row => row.name); },
      get timezone() { return household?.timezone || 'UTC'; },
      get profile() { const name = String(currentSession.user?.user_metadata?.display_name || currentSession.user?.user_metadata?.name || ''); return {name}; },
      membership,
      async api(path, rawBody) {
        const epoch = generation;
        try {
          let value;
          if (path.startsWith('/rest/v1/family_state?')) value = await rpc('finance_read_state', {}, false);
          else if (path === '/rest/v1/rpc/family_state_cas') value = await rpc('finance_state_cas', rawBody || {}, true);
          else throw denied('This integration is unavailable');
          requireCurrent(epoch);
          return {ok: true, status: 200, value};
        } catch (error) {
          requireCurrent(epoch);
          const status = Number(error?.status) || 503;
          return {ok: false, status, value: {message: status === 403 ? 'Access denied' : 'Request failed'}};
        }
      },
      async refresh() {
        const epoch = generation;
        requireCurrent(epoch);
        if (typeof refresh !== 'function') return currentSession;
        const next = await refresh(); requireCurrent(epoch);
        if (!next?.access_token || userId(next) !== uid) { loseAccess(denied('Account session changed', 401)); return null; }
        currentSession = clone(next); onSession?.(clone(next)); return clone(next);
      },
      ready() { if (active && verified) { frame.hidden = false; frame.style.visibility = 'visible'; resolveReady(frame); } },
      fail(error) { if (active) rejectReady(error); },
      close() { loseAccess(denied('Return to account access', 401)); },
    };
    instances.set(token, bridge);
    const instance = {
      ready, namespace: prefix,
      get iframe() { return frame; },
      unmount() {
        if (active) { active = false; verified = false; generation++; }
        try { frame?.contentWindow.__financeLock?.(); } catch (_) {}
        frame?.remove(); instances.delete(token); rejectReady(denied('Ledger closed', 409));
      },
    };
    // Load a fixed same-origin document with its own CSP. No account or household
    // data is serialized into markup, a script, the URL or the iframe name.
    (async () => {
      const epoch = generation;
      await membership(); requireCurrent(epoch);
      frame = document.createElement('iframe'); frame.className = 'finance-ledger-frame'; frame.title = 'Финансы семьи'; frame.hidden = true;
      frame.style.cssText = 'visibility:hidden;width:100%;height:calc(100vh - 76px);min-height:650px;border:0;background:#f4f6fb';
      frame.setAttribute('referrerpolicy', 'no-referrer');
      frame.src = '/ledger-template.html#' + token; container.replaceChildren(frame);
    })().catch(error => { if (active) { rejectReady(error); if (!verified) loseAccess(error); } });
    return instance;
  }

  // This code executes in the trusted, generated iframe, after the full client.
  function childRuntime() {
    'use strict';
    const bridge = window.__FINANCE_BRIDGE__;
    if (!bridge?.active) return;
    let alive = true, writer = bridge.role !== 'viewer';
    const canWrite = () => alive && bridge.active && writer && session;
    const blocked = () => { toast('Режим просмотра: изменения доступны владельцу и редакторам.'); return false; };
    const rawSaveLocal = saveLocal, rawPending = savePendingLocal, rawConflict = saveSyncConflict;
    saveLocal = () => canWrite() ? rawSaveLocal() : false;
    savePendingLocal = () => canWrite() ? rawPending() : false;
    saveSyncConflict = (...args) => canWrite() ? rawConflict(...args) : false;
    // Every network operation rechecks live membership in the parent bridge.
    api = async (path, options = {}) => {
      if (!alive || !bridge.active) throw new Error('Ledger closed');
      const epoch = authEpoch;
      let body; if (options.body) body = JSON.parse(options.body);
      const packet = await bridge.api(path, body);
      if (!alive || !bridge.active || epoch !== authEpoch) throw new Error('Ledger closed');
      return {ok: packet.ok, status: packet.status, json: async () => packet.value};
    };
    refreshSession = async () => {
      const epoch = authEpoch, next = await bridge.refresh();
      if (!alive || !bridge.active || epoch !== authEpoch || !next) return false;
      session = next; return true;
    };
    verifyHouseholdAccess = async () => { try { await bridge.membership(); return alive && bridge.active; } catch (_) { return false; } };
    verifyCachedSession = verifyHouseholdAccess;
    login = gateLogin = async () => false;
    logout = () => bridge.close();
    loadWeather = async () => null;
    telegramNotify = async () => false;
    sendTelegramMessage = async () => { throw new Error('Интеграция недоступна'); };
    testTelegram = async () => false;
    v88SendFeedback = v88ShareFeedback = async event => { event?.preventDefault?.(); toast('Обращение можно скачать файлом.'); return false; };
    v881OpenEmail = () => false;
    // Browser events and direct calls share the same role guard; the server also
    // rejects viewer CAS requests independently of this interface.
    const mutations = ['addEntry','deleteEntry','saveEdit','v98OpenReviewEntry','v98SaveCategoryReview','addBoardItem','deleteBoardItem','addGoal','deleteGoal','addGoalDeposit','saveSettings','addBirthday','deleteBirthday','addChore','completeChore','deleteChore','v77CreateInstallment','v77LinkPayment','v77PayPart','v77DeleteInstallment','v77UpdatePart','v78ToggleMortgage','v84LinkRecurring','v84Remove','v84AddBudget','v84AddRecurring','v84ConfirmRecurring','v84SaveAccount','v87ApplyAdvisor','v97CommitFavorite','v97SubmitFavoriteEditor','v97AddFavorite','v97SaveFavoriteFromForm','v97SaveFavoriteFromEntry','v97RenameFavorite','v97RemoveFavorite','v96StageBranding','v96SaveBranding','v96ResetBranding','updateTelegramSetting'];
    const mutatorSet = new Set(mutations);
    for (const name of mutations) {
      const original = window[name];
      if (typeof original === 'function') window[name] = function(...args) { return canWrite() ? original.apply(this, args) : Promise.resolve(blocked()); };
    }
    const readActions = new Set(['drill','monthly-review-group','navigate']);
    function mutationControl(node) {
      if (!(node instanceof Element)) return false;
      const action = node.closest('[data-record-action]');
      if (action && !readActions.has(action.dataset.recordAction)) return true;
      const handler = node.closest('[onclick],[onchange],[onsubmit]');
      const code = ['onclick','onchange','onsubmit'].map(key => handler?.getAttribute(key) || '').join(' ');
      return [...mutatorSet].some(name => new RegExp('\\b' + name + '\\s*\\(').test(code)) || !!node.closest('#importFile,#v90Save,#v77NewInstallmentBtn,#v77SaveInstallmentBtn,#v84AccountSave,[data-setting],.telegram-settings-card,[data-v78-mortgage],[data-v84-link],[data-v77-pay],[data-v77-link],[data-v77-match],[data-v77-date],[data-v77-save-date],[data-v77-delete]');
    }
    for (const type of ['click','change','submit']) document.addEventListener(type, event => {
      if (!canWrite() && mutationControl(event.target)) { event.preventDefault(); event.stopImmediatePropagation(); }
    }, true);
    function roleControls() {
      if (!alive) return;
      document.querySelectorAll('button,input,select,textarea').forEach(node => {
        if (mutationControl(node)) {
          if (!writer) { node.dataset.financeViewerDisabled = '1'; if (!node.disabled) node.disabled = true; node.title = 'Только просмотр'; }
          else if (node.dataset.financeViewerDisabled) { delete node.dataset.financeViewerDisabled; node.disabled = false; }
        }
      });
      const button = document.getElementById('authBtn'); if (button) button.hidden = true;
      document.querySelectorAll('.telegram-settings-card').forEach(node => { node.hidden = true; });
    }
    window.__financeRole = role => {
      const nextWriter = role !== 'viewer', changed = writer !== nextWriter;
      if (changed) {
        // A role change invalidates reads/acks from the previous permissions.
        // Regaining edit rights restores untouched raw queues before any sync.
        authEpoch++; writer = nextWriter;
        if (nextWriter && alive && session) { state = loadLocal(); knownEntries = entryMap(); renderAll(); }
      }
      roleControls();
    };
    window.__financeLock = () => { alive = false; authEpoch++; stopCloudSync(); session = null; showGate(); document.getElementById('appRoot').style.display = 'none'; };
    let repaint = false;
    new MutationObserver(() => { if (!repaint) { repaint = true; queueMicrotask(() => { repaint = false; roleControls(); }); } }).observe(document.body, {subtree: true, childList: true, attributes: true, attributeFilter: ['disabled']});

    const metadata = bridge.household;
    const normalizeCatalog = (rows, key) => (rows || []).map(row => typeof row === 'string' ? {id: 'legacy-' + key + '-' + encodeURIComponent(row), name: row} : row).filter(row => row && typeof row.id === 'string' && typeof row.name === 'string');
    const peopleCatalog = normalizeCatalog(metadata.settings?.people, 'people');
    const categories = normalizeCatalog(metadata.settings?.categories, 'categories');
    const activeCategories = categories.filter(row => !row.archived);
    const label = row => String(row.name || '');
    V90_CATEGORIES.splice(0, V90_CATEGORIES.length, ...activeCategories.map(row => [label(row), label(row), (Array.isArray(row.aliases) ? row.aliases : []).join(' ')]));
    CATS.splice(0, CATS.length, ...activeCategories.map(label));
    for (const row of activeCategories) if (!Object.hasOwn(EXPENSE_GROUP_NAME, label(row))) EXPENSE_GROUP_NAME[label(row)] = label(row);
    const configuredGroups = new Map();
    const groupIds = new Map(EXPENSE_GROUPS.map(group => [group.title, v98GroupId(group)]));
    for (const row of activeCategories) {
      const name = label(row), title = expenseEntryGroup({type: 'expense', category: name});
      if (!configuredGroups.has(title)) configuredGroups.set(title, {id: groupIds.get(title) || 'custom:' + encodeURIComponent(title), title, values: [], legacy: []});
      configuredGroups.get(title).values.push(name);
    }
    EXPENSE_GROUPS.splice(0, EXPENSE_GROUPS.length, ...configuredGroups.values());
    categoryOptions = (selected = '', withAll = false) => {
      const rows = activeCategories.map(label);
      if (withAll) for (const row of state.entries) if (row.category && !rows.includes(row.category)) rows.push(row.category);
      if (selected && !rows.includes(selected)) rows.push(selected);
      return (withAll ? '<option value="">Все категории</option>' : '<option value="">' + (rows.length ? 'Выберите категорию' : 'Добавьте категории в настройках семьи') + '</option>') + rows.map(name => '<option value="' + esc(name) + '"' + (name === selected ? ' selected' : '') + '>' + esc(name) + '</option>').join('');
    };
    const rawCategoryPaint = v90Paint;
    v90Paint = function() {
      const expanded = v91Expanded; v91Expanded = true;
      try { rawCategoryPaint(); } finally { v91Expanded = expanded; }
      document.querySelectorAll('#v90Quick [data-cat]').forEach(node => { if (!CATS.includes(node.dataset.cat)) node.remove(); });
      const toggle = document.getElementById('v91All'); if (toggle) toggle.hidden = true;
      if (!activeCategories.length) { const hint = document.getElementById('v92SearchHint'); if (hint) hint.textContent = 'Добавьте категории в настройках семьи в верхней панели.'; }
    };
    const rawOpenEdit = openEdit;
    openEdit = function(id, context) {
      rawOpenEdit(id, context);
      const row = state.entries.find(entry => entry.id === id), select = document.getElementById('xWho');
      if (row?.who && select) {
        if (![...select.options].some(option => option.value === row.who)) select.add(new Option(row.who, row.who));
        select.value = row.who;
      }
    };
    // IDs are additive. Existing display labels and historical IDs are retained;
    // a catalog rename never rewrites earlier transactions.
    const entryMap = () => new Map(state.entries.map(row => [row.id, {category: row.category, person: row.beneficiary || row.who}]));
    function identifyEntries(before) {
      for (const row of state.entries) {
        const previous = before.get(row.id);
        const category = categories.find(item => !item.archived && item.name === row.category);
        const person = peopleCatalog.find(item => !item.archived && item.name === (row.beneficiary || row.who));
        if (!previous || previous.category !== row.category) { if (category) row.category_id = category.id; else delete row.category_id; }
        if (!previous || previous.person !== (row.beneficiary || row.who)) { if (person) row.person_id = person.id; else delete row.person_id; }
      }
    }
    const rawSaveAll = saveAll;
    let knownEntries = new Map();
    saveAll = function() {
      if (!canWrite()) return Promise.resolve(false);
      identifyEntries(knownEntries); knownEntries = entryMap();
      return rawSaveAll();
    };
    const rawSync = syncFromCloud;
    syncFromCloud = async function() {
      if (!alive || !bridge.active) return false;
      if (!writer) {
        if (cloudSyncBusy) return false;
        cloudSyncBusy = true;
        const epoch = authEpoch;
        try {
          const cloud = await fetchCloudState();
          if (!alive || !bridge.active || epoch !== authEpoch) return false;
          if (cloud) { state = cloud; knownEntries = entryMap(); renderAll(); updateSync('Только просмотр · облачная копия обновлена'); }
          return !!cloud;
        } catch (_) { if (alive && bridge.active) updateSync('Не удалось обновить облачную копию'); return false; }
        finally { cloudSyncBusy = false; }
      }
      const result = await rawSync();
      if (alive && bridge.active) { knownEntries = entryMap(); roleControls(); }
      return result;
    };
    const originalRenderAll = renderAll;
    renderAll = function() {
      if (!alive || !bridge.active) return;
      const categoryFilter = document.getElementById('fCat');
      if (categoryFilter) { const selected = categoryFilter.value; categoryFilter.innerHTML = categoryOptions(selected, true); categoryFilter.value = selected; }
      for (const [id, values] of [['fWho', state.entries.map(row => row.beneficiary || row.who)], ['fGroup', state.entries.filter(row => row.type === 'expense').map(expenseEntryGroup)]]) {
        const select = document.getElementById(id);
        if (select) for (const value of values) if (value && ![...select.options].some(option => option.value === value)) select.add(new Option(value, value));
      }
      originalRenderAll();
      const heading = document.querySelector('.brand-heading');
      if (heading) { const small = heading.querySelector('small'); heading.replaceChildren(document.createTextNode(metadata.name || 'Семейный Банк')); if (small) heading.append(small); }
      if (!activeCategories.length) {
        const categoryPrompt = document.getElementById('saveMsg');
        if (categoryPrompt) categoryPrompt.textContent = 'Добавьте категории в настройках семьи в верхней панели.';
      }
      roleControls();
    };
    (async () => {
      showGate();
      if (!(await verifyHouseholdAccess()) || !alive) throw new Error('Membership verification failed');
      session = bridge.session;
      state = loadLocal();
      knownEntries = entryMap();
      initForm();
      const choreWho = document.getElementById('choreWho');
      if (choreWho) { choreWho.replaceChildren(...[...bridge.people, 'Семья'].map(name => new Option(name, name))); }
      for (const node of document.querySelectorAll('.family-avatars,.board-family-line')) {
        node.replaceChildren(...bridge.people.map(name => { const member = document.createElement('span'); member.textContent = name; return member; }));
      }
      setStatus(writer ? 'Финансы семьи' : 'Только просмотр', true);
      showApp(); startCloudSync(); roleControls(); bridge.ready();
    })().catch(error => bridge.fail(error));
  }
  window.FinanceLedger = Object.freeze({mount, unmount(instance) { instance?.unmount(); }, namespace, bridge(token) { return instances.get(token); }});
})();
