"""Installment row regressions with fictional local data and blocked external traffic."""
import unittest

import test_local_data_safety as harness


class InstallmentRows(unittest.TestCase):
    WIDTHS = (320, 390, 820, 844, 1024, 1920)

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

    def prepare(self, width, scale, linked=False):
        self.page.set_viewport_size({'width': width, 'height': 920})
        self.open()
        self.page.evaluate("""linked => {
          session=null;stopCloudSync();state=blankState();localStorage.clear();
          today=()=> '2026-11-01';month=()=> '2026-11';
          loanScheduleData=()=>[{n:1,payDate:'2099-12-01',periodEnd:'2099-12-01',
            payment:1,interest:0,body:1,balance:0}];
          weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now();
          telegramNotify=async()=>false;
          const entry=(id,amount)=>({id,type:'expense',date:'2026-11-01',amount,
            category:'Кредит',who:'Не указано',store:'Fictional payment',
            comment:'Synthetic saved expense',futureField:{keep:['saved',id]}});
          state.entries=[entry('fictional-free-payment',100.25),entry('fictional-unrelated',17.49)];
          const plan={id:'fictional-plan',kind:'split',title:'Fictional four part purchase',
            provider:'Fictional provider',amount:401,accountingMode:'payments',
            parts:['a','b','c','d'].map((id,n)=>({id:'fictional-part-'+id,
              date:'2026-11-'+String(2+n*7).padStart(2,'0'),amount:100.25,
              futurePartField:{keep:id}})),links:{},
            created_at:'2026-10-31T12:00:00Z',updated_at:'2026-10-31T12:00:00Z',
            futurePlanField:{keep:['unchanged',401]}};
          if(linked){
            state.entries.push(entry('fictional-full-payment',100.25),entry('fictional-partial-payment',40));
            plan.links={'fictional-part-a':'fictional-full-payment','fictional-part-b':'fictional-partial-payment'};
          }
          state.installments=[plan,{id:'fictional-single',kind:'store',
            title:'Fictional single part purchase',provider:'Fictional provider',
            amount:17.49,accountingMode:'payments',parts:[{id:'fictional-only-part',
            date:'2026-11-27',amount:17.49,futurePartField:{keep:'only'}}],links:{},
            created_at:'2026-10-30T12:00:00Z',updated_at:'2026-10-30T12:00:00Z',
            futurePlanField:{keep:['single']}}];
          window.__installmentOriginal=JSON.parse(JSON.stringify({entries:state.entries,plans:state.installments}));
          showApp();renderAll();go('loans');
        }""", linked)
        if scale != 1:
            # Snapshot sizes before writing to avoid inherited multiplication.
            self.page.evaluate("""scale=>{
              const nodes=[...document.querySelectorAll('body,body *')]
                .filter(el=>!['SCRIPT','STYLE','SVG','PATH'].includes(el.tagName));
              const sizes=nodes.map(el=>parseFloat(getComputedStyle(el).fontSize));
              nodes.forEach((el,n)=>{if(sizes[n])el.style.setProperty('font-size',sizes[n]*scale+'px','important')});
            }""", scale)

    def expand(self, index=0):
        details = self.page.locator('#v77InstallmentList .v77-installment-details').nth(index)
        if not details.evaluate('(el)=>el.open'):
            details.locator(':scope > summary').click()
        self.assertTrue(details.evaluate('(el)=>el.open'))
        return details

    def assert_row_structure_and_layout(self):
        structure = self.page.evaluate("""()=>[...document.querySelectorAll('#v77InstallmentList .v77-part-list')].map(list=>({
          direct:[...list.children].filter(el=>el.matches('.v77-part')).length,
          total:list.querySelectorAll('.v77-part').length,
          nested:list.querySelectorAll('.v77-part .v77-part').length,
          ancestorCounts:[...list.querySelectorAll('.v77-part')].map(el=>{
            let count=0;for(let p=el.parentElement;p&&p!==list;p=p.parentElement)if(p.matches('.v77-part'))count++;return count;
          })
        }))""")
        self.assertEqual(structure, [
            {'direct': 4, 'total': 4, 'nested': 0, 'ancestorCounts': [0, 0, 0, 0]},
            {'direct': 1, 'total': 1, 'nested': 0, 'ancestorCounts': [0]},
        ])
        layout = self.page.evaluate(r"""()=>[...document.querySelectorAll('#v77InstallmentList .v77-part')].map(el=>{
          const box=el.getBoundingClientRect(),listBox=el.parentElement.getBoundingClientRect(),style=getComputedStyle(el),content=el.firstElementChild,
            contentBox=content.getBoundingClientRect(),actions=el.querySelector(':scope > .v77-part-actions'),
            actionBox=actions.getBoundingClientRect(),amount=content.querySelector('strong'),
            inner=el.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight),words=[];
          const walker=document.createTreeWalker(content,NodeFilter.SHOW_TEXT);
          while(walker.nextNode()){
            const node=walker.currentNode;
            for(const match of node.textContent.matchAll(/\S+/g)){
              const range=document.createRange();range.setStart(node,match.index);range.setEnd(node,match.index+match[0].length);
              const rects=[...range.getClientRects()].filter(r=>r.width&&r.height);
              words.push({text:match[0],lines:new Set(rects.map(r=>Math.round(r.top))).size,
                overflow:rects.some(r=>r.left<contentBox.left-1||r.right>contentBox.right+1)});
            }
          }
          return {width:box.width,overflow:el.scrollWidth-el.clientWidth,words,
            listOverflow:Math.max(0,listBox.left-box.left,box.right-listBox.right),
            contentWidth:contentBox.width,minimumContentWidth:Math.min(inner,Math.max(160,parseFloat(getComputedStyle(amount).fontSize)*8)),
            contentActionOverlap:Math.max(0,Math.min(contentBox.right,actionBox.right)-Math.max(contentBox.left,actionBox.left))*
              Math.max(0,Math.min(contentBox.bottom,actionBox.bottom)-Math.max(contentBox.top,actionBox.top)),
            buttons:[...el.querySelectorAll('button')].map(button=>{
              const rect=button.getBoundingClientRect(),style=getComputedStyle(button);
              return {text:button.textContent.trim(),width:rect.width,height:rect.height,
                font:parseFloat(style.fontSize),right:rect.right-box.right,left:box.left-rect.left};
            })};
        })""")
        self.assertEqual(len(layout), 5)
        self.assertLess(max(row['width'] for row in layout[:4]) - min(row['width'] for row in layout[:4]), 1)
        for row in layout:
            self.assertLessEqual(row['overflow'], 1, row)
            self.assertLessEqual(row['listOverflow'], 1, row)
            self.assertGreaterEqual(row['contentWidth'] + 1, row['minimumContentWidth'], row)
            self.assertLessEqual(row['contentActionOverlap'], 1, row)
            for word in row['words']:
                self.assertEqual(word['lines'], 1, word)
                self.assertFalse(word['overflow'], word)
            for button in row['buttons']:
                self.assertLessEqual(button['right'], 1, button)
                self.assertLessEqual(button['left'], 1, button)
                # A word must fit horizontally; the old nested rows became one-letter columns.
                self.assertGreater(button['width'], button['font'] * 3, button)

    def test_one_and_many_parts_are_siblings_and_expand_render_cancel_do_not_write(self):
        for width in self.WIDTHS:
            for scale in (1, 2):
                with self.subTest(width=width, text_scale=scale):
                    self.prepare(width, scale)
                    before = self.snapshot()
                    serial = self.page.evaluate('mutationSerial')
                    self.expand()
                    self.expand(1)
                    self.assert_row_structure_and_layout()
                    self.assertEqual(self.snapshot(), before)
                    self.page.evaluate('renderInstallments()')
                    self.expand()
                    self.expand(1)
                    self.assertEqual(self.snapshot(), before)
                    self.page.evaluate('window.confirm=()=>false')
                    self.page.locator('[data-v77-pay="fictional-plan"][data-v77-part="fictional-part-c"]').click()
                    self.page.locator('[data-v77-delete="fictional-plan"]').click()
                    self.assertEqual(self.snapshot(), before)
                    self.assertEqual(self.page.evaluate('mutationSerial'), serial)

    def test_date_save_changes_exactly_the_clicked_part_and_preserves_saved_fields(self):
        for width in self.WIDTHS:
            for scale in (1, 2):
                with self.subTest(width=width, text_scale=scale):
                    self.prepare(width, scale)
                    self.expand()
                    serial = self.page.evaluate('mutationSerial')
                    target = '[data-v77-part="fictional-part-c"]'
                    self.page.locator('input[data-v77-date="fictional-plan"]' + target).fill('2026-12-13')
                    self.page.locator('button[data-v77-save-date="fictional-plan"]' + target).click()
                    result = self.page.evaluate("""()=>({plans:state.installments,
                      entries:state.entries,original:window.__installmentOriginal,serial:mutationSerial,
                      pending:JSON.parse(localStorage.getItem(KEYS.pending))})""")
                    expected = result['original']['plans']
                    expected[0]['parts'][2]['date'] = '2026-12-13'
                    expected[0]['updated_at'] = result['plans'][0]['updated_at']
                    self.assertEqual(result['plans'], expected)
                    self.assertEqual(result['entries'], result['original']['entries'])
                    self.assertEqual(result['serial'], serial + 1)
                    self.assertEqual(result['pending']['installments'], expected)
                    self.expand()
                    self.assertEqual(self.page.locator('input[data-v77-date="fictional-plan"]' + target).input_value(), '2026-12-13')

    def test_matching_existing_payment_partial_status_and_history_keep_correct_references(self):
        for width in self.WIDTHS:
            for scale in (1, 2):
                with self.subTest(width=width, text_scale=scale):
                    self.prepare(width, scale, linked=True)
                    details = self.expand()
                    self.expand(1)
                    self.assert_row_structure_and_layout()
                    rows = details.locator(':scope > .v77-part-list > .v77-part')
                    self.assertEqual(rows.count(), 4)
                    self.assertIn('paid', rows.nth(0).get_attribute('class').split())
                    self.assertNotIn('paid', rows.nth(1).get_attribute('class').split())
                    self.assertIn('Частично: 40,00', rows.nth(1).inner_text())
                    self.assertIn('остаток 60,25', rows.nth(1).inner_text())
                    self.assertEqual(rows.nth(1).locator('[data-v77-op="history"]').count(), 1)
                    self.assertEqual(rows.nth(1).locator('[data-v77-pay],input[data-v77-date]').count(), 0)
                    before = self.snapshot()
                    serial = self.page.evaluate('mutationSerial')
                    self.page.locator('[data-v77-match="fictional-plan"][data-v77-part="fictional-part-c"]').click()
                    self.assertEqual(self.snapshot(), before)
                    matches = self.page.locator('#v77Matches_fictional-part-c')
                    self.assertTrue(matches.is_visible())
                    if scale != 1:
                        # Match buttons are rendered after the initial text-preference snapshot.
                        matches.evaluate("""(box,scale)=>{
                          const nodes=[...box.querySelectorAll('*')],sizes=nodes.map(el=>parseFloat(getComputedStyle(el).fontSize));
                          nodes.forEach((el,n)=>{if(sizes[n])el.style.setProperty('font-size',sizes[n]*scale+'px','important')});
                        }""", scale)
                    self.assertTrue(matches.evaluate("""box=>{
                      const parent=box.parentElement.getBoundingClientRect(),rect=box.getBoundingClientRect();
                      return rect.left>=parent.left&&rect.right<=parent.right&&box.scrollWidth<=box.clientWidth+1&&
                        [...box.querySelectorAll('button')].every(button=>{
                          const r=button.getBoundingClientRect();return r.left>=rect.left&&r.right<=rect.right+1;
                        });
                    }"""))
                    self.page.locator('[data-v77-link="fictional-plan"][data-v77-part="fictional-part-c"][data-v77-entry="fictional-free-payment"]').click()
                    result = self.page.evaluate("""()=>({plans:state.installments,entries:state.entries,
                      original:window.__installmentOriginal,serial:mutationSerial,
                      allocations:state.installments[0].parts.map(p=>installmentAllocated(state.installments[0],p)),
                      upcoming:installmentUpcoming()})""")
                    expected = result['original']['plans']
                    expected[0]['links']['fictional-part-c'] = 'fictional-free-payment'
                    expected[0]['updated_at'] = result['plans'][0]['updated_at']
                    self.assertEqual(result['plans'], expected)
                    self.assertEqual(result['entries'], result['original']['entries'])
                    self.assertEqual(result['allocations'], [100.25, 40, 100.25, 0])
                    self.assertEqual(result['serial'], serial + 1)
                    remaining = {p['partId']: p['amount'] for p in result['upcoming']}
                    self.assertEqual(remaining, {'fictional-part-b': 60.25, 'fictional-part-d': 100.25, 'fictional-only-part': 17.49})
                    rows = self.expand().locator(':scope > .v77-part-list > .v77-part')
                    self.assertIn('paid', rows.nth(2).get_attribute('class').split())
                    saved = self.snapshot()
                    rows.nth(1).locator('[data-v77-op="history"]').click()
                    self.assertTrue(self.page.locator('#history').is_visible())
                    self.assertEqual(self.snapshot(), saved)
                    self.assertEqual(self.page.evaluate("state.installments[0].links['fictional-part-b']"), 'fictional-partial-payment')
                    self.assertEqual(self.page.evaluate("state.entries.find(e=>e.id==='fictional-partial-payment').amount"), 40)
                    partial_row = self.page.locator('#historyBody button[data-action="edit"][data-id="fictional-partial-payment"]').locator('xpath=ancestor::tr')
                    self.assertEqual(partial_row.count(), 1)
                    self.assertIn('Fictional payment', partial_row.inner_text())
                    self.assertRegex(partial_row.locator('.v76-amount').inner_text().strip(), r'^−40(?:,00)?\s*₽$')


if __name__ == '__main__':
    unittest.main()
