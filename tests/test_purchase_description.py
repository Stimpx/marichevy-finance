"""Search text versus purchase notes in the actual form; synthetic browser only."""
import argparse
from pathlib import Path
import unittest

import test_local_data_safety as harness


class PurchaseDescription(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open

    def prepare(self):
        self.open()
        self.page.evaluate("""() => {
            session=null;state=blankState();localStorage.clear();showApp();
            clearEntry();openEntry('expense');
        }""")

    def save(self, amount='22,35'):
        self.page.locator('#eAmount').fill(amount)
        self.page.locator('#v90Save').click()
        self.page.wait_for_function('state.entries.length===1&&!v90Saving')
        return self.page.evaluate('state.entries[0]')

    def test_category_fragment_and_chosen_detail_do_not_become_saved_comments(self):
        for query,category,detail,label in (
            ('од','Одежда','',''),
            ('корм','Животные','Корм','Корм питомцу'),
        ):
            with self.subTest(query=query):
                self.prepare()
                self.page.locator('#v90Search').fill(query)
                if label:
                    self.page.locator('#v90Quick').get_by_role('button',name=label,exact=True).click()
                else:
                    self.page.locator('#v90Quick button[data-cat="'+category+'"]').click()
                self.assertEqual(self.page.locator('#eComment').input_value(),'')
                row=self.save()
                self.assertEqual(row['category'],category)
                self.assertEqual(row['subcategory'],detail)
                self.assertEqual(row['comment'],'')
                self.assertEqual(row['amount'],22.35)

    def test_meaningful_purchase_description_survives_category_rechoice_exactly_once(self):
        self.prepare()
        self.page.locator('#v90Search').fill('молоко без лактозы')
        self.page.locator('#v90Quick button[data-cat="Продукты"]').click()
        self.assertEqual(self.page.locator('#eComment').input_value(),'молоко без лактозы')
        # Reviewing the selected category must not erase or append to the purchase text.
        self.page.locator('#v90Quick button[data-cat="Продукты"]').click()
        self.assertEqual(self.page.locator('#eComment').input_value(),'молоко без лактозы')
        row=self.save('17,45')
        self.assertEqual(row['comment'],'молоко без лактозы')
        self.assertEqual(row['category'],'Продукты')

    def test_manual_note_survives_quick_description_and_category_choices(self):
        self.prepare()
        note='Fictional explicit note: keep exactly two packs'
        self.page.locator('#v90Extra').evaluate('(node)=>{node.open=true}')
        self.page.locator('#eComment').fill(note)
        self.page.locator('#v90Quick').get_by_role('button',name='Чаевые',exact=True).click()
        self.assertEqual(self.page.locator('#eComment').input_value(),note)
        self.page.locator('#v90Search').fill('молоко без лактозы')
        self.page.locator('#v90Quick button[data-cat="Продукты"]').click()
        self.assertEqual(self.page.locator('#eComment').input_value(),note)
        self.page.locator('#v90Search').fill('од')
        self.page.locator('#v90Quick button[data-cat="Одежда"]').click()
        row=self.save('19,35')
        self.assertEqual(row['comment'],note)
        self.assertEqual(row['category'],'Одежда')

    def test_clear_form_does_not_carry_automatic_text_into_next_operation(self):
        self.prepare()
        self.page.locator('#v90Search').fill('молоко без лактозы')
        self.page.locator('#v90Quick button[data-cat="Продукты"]').click()
        self.assertEqual(self.page.locator('#eComment').input_value(),'молоко без лактозы')
        self.page.locator('#today').get_by_role('button',name='Очистить',exact=True).click()
        self.assertEqual(self.page.locator('#eComment').input_value(),'')
        self.assertEqual(self.page.locator('#v90Search').input_value(),'')
        self.assertEqual(self.page.evaluate('v92AutoDescription'),'')
        self.page.locator('#v90Search').fill('од')
        self.page.locator('#v90Quick button[data-cat="Одежда"]').click()
        row=self.save('9,45')
        self.assertEqual(row['comment'],'')
        self.assertEqual(row['category'],'Одежда')
        self.assertEqual(self.page.evaluate('v92AutoDescription'),'')


if __name__=='__main__':
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--html',type=Path)
    args,remaining=parser.parse_known_args()
    if args.html:
        harness.HTML=args.html.resolve()
    unittest.main(argv=[__file__,*remaining])
