"""Real geometry for expanded analytic rows and readable open help topics.

Sanitized fictional data only. A narrow viewport is a responsive approximation,
not evidence from a native phone. These assertions cover composition inside the
dialog/reading surface, which document-overflow checks alone cannot detect.
"""
import json
import os
from pathlib import Path
import unittest

import test_responsive_editor_layout as layouts


class DrillHelpLayout(unittest.TestCase):
    setUpClass = classmethod(layouts.ResponsiveEditorLayout.setUpClass.__func__)
    tearDownClass = classmethod(layouts.ResponsiveEditorLayout.tearDownClass.__func__)
    page = layouts.ResponsiveEditorLayout.page

    def test_drill_rows_keep_amount_with_content_and_actions_together(self):
        for width, height in layouts.PROFILES:
            for person in ('Алексей', 'София'):
                with self.subTest(width=width, height=height, person=person):
                    page, context = self.page(width, height)
                    before = page.evaluate('JSON.stringify(state)')
                    page.evaluate("go('analytics')")
                    page.evaluate('(name)=>v84Drill("person",name)', person)
                    rows = page.evaluate('''() => {
                      const rect=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};
                      const modal=document.querySelector('#v84DrillModal .v84-modal');
                      return [...document.querySelectorAll('#v84DrillEntries .v85-drill-entry')].map(row=>({
                        modal:rect(modal),row:rect(row),date:rect(row.querySelector('.v85-drill-date')),
                        name:rect(row.querySelector('.v85-drill-name')),
                        amount:rect(row.querySelector('.v84-drill-sum')),
                        details:row.querySelector('.v85-drill-details')?
                          rect(row.querySelector('.v85-drill-details')):null,
                        buttons:[...row.querySelectorAll('.v96-drill-entry-actions button')].map(rect)}));
                    }''')
                    self.assertGreater(len(rows), 0)
                    self.records.append({'view': 'drill-row-alignment', 'width': width,
                        'height': height, 'rows': rows})
                    for row in rows:
                        self.assertEqual(len(row['buttons']), 2)
                        self.assertLessEqual(abs(row['buttons'][0]['y'] - row['buttons'][1]['y']), 2,
                            'edit and repeat must not create a tall right-side action column')
                        # Compact rows put date+amount above the title; wide rows
                        # align the amount with the title. Both avoid the old
                        # detached, vertically centred text/actions composition.
                        self.assertLessEqual(min(abs(row['amount']['y'] - row['name']['y']),
                            abs(row['amount']['y'] - row['date']['y'])), 10,
                            'amount must share the first text row baseline')
                        if width >= 1024:
                            # Equal top edges do not align a short amount with
                            # a taller touch target. Their visual centres must
                            # share the title line, with metadata underneath.
                            centre = lambda item: item['y'] + item['h'] / 2
                            for element in [row['date'], row['name'], *row['buttons']]:
                                self.assertLessEqual(abs(centre(element) - centre(row['amount'])), 2,
                                    'wide-row title, amount and action controls must share a visual centre')
                            if row['details']:
                                self.assertGreaterEqual(row['details']['y'],
                                    max(item['bottom'] for item in
                                        [row['date'], row['name'], row['amount'], *row['buttons']]),
                                    'metadata must sit below the aligned primary line')
                        for element in [row['date'], row['name'], row['amount'], *row['buttons']]:
                            self.assertGreaterEqual(element['x'], row['modal']['x'] - 1)
                            self.assertLessEqual(element['right'], row['modal']['right'] + 1)
                        for button in row['buttons']:
                            self.assertGreaterEqual(button['h'], 44)
                    self.assertEqual(before, page.evaluate('JSON.stringify(state)'))
                    context.close()

    def test_expanded_help_has_a_readable_measure_and_consistent_gutters(self):
        for width, height in layouts.PROFILES:
            with self.subTest(width=width, height=height):
                page, context = self.page(width, height)
                before = page.evaluate('JSON.stringify(state)')
                page.evaluate('''() => {
                  go('help');for(const id of ['help-start','help-operations','help-calculator','help-categories'])
                    document.getElementById(id).open=true;
                  document.querySelector('#help .v96-help-category').open=true;
                }''')
                geometry = page.evaluate('''() => {
                  const rect=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right}};
                  const context=document.createElement('canvas').getContext('2d');
                  const body=document.querySelector('#help-start > .v96-help-body');
                  const para=body.querySelector('p'),style=getComputedStyle(para);
                  context.font=style.font||`${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
                  const unit=context.measureText('0').width;
                  const blocks=[...document.querySelectorAll('#help details[open] > .v96-help-body > p,'+
                    '#help details[open] > .v96-help-body > ol,'+
                    '#help details[open] > .v96-help-body > ul,'+
                    '#help details[open] > .v96-help-body > dl')].filter(el=>el.getBoundingClientRect().height);
                  return {surface:rect(document.querySelector('#help')),
                    paragraph:rect(para),unit,heading:rect(document.querySelector('#help-start summary h3')),
                    blocks:blocks.map(el=>({rect:rect(el),parent:rect(el.parentElement)})),
                    doc:document.documentElement.scrollWidth};
                }''')
                self.records.append({'view': 'expanded-help-reading', 'width': width,
                    'height': height, **geometry})
                self.assertLessEqual(geometry['paragraph']['w'] / geometry['unit'], 94,
                    'help lines should have a readable character measure, not span a wide dashboard')
                self.assertLessEqual(abs(geometry['paragraph']['x'] - geometry['heading']['x']), 2,
                    'expanded paragraphs and topic heading must share a left gutter')
                self.assertLessEqual(geometry['doc'], width + 1)
                for block in geometry['blocks']:
                    self.assertGreaterEqual(block['rect']['x'], block['parent']['x'] - 1)
                    self.assertLessEqual(block['rect']['right'], block['parent']['right'] + 1)
                    self.assertGreaterEqual(block['rect']['x'], -1)
                    self.assertLessEqual(block['rect']['right'], width + 1)
                self.assertEqual(before, page.evaluate('JSON.stringify(state)'))
                context.close()

    def test_enlarged_drill_buttons_keep_whole_labels_and_remain_reachable(self):
        for width, height, scale in ((320, 740, 2), (390, 844, 1.5), (820, 600, 2), (1280, 800, 1.5)):
            with self.subTest(width=width, height=height, text=scale):
                page, context = self.page(width, height)
                page.evaluate("go('analytics')")
                page.evaluate("v84Drill('person','София')")
                layouts.enlarge_text(page, scale)
                self.assertLessEqual(page.evaluate('Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)'),
                    width + 1, 'enlarged underlying analytics must not widen the document')
                buttons = page.locator('#v84DrillEntries .v96-drill-entry-actions button')
                for index in range(buttons.count()):
                    button = buttons.nth(index)
                    button.scroll_into_view_if_needed()
                    self.assertTrue(button.evaluate('''el=>{
                      const r=el.getBoundingClientRect(),s=getComputedStyle(el);
                      const c=document.createElement('canvas').getContext('2d');
                      c.font=s.font||`${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
                      c.letterSpacing=s.letterSpacing==='normal'?'0px':s.letterSpacing;
                      const front=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
                      return r.x>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight&&el.contains(front)&&
                        c.measureText(el.textContent.trim()).width<=el.clientWidth-
                        parseFloat(s.paddingLeft)-parseFloat(s.paddingRight)+1;
                    }'''), 'analytic action must remain reachable with a whole readable label')
                context.close()
