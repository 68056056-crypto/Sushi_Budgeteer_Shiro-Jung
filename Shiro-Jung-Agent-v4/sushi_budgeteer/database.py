"""Validated CSV ingestion and SQLite catalog. Runtime reads SQLite, never a mock."""
from __future__ import annotations
import argparse
import csv
import io
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)
COLUMNS = ('item_id','name_th','name_en','category','plate_color','price_baht',
           'description_th','keywords','allergens_verified','source_url','price_status',
           'allergen_status','allergen_source_url','checked_at')
FDA_SOURCE = 'https://food.fda.moph.go.th/media.php?id=654869394207416320&name=P450.pdf'

def database_path() -> Path:
    return Path(os.getenv('SUSHI_DB_PATH', str(ROOT / 'data' / 'menu.sqlite3'))).resolve()

def cents(value) -> int:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal('.01')):
            raise ValueError('เงินต้องเป็นจำนวนไม่ติดลบและทศนิยมไม่เกิน 2 ตำแหน่ง')
        return int(amount * 100)
    except (InvalidOperation, TypeError) as e:
        raise ValueError('จำนวนเงินไม่ถูกต้อง') from e

def import_csv(source: str | Path, target: str | Path | None = None) -> dict:
    source = Path(source).resolve()
    raw = source.read_bytes()
    rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    if not rows or not {'item_id','name_th','category','price_baht','allergens_verified'} <= rows[0].keys():
        raise ValueError('CSV ไม่มีข้อมูลหรือขาดคอลัมน์ที่จำเป็น')
    seen, values = set(), []
    for row in rows:
        if not row['item_id'].strip() or row['item_id'] in seen or not row['name_th'].strip():
            raise ValueError('item_id ต้องไม่ซ้ำและชื่อเมนูต้องไม่ว่าง')
        seen.add(row['item_id'])
        row = {k: (row.get(k) or '').strip() for k in COLUMNS}
        row['price_baht'] = cents(row['price_baht']) / 100
        row['price_status'] = row['price_status'] or 'unverified'
        row['allergen_status'] = row['allergen_status'] or 'unknown'
        if row['price_status'] not in {'confirmed','unverified'} or row['allergen_status'] not in {'confirmed','unknown'}:
            raise ValueError('สถานะ provenance ไม่ถูกต้อง')
        if row['allergen_status'] == 'confirmed' and not (row['allergen_source_url'] and row['checked_at']):
            raise ValueError('confirmed allergen ต้องมีแหล่งข้อมูลรายเมนูและวันที่ตรวจ')
        if row['price_status'] == 'confirmed' and not row['checked_at']:
            raise ValueError('confirmed price ต้องมีวันที่ตรวจ')
        values.append(tuple(row[k] for k in COLUMNS))
    path = Path(target).resolve() if target else database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {'source_csv': source.name, 'source_sha256': hashlib.sha256(raw).hexdigest(),
                'imported_at': datetime.now(timezone.utc).isoformat(), 'row_count': len(rows),
                'allergen_policy_reference': FDA_SOURCE}
    with sqlite3.connect(path) as conn:
        # A transaction retains the last valid catalog if validation/import fails.
        definitions = ','.join(f'{k} '+('REAL NOT NULL' if k=='price_baht' else 'TEXT NOT NULL') for k in COLUMNS)
        conn.execute(f'CREATE TABLE IF NOT EXISTS menu ({definitions}, PRIMARY KEY(item_id))')
        conn.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        conn.execute("DELETE FROM metadata WHERE key='menu_reference'")
        conn.execute('DELETE FROM menu')
        conn.executemany(f'INSERT INTO menu VALUES ({",".join("?" for _ in COLUMNS)})', values)
        conn.executemany('INSERT OR REPLACE INTO metadata VALUES (?,?)', [(k,json.dumps(v,ensure_ascii=False)) for k,v in metadata.items()])
    return {**metadata, 'database': display_path(path)}

def display_path(path) -> str:
    """Project-relative path for reports/traces; avoids leaking machine-specific absolute paths."""
    path = Path(path).resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name

def ensure_database() -> Path:
    path = database_path()
    if not path.exists():
        import_csv(os.getenv('SUSHI_MENU_CSV_PATH', str(ROOT / 'sushiro_menu_dataset.csv')), path)
    return path

def records() -> list[dict]:
    path = ensure_database()
    with sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute('SELECT * FROM menu ORDER BY rowid')]

def catalog_revision(rows=None) -> str:
    return hashlib.sha256(json.dumps(records() if rows is None else rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def status() -> dict:
    rows = records()
    return {'row_count':len(rows),'catalog_revision':catalog_revision(rows),
            'database':display_path(database_path()),'unverified_prices':sum(r['price_status']!='confirmed' for r in rows),
            'unknown_allergens':sum(r['allergen_status']!='confirmed' for r in rows),
            'mode':os.getenv('SUSHI_DATA_MODE','strict')}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['import','status'])
    p.add_argument('--csv',default=str(ROOT/'sushiro_menu_dataset.csv'))
    p.add_argument('--db')
    args=p.parse_args()
    if args.db: os.environ['SUSHI_DB_PATH']=args.db
    print(json.dumps(import_csv(args.csv) if args.command=='import' else status(),ensure_ascii=False,indent=2))

if __name__=='__main__': main()
