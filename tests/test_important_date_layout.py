"""Fictional Important Dates alignment/reflow and non-mutating edit regression."""
import unittest
import test_responsive_editor_layout as layouts


class ImportantDateLayout(unittest.TestCase):
    setUpClass = classmethod(layouts.ResponsiveEditorLayout.setUpClass.__func__)
    tearDownClass = classmethod(layouts.ResponsiveEditorLayout.tearDownClass.__func__)
    page = layouts.ResponsiveEditorLayout.page

    def test_all_date_actions_share_frames_and_edit_column_with_labels_beside_names(self):
        for width, height in layouts.PROFILES:
            with self.subTest(width=width, height=height):
                page, context = self.page(width, height)
                before = page.evaluate('JSON.stringify(state)')
                page.evaluate("go('dates')")
                geometry = page.evaluate('''() => {
                  const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};
                  return [...document.querySelectorAll('#birthdayList .birthday-row')].map(row=>{
                    const badge=row.querySelector('.birthday-family-badge');
                    const actions=row.querySelector('.birthday-row-actions');
                    return {row:rect(row),edit:rect(row.querySelector('[data-record-action="birthday-edit"]')),
                      singleRow:getComputedStyle(row).gridTemplateRows.trim().split(/\\s+/).length===1,
                      badge:badge?{...rect(badge),besideName:!!badge.closest('.birthday-main'),insideActions:!!badge.closest('.birthday-row-actions')}:null,
                      buttons:[...actions.querySelectorAll('a.btn,button.btn')].map(button=>{
                        const style=getComputedStyle(button);
                        return {...rect(button),radius:style.borderRadius,border:style.borderTopWidth};
                      })};
                  });
                }''')
                self.assertGreaterEqual(len(geometry), 2)
                self.assertLessEqual(max(row['edit']['x'] for row in geometry) -
                    min(row['edit']['x'] for row in geometry), 1,
                    'family and contact edit actions must occupy the same column')
                for row in geometry:
                    if row['singleRow']:
                        self.assertLessEqual(abs((row['edit']['y'] + row['edit']['h']/2) -
                            (row['row']['y'] + row['row']['h']/2)), 1,
                            'desktop actions must sit in the vertical centre of the row')
                    if row['badge']:
                        self.assertTrue(row['badge']['besideName'])
                        self.assertFalse(row['badge']['insideActions'])
                    for item in row['buttons']:
                        self.assertGreaterEqual(item['h'], 44)
                        self.assertEqual(item['radius'], '10px')
                        self.assertEqual(item['border'], '1px')
                        self.assertGreaterEqual(item['x'], row['row']['x'])
                        self.assertLessEqual(item['right'], row['row']['right'])
                    self.assertLessEqual(max(item['h'] for item in row['buttons']) -
                        min(item['h'] for item in row['buttons']), 1)
                self.assertEqual(before, page.evaluate('JSON.stringify(state)'))
                context.close()

    def test_enlarged_labels_and_contact_actions_remain_reachable(self):
        for width, height, scale in ((320,740,2),(390,844,1.5),(820,1180,2),(1280,900,2)):
            with self.subTest(width=width, height=height, scale=scale):
                page, context = self.page(width, height)
                before = page.evaluate('JSON.stringify(state)')
                page.evaluate("go('dates')")
                layouts.enlarge_text(page, scale)
                self.assertLessEqual(page.evaluate('Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)'), width+1)
                labels = page.locator('#birthdayList .birthday-family-badge, #birthdayList button')
                for index in range(labels.count()):
                    label=labels.nth(index)
                    label.scroll_into_view_if_needed()
                    label.evaluate("el=>el.scrollIntoView({block:'center'})")
                    self.assertTrue(label.evaluate('''el=>{
                      const r=el.getBoundingClientRect(),s=getComputedStyle(el),canvas=document.createElement('canvas').getContext('2d');
                      canvas.font=s.font||`${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
                      canvas.letterSpacing=s.letterSpacing==='normal'?'0px':s.letterSpacing;
                      const available=el.clientWidth-parseFloat(s.paddingLeft)-parseFloat(s.paddingRight);
                      const maxWord=Math.max(...el.textContent.trim().split(/\\s+/).map(word=>canvas.measureText(word).width));
                      const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
                      return r.x>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight&&el.contains(hit)&&maxWord<=available+1;
                    }'''), 'date action must remain reachable with unbroken words')
                self.assertEqual(before, page.evaluate('JSON.stringify(state)'))
                # Opening the editor and cancelling must not rewrite family dates.
                page.locator('#birthdayList .birthday-row-family button').first.click()
                self.assertTrue(page.locator('#birthdayCancelBtn').is_visible())
                page.locator('#birthdayCancelBtn').click()
                self.assertEqual(before, page.evaluate('JSON.stringify(state)'))
                context.close()
