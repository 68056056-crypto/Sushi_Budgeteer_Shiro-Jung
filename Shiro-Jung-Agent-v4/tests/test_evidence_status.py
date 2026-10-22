"""Team review remains unconfirmed; evidence metadata is required on import."""
import csv
from pathlib import Path
import sqlite3
import unittest
import test_system as fixtures
from sushi_budgeteer.database import ROOT, import_csv, records
from sushi_budgeteer.service import MenuService


class EvidenceStatusTest(unittest.TestCase):
    setUp=fixtures.CatalogTest.setUp
    tearDown=fixtures.CatalogTest.tearDown

    def source(self,**updates):
        with (ROOT/'sushiro_menu_dataset.csv').open(encoding='utf-8-sig') as stream:
            rows=list(csv.DictReader(stream))
        rows[0].update(updates)
        keys=list(dict.fromkeys([*rows[0],*(key for row in rows for key in row)]))
        path=Path(self.tmp.name)/'evidence.csv'
        with path.open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=keys);writer.writeheader();writer.writerows(rows)
        return path

    def test_team_review_requires_reason_reviewer_and_date(self):
        for missing in ('allergen_review_reason','allergen_reviewed_by','checked_at'):
            fields=dict(allergen_status='team_reviewed',allergen_review_reason='Dataset tags inspected; restaurant reply not received',
                        allergen_reviewed_by='Test fixture only',checked_at='2026-10-22')
            fields[missing]=''
            with self.subTest(missing=missing),self.assertRaisesRegex(ValueError,'team_reviewed'):
                import_csv(self.source(**fields))
        self.assertEqual(len(records()),42)

    def test_team_review_does_not_unlock_strict_allergy_recommendations(self):
        import_csv(self.source(allergen_status='team_reviewed',allergen_review_reason='Dataset review, no restaurant confirmation',
                               allergen_reviewed_by='Test fixture only',checked_at='2026-10-22'))
        self.assertEqual(records()[0]['allergen_status'],'team_reviewed')
        self.assertEqual(MenuService().build(budget=300,allergens=['milk'])['status'],'requires_clarification')

    def test_confirmed_price_requires_source_evidence_and_date(self):
        for missing in ('source_url','checked_at'):
            fields=dict(price_status='confirmed',source_url='https://example.org/fixture-price-sign',checked_at='2026-10-22')
            fields[missing]=''
            with self.subTest(missing=missing),self.assertRaisesRegex(ValueError,'confirmed price'):
                import_csv(self.source(**fields))

    def test_existing_catalog_migration_adds_review_fields_without_confirming(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute('ALTER TABLE menu DROP COLUMN allergen_review_reason')
            conn.execute('ALTER TABLE menu DROP COLUMN allergen_reviewed_by')
        rows=records()
        self.assertEqual(len(rows),42)
        self.assertTrue(all(row['allergen_status']=='unknown' and row['price_status']=='unverified' for row in rows))
        self.assertTrue(all(row['allergen_review_reason']=='' for row in rows))
