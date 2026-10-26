"""Local help navigation, detailed coverage and side-effect safety; fictional state."""
import argparse
from pathlib import Path
import unittest

import test_local_data_safety as harness


TOPICS = (
    'help-start','help-operations','help-fields','help-calculator','help-quick-entry','help-categories',
    'help-history','help-analytics','help-category-review','help-car','help-loans','help-plans','help-goals',
    'help-family','help-sync','help-backup','help-privacy','help-feedback',
)


class HelpGuide(unittest.TestCase):
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
        self.page.evaluate("""() => {
            session=null;state=blankState();localStorage.clear();showApp();stopCloudSync();
            state.entries=[{id:'fictional-guide-entry',type:'expense',date:today(),amount:17.25,
                category:'Продукты',who:'Fictional historical owner',beneficiary:'Общее',
                store:'Fictional shop',comment:'Synthetic help fixture',futureField:{keep:true}}];
            renderAll();
        }""")

    def test_help_navigation_opens_guide_without_leaving_application(self):
        self.prepare()
        help_button=self.page.locator('#nav [data-page="help"]')
        self.assertEqual(help_button.count(),1)
        previous=self.page.url
        help_button.click()
        self.assertTrue(self.page.locator('#help').is_visible())
        self.assertEqual(self.page.locator('#v96HelpTitle').inner_text(),'Как пользоваться')
        self.assertEqual(self.page.evaluate('NAV.help[0]'),'Как пользоваться')
        self.assertEqual(self.page.url,previous)

    def test_all_topics_and_every_exact_category_have_detailed_explanations(self):
        self.prepare()
        self.assertEqual(self.page.locator('#help').count(),1)
        result=self.page.evaluate("""() => ({
            expected:CATS,current:V90_CATEGORIES.map(c=>c[0]),
            categories:[...document.querySelectorAll('#help [data-help-category]')].map(node=>({
                key:node.dataset.helpCategory,paragraphs:node.querySelectorAll('p').length,
                text:node.textContent.trim().length,summary:node.querySelector('summary')?.textContent.trim()
            })),
            topics:[...document.querySelectorAll('#help .v96-help-topic')].map(node=>({
                id:node.id,summary:node.querySelector('summary')?.textContent.trim(),
                text:node.querySelector('.v96-help-body')?.textContent.trim().length
            }))
        })""")
        self.assertCountEqual([c['key'] for c in result['categories']],result['expected'])
        self.assertTrue(set(result['current']).issubset(c['key'] for c in result['categories']))
        for category in result['categories']:
            self.assertGreaterEqual(category['paragraphs'],2,category['key'])
            self.assertGreater(category['text'],150,category['key'])
            self.assertTrue(category['summary'],category['key'])
        self.assertCountEqual([t['id'] for t in result['topics']],TOPICS)
        for topic in result['topics']:
            self.assertTrue(topic['summary'],topic['id'])
            self.assertGreater(topic['text'],150,topic['id'])

    def test_contents_links_resolve_and_guide_has_no_external_resources_or_actions(self):
        self.prepare()
        self.assertEqual(self.page.locator('#help').count(),1)
        result=self.page.evaluate("""() => {
            const guide=document.getElementById('help');
            return {links:[...guide.querySelectorAll('a')].map(a=>({href:a.getAttribute('href'),
                targetExists:!!guide.querySelector(a.getAttribute('href'))})),
                uniqueIds:[...guide.querySelectorAll('[id]')].every(n=>document.querySelectorAll('[id="'+n.id+'"]').length===1),
                forbidden:guide.querySelectorAll('script,iframe,object,embed,img,audio,video,link,form,input,select,textarea').length,
                eventAttributes:[...guide.querySelectorAll('*')].flatMap(n=>[...n.attributes].map(a=>a.name)).filter(n=>n.startsWith('on')),
                readingNotice:guide.textContent.includes('Чтение справки не создаёт операций')};
        }""")
        self.assertEqual(len(result['links']),len(TOPICS))
        self.assertTrue(all(link['href'].startswith('#help-') and link['targetExists'] for link in result['links']))
        self.assertTrue(result['uniqueIds'])
        self.assertEqual(result['forbidden'],0)
        self.assertEqual(result['eventAttributes'],[])
        self.assertTrue(result['readingNotice'])

    def test_reading_and_expanding_help_does_not_modify_state_or_request_network(self):
        self.prepare()
        self.assertEqual(self.page.locator('#help').count(),1)
        before=self.snapshot()
        requests=[]
        self.page.on('request',lambda request:requests.append(request.url))
        self.page.evaluate("""() => {
            window.__helpFetches=[];
            window.fetch=(...args)=>{window.__helpFetches.push(String(args[0]));return Promise.reject(Error('No network expected for help'))};
            go('help');document.querySelectorAll('#help details').forEach(n=>{n.open=true});
        }""")
        self.page.locator('#help .v96-help-toc a[href="#help-backup"]').click()
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.page.evaluate('window.__helpFetches'),[])
        self.assertEqual(requests,[])

    def test_expanded_help_fits_phone_and_desktop_widths(self):
        self.prepare()
        self.assertEqual(self.page.locator('#help').count(),1)
        for width in (1280,390,320):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width':width,'height':844})
                result=self.page.evaluate("""() => {
                    go('help');document.querySelectorAll('#help details').forEach(n=>{n.open=true});
                    return {overflow:document.documentElement.scrollWidth>innerWidth+1,
                        outside:[...document.querySelectorAll('#help summary,#help .v96-help-toc a')].some(n=>{
                            const r=n.getBoundingClientRect();return r.width<=0||r.left<0||r.right>innerWidth+1;
                        })};
                }""")
                self.assertEqual(result,{'overflow':False,'outside':False})


if __name__=='__main__':
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--html',type=Path)
    args,remaining=parser.parse_known_args()
    if args.html:
        harness.HTML=args.html.resolve()
    unittest.main(argv=[__file__,*remaining])
