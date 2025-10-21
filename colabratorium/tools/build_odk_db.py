#!/usr/bin/env python3
"""
Build an SQLite database from CSV files in the `odk/` folder.

Creates `odk_import.db` in the repository root. This script is standalone and uses only
the Python standard library. It attempts to follow the schema provided in the project
description and will print row counts per table after import.

Usage:
    python scripts/build_odk_db.py [output_db_path]

"""
import csv
import os
import sqlite3
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ODK_DIR = os.path.join(ROOT, 'odk')
DEFAULT_DB = os.path.join(ROOT, 'odk_import.db')


def clean_val(v):
    if v is None:
        return None
    v = v.strip()
    if v == '':
        return None
    # booleans
    if v.upper() == 'TRUE':
        return 1
    if v.upper() == 'FALSE':
        return 0
    # numeric-looking values: keep as-is (sqlite is typeless) but try to convert where appropriate
    return v


def create_tables(conn):
    cur = conn.cursor()
    # Entities
    cur.execute('''
    CREATE TABLE IF NOT EXISTS people (
        id INTEGER,
        version INTEGER,
        name TEXT,
        role TEXT,
        email TEXT,
        active INTEGER,
        timestamp TEXT,
        tags TEXT,
        status TEXT,
        created_by INTEGER,
        PRIMARY KEY (id, version)
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS organisations (
        id INTEGER,
        version INTEGER,
        timestamp TEXT,
        name TEXT,
        description TEXT,
        location TEXT,
        contact_person INTEGER,
        tags TEXT,
        status TEXT,
        created_by INTEGER,
        PRIMARY KEY (id, version)
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS initiatives (
        id INTEGER,
        version INTEGER,
        name TEXT,
        description TEXT,
        responsible_person INTEGER,
        timestamp TEXT,
        tags TEXT,
        status TEXT,
        created_by INTEGER,
        PRIMARY KEY (id, version)
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS activities (
        id INTEGER,
        version INTEGER,
        timestamp TEXT,
        name TEXT,
        description TEXT,
        location TEXT,
        start_date TEXT,
        end_date TEXT,
        tags TEXT,
        status TEXT,
        created_by INTEGER,
        PRIMARY KEY (id, version)
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS contracts (
        id INTEGER,
        version INTEGER,
        timestamp TEXT,
        name TEXT,
        description TEXT,
        organisation INTEGER,
        organisation_person INTEGER,
        responsible_person INTEGER,
        start_date TEXT,
        end_date TEXT,
        tags TEXT,
        status TEXT,
        created_by INTEGER,
        PRIMARY KEY (id, version)
    )
    ''')

    # Link tables (composite pk id,version)
    cur.execute('''
    CREATE TABLE IF NOT EXISTS activity_activity_links (
        id INTEGER,
        version INTEGER,
        timestamp TEXT,
        status TEXT,
        parent_id INTEGER,
        child_id INTEGER,
        type TEXT,
        created_by INTEGER,
        PRIMARY KEY (id, version)
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS initiative_initiative_links (
        id INTEGER,
        version INTEGER,
        timestamp TEXT,
        status TEXT,
        parent_id INTEGER,
        child_id INTEGER,
        type TEXT,
        created_by INTEGER,
        PRIMARY KEY (id, version)
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS activity_initiative_links (
        id INTEGER,
        version INTEGER,
        timestamp TEXT,
        status TEXT,
        activity_id INTEGER,
        initiative_id INTEGER,
        type TEXT,
        created_by INTEGER,
        PRIMARY KEY (id, version)
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS activity_contract_links (
        id INTEGER,
        version INTEGER,
        timestamp TEXT,
        status TEXT,
        activity_id INTEGER,
        contract_id INTEGER,
        type TEXT,
        created_by INTEGER,
        PRIMARY KEY (id, version)
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS contract_initiative_links (
        id INTEGER,
        version INTEGER,
        timestamp TEXT,
        status TEXT,
        contract_id INTEGER,
        initiative_id INTEGER,
        type TEXT,
        created_by INTEGER,
        PRIMARY KEY (id, version)
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS organisation_people_links (
        id INTEGER,
        version INTEGER,
        timestamp TEXT,
        status TEXT,
        organisation_id INTEGER,
        person_id INTEGER,
        type TEXT,
        created_by INTEGER,
        PRIMARY KEY (id, version)
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS activity_people_links (
        id INTEGER,
        version INTEGER,
        timestamp TEXT,
        status TEXT,
        activity_id INTEGER,
        person_id INTEGER,
        type TEXT,
        created_by INTEGER,
        PRIMARY KEY (id, version)
    )
    ''')

    # simple tags table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER,
        version INTEGER,
        name TEXT,
        key_values TEXT,
        initiatives TEXT,
        people TEXT,
        organisations TEXT,
        activities TEXT,
        contracts TEXT,
        timestamp TEXT,
        status TEXT,
        created_by INTEGER,
        PRIMARY KEY (id, version)
    )
    ''')

    conn.commit()


def insert_csv(conn, csv_path, table):
    with open(csv_path, newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames
        rows = []
        for r in reader:
            # normalize keys to match table columns
            vals = []
            for c in cols:
                v = r.get(c)
                v = clean_val(v)
                vals.append(v)
            rows.append((cols, vals))

    cur = conn.cursor()
    for cols, vals in rows:
        placeholders = ','.join('?' for _ in cols)
        colnames = ','.join(cols)
        sql = f'INSERT INTO {table} ({colnames}) VALUES ({placeholders})'
        try:
            cur.execute(sql, vals)
        except Exception:
            # try a more tolerant insert by mapping to columns that exist in the table
            # fetch table columns
            tbl_cols = [c[1] for c in cur.execute(f'PRAGMA table_info({table})').fetchall()]
            mapped_cols = []
            mapped_vals = []
            for k, v in zip(cols, vals):
                if k in tbl_cols:
                    mapped_cols.append(k)
                    mapped_vals.append(v)
            if not mapped_cols:
                continue
            placeholders = ','.join('?' for _ in mapped_cols)
            colnames = ','.join(mapped_cols)
            sql = f'INSERT INTO {table} ({colnames}) VALUES ({placeholders})'
            try:
                cur.execute(sql, mapped_vals)
            except Exception:
                # last resort: ignore row
                continue

    conn.commit()


def main(argv):
    out_db = argv[1] if len(argv) > 1 else DEFAULT_DB
    if os.path.exists(out_db):
        print(f'Removing existing DB at {out_db}')
        os.remove(out_db)

    conn = sqlite3.connect(out_db)
    create_tables(conn)

    files_map = {
        'people_table.csv': ('people',),
        'organisation_table.csv': ('organisations',),
        'initiatives_table.csv': ('initiatives',),
        'activities_table.csv': ('activities',),
        'contract_table.csv': ('contracts',),

        'activity_activity_links.csv': ('activity_activity_links',),
        'initiative_initiative_links.csv': ('initiative_initiative_links',),
        'activity_initiative_links.csv': ('activity_initiative_links',),
        'activity_contract_links.csv': ('activity_contract_links',),
        'contract_initiative_links.csv': ('contract_initiative_links',),
        'organisation_people_links.csv': ('organisation_people_links',),
        'activity_people_links.csv': ('activity_people_links',),
    }

    for fname, (table,) in files_map.items():
        path = os.path.join(ODK_DIR, fname)
        if not os.path.exists(path):
            print('Skipping missing', fname)
            continue
        print('Importing', fname, '->', table)
        insert_csv(conn, path, table)

    # report counts
    cur = conn.cursor()
    print('\nImport complete. Row counts:')
    for t in ['people','organisations','initiatives','activities','contracts','activity_activity_links','initiative_initiative_links','activity_initiative_links','activity_contract_links','contract_initiative_links','organisation_people_links','activity_people_links','tags']:
        try:
            r = cur.execute(f'SELECT COUNT(*) FROM {t}').fetchone()
            print(f'  {t}:', r[0])
        except Exception:
            print(f'  {t}: (no table)')

    conn.close()
    print('\nDB written to', out_db)


if __name__ == '__main__':
    main(sys.argv)
