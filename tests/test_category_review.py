"""Explicit category review using synthetic local rows; external requests are blocked."""
import json
import unittest

import test_local_data_safety as harness


class CategoryReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open
    snapshot = harness.LocalDataSafety.snapshot

    def prepare(self):
        self.open()
        self.period = self.page.evaluate("""() => {
          session=null;stopCloudSync();state=blankState();localStorage.clear();showApp();
          const m=previousMonthKey(month());
          window.reviewRow=(id,fields={})=>({id,type:'expense',date:m+'-05',amount:120.50,
            category:'Прочее',store:'ChatGPT',comment:'',subcategory:'',beneficiary:'',
            who:'Legacy recipient',pay:'Legacy payment',created_at:'2020-01-01T00:00:00Z',
            updated_at:'2020-01-02T00:00:00Z',futureField:{keep:[null,true,{nested:'unchanged'}]},
            ...fields});
          state.entries=[reviewRow('digital'),reviewRow('diapers',{store:'Fictional shop',
            comment:'Подгузники для собаки',beneficiary:'Алиса'}),
            reviewRow('ambiguous',{store:'КБ',category:'Вкусняшки'}),
            reviewRow('current',{date:month()+'-05'}),
            reviewRow('ordinary',{store:'Fictional shop',category:'ЖКХ',comment:'Интернет'})];
          renderAll();clearEntry();document.getElementById('eAmount').value='77,25';
          document.getElementById('eComment').value='Unsaved main entry draft';
          document.getElementById('analyticsMonth').value=m;go('analytics');return m;
        }""")
        self.before = self.snapshot()

    def open_review(self):
        self.page.evaluate('v98OpenCategoryReview()')
        self.assertTrue(self.page.locator('#categoryReview').is_visible())

    def row_ids(self):
        return self.page.locator('#v98ReviewRows [data-v98-review-id]').evaluate_all(
            '(rows)=>rows.map(row=>row.dataset.v98ReviewId)')

    def edit(self, identifier='digital'):
        self.page.evaluate('id=>v98OpenReviewEntry(id)', identifier)
        self.assertTrue(self.page.locator('#editModal').is_visible())

    def save(self):
        self.page.locator('#editModal').get_by_role('button', name='Сохранить', exact=True).click()

    def signals(self, fields):
        return self.page.evaluate("""fields=>fields.map(patch=>
          v98CategoryReviewSignal(reviewRow('signal',patch)))""", fields)

    def test_digital_service_suggests_two_active_choices_without_auto_assignment(self):
        self.prepare()
        signals = self.signals([{'store':'ChatGPT'}, {'store':'Fictional shop','comment':'OpenAI'},
                                {'store':'Fictional shop','subcategory':'Chat GPT'}])
        for signal in signals:
            self.assertEqual(signal['kind'], 'suggestion')
            self.assertEqual(set(signal['suggestions']), {'Подписки','Работа'})
            self.assertTrue(signal['reason'])
        self.assertEqual(self.signals([{'category':'Подписки'}, {'category':'Работа'}]), [None,None])
        filtered = self.page.evaluate("""() => {
          const saved=V90_CATEGORIES.slice();try{
            V90_CATEGORIES.splice(V90_CATEGORIES.findIndex(row=>row[0]==='Работа'),1);
            return v98CategoryReviewSignal(reviewRow('filtered'));
          } finally {V90_CATEGORIES.splice(0,V90_CATEGORIES.length,...saved)}
        }""")
        self.assertNotIn('Работа', filtered['suggestions'])
        self.assertEqual(self.snapshot(), self.before)

    def test_diapers_follow_explicit_purpose_and_never_merchant_or_beneficiary(self):
        self.prepare()
        patches = [{'store':'Fictional shop','comment':text} for text in
                   ['Подгузники для собаки','Памперсы для взрослых','Подгузники детские']]
        signals = self.signals(patches)
        self.assertEqual([s['suggestions'] for s in signals],
                         [['Животные'],['Аптека и медицина'],['Дети']])
        self.assertEqual(self.signals([
            {'store':'Подгузники для собаки','comment':'','subcategory':''},
            {'store':'Fictional shop','comment':'','subcategory':'','beneficiary':'Подгузники для взрослых'},
            {'store':'Fictional shop','comment':'Подгузники для собаки','category':'Животные'},
        ]), [None,None,None])
        self.assertEqual(self.signals([{'store':'Fictional shop','subcategory':'Пеленки для кошки'}])[0]['suggestions'], ['Животные'])
        self.assertEqual(self.snapshot(), self.before)

    def test_kb_is_neutral_clarification_only_without_informative_purchase_text(self):
        self.prepare()
        signals = self.signals([{'store':merchant,'category':category}
                                for merchant in ['КБ','Красное и Белое']
                                for category in ['Вкусняшки','Прочее']])
        for signal in signals:
            self.assertEqual(signal['kind'], 'clarify')
            self.assertEqual(signal['suggestions'], [])
            self.assertTrue(signal['reason'])
        self.assertEqual(self.signals([
            {'store':'КБ','category':'Вкусняшки','comment':'Шоколад и чипсы'},
            {'store':'КБ','category':'Продукты','comment':'Молоко и хлеб'},
            {'store':'КБ','category':'Прочее','subcategory':'Молоко и хлеб'},
            {'store':'Fictional shop','category':'Вкусняшки'},
        ]), [None,None,None,None])

    def test_loans_recurring_nonexpenses_claimed_duplicate_and_deleted_rows_are_excluded(self):
        self.prepare()
        result = self.page.evaluate("""() => {
          const excluded=[{category:'Кредит'},{installmentId:'plan'},{installmentPartId:'part'},
            {recurringId:'regular'},{recurringPeriod:month()},{mortgagePayment:true},
            {obligationType:'mortgage'},{paymentKey:'payment'},{scheduledDate:today()},
            {debtRepayment:true},{accountingMode:'purchase'},{autoGenerated:true},{generated:true},{type:'income'},
            {type:'transfer'},{type:'cash'}];
          const signals=excluded.map((patch,i)=>v98CategoryReviewSignal(reviewRow('excluded-'+i,patch)));
          state.entries=[reviewRow('claimed'),reviewRow('deleted'),reviewRow('duplicate'),
            reviewRow('duplicate'),reviewRow('live')];
          state.installments=[{id:'plan',parts:[],links:{part:'claimed'}}];
          state.deletedEntries.deleted='2026-01-01T00:00:00Z';
          return {signals};
        }""")
        self.assertTrue(all(signal is None for signal in result['signals']))
        before = self.snapshot();self.open_review()
        self.assertEqual(self.row_ids(), ['live'])
        self.assertEqual(self.snapshot(), before)

    def test_month_alltime_and_kind_filter_do_not_mutate_finances_or_main_draft(self):
        self.prepare();draft = self.page.evaluate('v97DraftFields()');self.open_review()
        self.assertEqual(self.page.locator('#v98ReviewMonth').input_value(), self.period)
        self.assertEqual(set(self.row_ids()), {'digital','diapers','ambiguous'})
        self.page.locator('#v98ReviewFilter').select_option('clarify')
        self.assertEqual(self.row_ids(), ['ambiguous'])
        self.page.locator('#v98ReviewFilter').select_option('suggestion')
        self.assertEqual(set(self.row_ids()), {'digital','diapers'})
        self.page.locator('#v98ReviewMonth').select_option('all')
        self.assertEqual(set(self.row_ids()), {'digital','diapers','current'})
        self.page.locator('#v98ReviewFilter').select_option('all')
        self.assertEqual(set(self.row_ids()), {'digital','diapers','ambiguous','current'})
        self.assertEqual(self.snapshot(), self.before)
        self.assertEqual(self.page.evaluate('v97DraftFields()'), draft)

    def test_untrusted_ids_and_names_render_as_text_and_open_the_exact_same_amount_row(self):
        self.prepare()
        malicious = "x');window.__reviewInjected=true;//<img id=review-injected src=x>"
        self.page.evaluate("""id=>{
          window.__reviewInjected=false;state.entries[0].id=id;
          state.entries[0].store='ChatGPT <img id=review-name-injected src=x onerror="window.__reviewInjected=true">';
        }""", malicious)
        before = self.snapshot();self.open_review()
        row = self.page.locator('#v98ReviewRows [data-v98-review-id]').filter(has_text='ChatGPT <img')
        self.assertEqual(row.count(), 1)
        self.assertEqual(row.get_attribute('data-v98-review-id'), malicious)
        row.locator('[data-record-action="category-review-entry"]').click()
        self.assertEqual(self.page.evaluate('editId'), malicious)
        self.assertFalse(self.page.evaluate('window.__reviewInjected'))
        self.assertEqual(self.page.locator('#review-injected,#review-name-injected').count(), 0)
        self.assertEqual(self.snapshot(), before)

    def test_suggestions_are_unselected_and_only_explicit_choice_changes_category(self):
        self.prepare();self.open_review();self.edit()
        self.assertEqual(self.page.locator('#xCat').input_value(), 'Прочее')
        choices = self.page.locator('#editModal [data-record-action="category-review-choose"]')
        self.assertEqual(choices.count(), 2)
        self.assertFalse(choices.evaluate_all('(rows)=>rows.some(el=>el.getAttribute("aria-pressed")==="true")'))
        self.assertEqual(self.snapshot(), self.before)
        choices.filter(has_text='Подписки').click()
        self.assertEqual(self.page.locator('#xCat').input_value(), 'Подписки')
        self.assertEqual(self.snapshot(), self.before)

    def test_category_only_save_preserves_every_other_field_and_missing_or_null_who(self):
        self.prepare()
        for variant in ['legacy','null','absent']:
            with self.subTest(who=variant):
                self.page.evaluate("""variant=>{
                  if(variant==='legacy')delete window.__FINANCE_BRIDGE__;
                  else window.__FINANCE_BRIDGE__={active:true,role:variant==='null'?'owner':'editor'};
                  state.entries[0]=reviewRow('digital');
                  if(variant==='null')state.entries[0].who=null;
                  if(variant==='absent')delete state.entries[0].who;
                }""", variant)
                before = self.snapshot();old = json.loads(before['state']);draft = self.page.evaluate('v97DraftFields()')
                self.assertEqual(self.page.locator('#eAmount').input_value(), '77,25')
                self.assertEqual(self.page.locator('#eComment').input_value(), 'Unsaved main entry draft')
                self.open_review()
                self.assertEqual(self.page.evaluate('v97DraftFields()'), draft)
                self.edit();self.page.locator('#xCat').select_option('Подписки')
                self.assertEqual(self.page.evaluate('v97DraftFields()'), draft)
                self.save()
                self.page.wait_for_function("!document.getElementById('editModal').classList.contains('open')")
                new = json.loads(self.snapshot()['state'])
                changed = new['entries'][0];original = old['entries'][0]
                self.assertEqual(changed['category'], 'Подписки')
                self.assertNotEqual(changed['updated_at'], original['updated_at'])
                for key in ['category','updated_at']:
                    changed.pop(key);original.pop(key)
                self.assertEqual(changed, original)
                self.assertEqual(new['entries'][1:], old['entries'][1:])
                self.assertEqual(self.page.locator('#v98ReviewMonth').input_value(), self.period)
                self.assertEqual(self.page.evaluate('v97DraftFields()'), draft)

    def test_same_category_noop_and_cancel_do_not_write_storage_or_timestamps(self):
        self.prepare()
        self.page.evaluate("for(let i=0;i<35;i++)state.entries.push(reviewRow('scroll-'+i))")
        self.open_review()
        self.page.evaluate('window.scrollTo(0,600)')
        expected_scroll = self.page.evaluate('window.scrollY')
        self.assertGreater(expected_scroll, 0)
        before = self.snapshot();draft = self.page.evaluate('v97DraftFields()')
        self.edit();self.save()
        self.assertEqual(self.snapshot(), before)
        if self.page.locator('#editModal').is_visible():
            self.page.evaluate('closeEdit()')
        self.edit();self.page.locator('#xCat').select_option('Работа')
        self.assertEqual(self.page.evaluate('v97DraftFields()'), draft)
        self.page.locator('#editModal').get_by_role('button', name='Отмена', exact=True).click()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.page.evaluate('v97DraftFields()'), draft)
        self.assertTrue(self.page.locator('#categoryReview').is_visible())
        self.assertEqual(self.page.locator('#v98ReviewMonth').input_value(), self.period)
        self.page.wait_for_function('expected=>Math.abs(window.scrollY-expected)<=1', arg=expected_scroll)

    def test_changed_deleted_linked_and_duplicate_sources_block_apply_without_any_write(self):
        self.prepare()
        mutations = {
            'unknown field': "state.entries[0].futureField.keep.push('remote mutation')",
            'amount': "state.entries[0].amount=121",
            'removed': "state.entries=state.entries.filter(e=>e.id!=='digital')",
            'tombstone': "state.deletedEntries.digital=new Date().toISOString()",
            'recurring': "state.entries[0].recurringId='remote-plan'",
            'claimed': "state.installments=[{id:'remote-plan',parts:[],links:{p:'digital'}}]",
            'duplicate': "state.entries.push({...state.entries[0]})",
        }
        for label, mutation in mutations.items():
            with self.subTest(change=label):
                self.page.evaluate("state=blankState();state.entries=[reviewRow('digital')]")
                self.open_review();self.edit();self.page.locator('#xCat').select_option('Подписки')
                self.page.evaluate(mutation);before = self.snapshot();self.save()
                self.assertEqual(self.snapshot(), before)
                self.assertTrue(self.page.locator('#editModal').is_visible())
                self.assertTrue(self.page.locator('#v98CategoryEditStatus').inner_text().strip())
                self.page.evaluate('closeEdit()')
        self.page.evaluate("state=blankState();state.entries=[reviewRow('digital')]")
        self.open_review();self.edit()
        self.page.evaluate("""() => {
          const choice=document.getElementById('xCat');
          for(const option of [...choice.options])if(option.value==='Кредит')option.remove();
          choice.add(new Option('Injected obligation category','Кредит'));choice.value='Кредит';
        }""")
        before = self.snapshot();draft = self.page.evaluate('v97DraftFields()');self.save()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.page.evaluate('v97DraftFields()'), draft)
        self.assertTrue(self.page.locator('#editModal').is_visible())
        self.assertRegex(self.page.locator('#v98CategoryEditStatus').inner_text().lower(), r'обязательств.*кредит')

    def test_locked_direct_apply_and_logout_refuse_private_editor_and_financial_writes(self):
        self.prepare()
        for role in ['owner','editor']:
            with self.subTest(allowed=role):
                self.page.evaluate("role=>window.__FINANCE_BRIDGE__={active:true,role}", role)
                self.open_review();self.edit();self.page.evaluate('closeEdit()')
        for bridge in [{'active':True,'role':'viewer'},{'active':True,'role':'unknown'},
                       {'active':True},{'active':False,'role':'owner'}]:
            with self.subTest(denied=bridge):
                self.page.evaluate('delete window.__FINANCE_BRIDGE__')
                self.open_review();self.edit();self.page.locator('#xCat').select_option('Подписки')
                self.page.evaluate('bridge=>window.__FINANCE_BRIDGE__=bridge', bridge)
                before = self.snapshot()
                self.page.evaluate('v98SaveCategoryReview()')
                self.assertEqual(self.snapshot(), before)
                self.page.evaluate('closeEdit();v98OpenReviewEntry("digital");v98SaveCategoryReview()')
                self.assertFalse(self.page.locator('#editModal').is_visible())
                self.assertEqual(self.snapshot(), before)
        self.page.evaluate('delete window.__FINANCE_BRIDGE__')
        self.open_review();self.edit();self.page.locator('#xCat').select_option('Подписки')
        before = self.snapshot()
        self.page.evaluate("document.getElementById('appRoot').classList.add('auth-locked');v98SaveCategoryReview()")
        self.assertEqual(self.snapshot(), before)
        self.page.evaluate("document.getElementById('appRoot').classList.remove('auth-locked');logout()")
        self.assertFalse(self.page.locator('#editModal').is_visible())
        before = self.snapshot()
        self.page.evaluate("v98OpenReviewEntry('digital');v98SaveCategoryReview()")
        self.assertFalse(self.page.locator('#editModal').is_visible())
        self.assertEqual(self.snapshot(), before)

    def test_quota_failure_reports_unconfirmed_persistence_without_a_cloud_success(self):
        self.prepare();self.open_review();self.edit();self.page.locator('#xCat').select_option('Подписки')
        self.page.evaluate("""() => {
          const native=Storage.prototype.setItem;
          Storage.prototype.setItem=function(key,value){
            if(key===KEYS.state||key===KEYS.pending)throw new DOMException('Synthetic quota','QuotaExceededError');
            return native.call(this,key,value);
          };
        }""")
        self.save()
        self.page.wait_for_function("[document.getElementById('v98ReviewStatus'),document.getElementById('v98CategoryEditStatus')].some(el=>el&&el.textContent.trim())")
        status = self.page.locator('#v98ReviewStatus').inner_text()
        if self.page.locator('#v98CategoryEditStatus').count():
            status += ' ' + self.page.locator('#v98CategoryEditStatus').inner_text()
        self.assertRegex(status.lower(), r'не сохран|ошиб|памят|повтор|не удалось|не подтвержден')
        self.assertNotRegex(status.lower(), r'сохранен[оа]? в облак|сохранён[оа]? в облак')
        self.assertIsNone(self.page.evaluate('localStorage.getItem(KEYS.pending)'))

    def test_late_save_ack_after_logout_never_reopens_private_review_or_editor(self):
        self.prepare();self.open_review();self.edit();self.page.locator('#xCat').select_option('Подписки')
        self.page.evaluate("() => {saveAll=()=>new Promise(resolve=>window.__finishCategorySave=resolve)}")
        self.save();self.page.wait_for_function("typeof window.__finishCategorySave==='function'")
        self.page.evaluate('logout();window.__finishCategorySave(true)')
        self.page.wait_for_timeout(30)
        self.assertFalse(self.page.locator('#editModal').is_visible())
        self.assertFalse(self.page.locator('#categoryReview').is_visible())
        self.assertTrue(self.page.locator('#appRoot').evaluate("el=>el.classList.contains('auth-locked')"))

    def test_review_and_category_editor_controls_fit_phone_and_desktop_widths(self):
        self.prepare()
        self.page.evaluate("state.entries[0].store='ChatGPT '+('Оченьдлинноеназваниесервиса'.repeat(4))")
        before = self.snapshot();draft = self.page.evaluate('v97DraftFields()')
        for width in [320,390,1280]:
            with self.subTest(width=width):
                self.page.set_viewport_size({'width':width,'height':900});self.open_review()
                review = self.page.evaluate("""() => ({width:innerWidth,body:document.body.scrollWidth,
                  controls:[...document.querySelectorAll('#categoryReview select,#categoryReview button')]
                    .filter(el=>el.getClientRects().length).map(el=>{const r=el.getBoundingClientRect();
                      return {label:el.textContent,left:r.left,right:r.right}})})""")
                self.assertLessEqual(review['body'], width)
                self.assertGreater(len(review['controls']), 3)
                for control in review['controls']:
                    self.assertGreaterEqual(control['left'], 0, control['label'])
                    self.assertLessEqual(control['right'], width, control['label'])
                self.edit()
                editor = self.page.evaluate("""() => {
                  const modal=document.querySelector('#editModal .modal');return {
                    width:modal.clientWidth,content:modal.scrollWidth,
                    controls:[...document.querySelectorAll('#editModal select,#editModal button')]
                      .filter(el=>el.getClientRects().length).map(el=>{const r=el.getBoundingClientRect();
                        return {label:el.textContent,left:r.left,right:r.right}})};
                }""")
                self.assertLessEqual(editor['content'], editor['width']+1)
                self.assertGreater(len(editor['controls']), 3)
                for control in editor['controls']:
                    self.assertGreaterEqual(control['left'], 0, control['label'])
                    self.assertLessEqual(control['right'], width, control['label'])
                self.page.evaluate('closeEdit()')
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.page.evaluate('v97DraftFields()'), draft)

    def test_category_save_refreshes_cached_home_group_totals_before_returning_home(self):
        self.prepare()
        groups = self.page.evaluate("""() => {
          state.entries=[reviewRow('digital',{category:'Развлечения'}),
            reviewRow('unrelated',{category:'Развлечения',store:'Fictional cinema',amount:20})];
          document.getElementById('homeMonth').value=document.getElementById('analyticsMonth').value;
          document.getElementById('fMonth').value=document.getElementById('analyticsMonth').value;
          renderAll();return {old:expenseGroup('Развлечения'),next:expenseGroup('Подписки')};
        }""")
        self.assertNotEqual(groups['old'], groups['next'])
        self.assertIn('140,50', self.page.locator('#categoryLegend').inner_text())
        draft = self.page.evaluate('v97DraftFields()');before = self.page.evaluate('state.entries')
        self.open_review();self.edit();self.page.locator('#xCat').select_option('Подписки');self.save()
        self.page.wait_for_function("!document.getElementById('editModal').classList.contains('open')")
        self.page.evaluate("go('home')")
        old_group = self.page.locator('#categoryLegend button').filter(has_text=groups['old'])
        new_group = self.page.locator('#categoryLegend button').filter(has_text=groups['next'])
        self.assertEqual(old_group.count(), 1)
        self.assertEqual(new_group.count(), 1)
        self.assertRegex(old_group.locator('b').inner_text(), r'^20\s*₽')
        self.assertIn('120,50', new_group.inner_text())
        self.assertIn('140,50', self.page.locator('#donutTotal').inner_text())
        self.assertEqual(self.page.evaluate('v97DraftFields()'), draft)
        self.page.evaluate("go('analytics')")
        self.assertIn(groups['next'], self.page.locator('#aCats').inner_text())
        self.page.evaluate("go('history')")
        changed = self.page.locator('#historyBody tr').filter(has_text='ChatGPT')
        self.assertEqual(changed.locator('.v76-cat').inner_text(), 'Подписки')
        self.assertEqual(self.page.evaluate('state.entries[1]'), before[1])
        self.assertEqual(self.page.evaluate('v97DraftFields()'), draft)


if __name__ == '__main__':
    unittest.main()
