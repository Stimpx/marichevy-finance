"""Fictional Important Dates alignment/reflow and non-mutating edit regression."""
import unittest
import test_responsive_editor_layout as layouts


class ImportantDateLayout(unittest.TestCase):
    setUpClass = classmethod(layouts.ResponsiveEditorLayout.setUpClass.__func__)
    tearDownClass = classmethod(layouts.ResponsiveEditorLayout.tearDownClass.__func__)
    page = layouts.ResponsiveEditorLayout.page

    def test_family_action_columns_are_independent_of_badge_text(self):
        for width, height in layouts.PROFILES:
            with self.subTest(width=width, height=height):
                page, context = self.page(width, height)
                before = page.evaluate('JSON.stringify(state)')
                page.evaluate("go('dates')")
                geometry = page.evaluate('''() => {
                  const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};
                  return [...document.querySelectorAll('#birthdayList .birthday-row-family')].map(row=>({
                    row:rect(row),edit:rect(row.querySelector('button')),badge:rect(row.querySelector('.birthday-family-badge'))}));
                }''')
                self.assertGreaterEqual(len(geometry), 2)
                for kind in ('edit', 'badge'):
                    self.assertLessEqual(max(row[kind]['x'] for row in geometry) -
                        min(row[kind]['x'] for row in geometry), 1, 'label length must not shift action columns')
                for row in geometry:
                    self.assertLessEqual(abs((row['edit']['y'] + row['edit']['h']/2) -
                        (row['badge']['y'] + row['badge']['h']/2)), 1)
                    self.assertGreaterEqual(row['edit']['h'], 44)
                    for item in (row['edit'], row['badge']):
                        self.assertGreaterEqual(item['x'], row['row']['x'])
                        self.assertLessEqual(item['right'], row['row']['right'])
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
