"""Ten regulatory groups are a mapping registry, never fabricated recipe evidence."""
import csv
import io
import sqlite3
import unittest
from pathlib import Path
import test_system as fixtures
from sushi_budgeteer.database import ROOT, records, import_csv
from sushi_budgeteer.regulatory_allergens import THAI_ALLERGEN_GROUPS, mapped_fields
from sushi_budgeteer.state import KNOWN_ALLERGENS
from sushi_budgeteer.service import MenuService


class ThaiAllergenTest(unittest.TestCase):
    setUp=fixtures.CatalogTest.setUp
    tearDown=fixtures.CatalogTest.tearDown

    def test_exactly_ten_groups_separate_from_additional_constraints(self):
        self.assertEqual(set(THAI_ALLERGEN_GROUPS),{'gluten','crustacean','egg','fish','peanut','soy','milk','tree_nuts','sulphites','molluscs'})
        self.assertTrue(set(THAI_ALLERGEN_GROUPS)<=KNOWN_ALLERGENS)
        self.assertFalse({'sesame','pork','seafood','echinoderm'} & set(THAI_ALLERGEN_GROUPS))
        self.assertIn('10',THAI_ALLERGEN_GROUPS['sulphites'])

    def test_every_menu_has_all_ten_columns_without_claiming_absence(self):
        for row in records():
            for tag in THAI_ALLERGEN_GROUPS:
                expected='possible' if tag in row['allergen_tags'].split(';') else 'unknown'
                self.assertEqual(row['thai_allergen_'+tag],expected)
            self.assertEqual(row['allergen_status'],'unknown')
            self.assertEqual(row['allergen_source_url'],'')

    def test_name_only_recommendation_cannot_remove_sauce_allergens(self):
        rows={row['item_id']:row for row in records()}
        eel=rows['S003']
        self.assertEqual(eel['recommended_thai_allergen_10_unverified'],'ปลาและผลิตภัณฑ์')
        self.assertEqual(eel['thai_allergen_soy'],'possible')
        self.assertEqual(eel['thai_allergen_gluten'],'possible')
        self.assertEqual(rows['D002']['thai_allergen_soy'],'possible')

    def test_supplied_audit_adds_possible_milk_and_fish_without_confirmation(self):
        rows={row['item_id']:row for row in records()}
        self.assertEqual(rows['S014']['thai_allergen_milk'],'possible')
        self.assertEqual(rows['S014']['thai_allergen_soy'],'possible')
        self.assertEqual(rows['R001']['thai_allergen_fish'],'possible')
        self.assertIn('ไม่ลบ soy',rows['S014']['mapping_audit_note'])
        self.assertTrue(all(row['allergen_status']=='unknown' for row in rows.values()))

    def test_uni_outside_ten_does_not_mean_allergen_free(self):
        row=next(row for row in records() if row['item_id']=='S007')
        self.assertEqual(row['thai_allergen_molluscs'],'unknown')
        self.assertIn('echinoderm',row['allergen_tags'])
        self.assertIn('ไม่ใช่การยืนยันว่าไม่มี',row['thai_allergen_10_unverified'])

    def test_import_recomputes_flags_instead_of_accepting_absence_claim(self):
        row=records()[0]
        row['thai_allergen_fish']='confirmed_absent'
        path=Path(self.tmp.name)/'altered.csv'
        with path.open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(row));writer.writeheader();writer.writerow(row)
        import_csv(path)
        self.assertEqual(records()[0]['thai_allergen_fish'],'possible')
        self.assertEqual(records()[0]['allergen_status'],'unknown')

    def test_strict_blocks_all_ten_groups_with_unknown_recipe_evidence(self):
        for tag in THAI_ALLERGEN_GROUPS:
            self.assertEqual(MenuService().build(budget=300,allergens=[tag])['status'],'requires_clarification',tag)

    def test_existing_database_gains_mapping_without_losing_prices(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE menu SET price_baht=77.25,allergen_tags='fish;soy' WHERE item_id='S014'")
            conn.execute('ALTER TABLE menu DROP COLUMN thai_allergen_milk')
        row=next(row for row in records() if row['item_id']=='S014')
        self.assertEqual(row['price_baht'],77.25)
        self.assertEqual(row['thai_allergen_milk'],'possible')
        self.assertEqual(row['thai_allergen_soy'],'possible')


if __name__=='__main__':
    unittest.main()
