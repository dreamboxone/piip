# -*- coding: utf-8 -*-
"""SQLite content cache for large Xtream/Stalker catalogues."""

import hashlib
import json
import os
import sqlite3

ROOT = '/etc/enigma2/piip_db'


def path(identity, mode='content'):
    raw = ('%s|%s' % (identity, mode)).encode('utf-8')
    return os.path.join(ROOT, hashlib.md5(raw).hexdigest() + '.db')


def connect(identity, mode='content'):
    if not os.path.isdir(ROOT):
        os.makedirs(ROOT)
    db = sqlite3.connect(path(identity, mode))
    db.execute('CREATE TABLE IF NOT EXISTS categories (id TEXT PRIMARY KEY, name TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS streams (id TEXT PRIMARY KEY, category TEXT, payload TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS streams_category ON streams(category)')
    db.commit()
    return db


def sync_categories(db, categories):
    db.execute('DELETE FROM categories')
    db.executemany('INSERT OR REPLACE INTO categories(id,name) VALUES (?,?)',
                   [(str(key), name) for key, name in categories])
    db.commit()


def sync_streams(db, streams):
    db.execute('DELETE FROM streams')
    rows = []
    for item in streams:
        payload = dict((slot, getattr(item, slot)) for slot in item.__slots__)
        rows.append((item.item_id or item.url, item.group,
                     json.dumps(payload, ensure_ascii=False)))
    db.executemany('INSERT OR REPLACE INTO streams(id,category,payload) VALUES (?,?,?)', rows)
    db.commit()


def categories(db):
    return list(db.execute('SELECT id,name FROM categories ORDER BY name'))


def streams(db, category=None, offset=0, limit=50):
    if category is None:
        cur = db.execute('SELECT payload FROM streams ORDER BY id LIMIT ? OFFSET ?',
                         (int(limit), int(offset)))
    else:
        cur = db.execute('SELECT payload FROM streams WHERE category=? ORDER BY id LIMIT ? OFFSET ?',
                         (category, int(limit), int(offset)))
    return [json.loads(row[0]) for row in cur]
