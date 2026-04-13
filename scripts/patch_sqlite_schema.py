import sqlite3

conn = sqlite3.connect('ai_news.db')
cur = conn.cursor()

# Ensure ai_news exists
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ai_news'")
if not cur.fetchone():
    print('ai_news table is missing')
else:
    cur.execute("PRAGMA table_info(ai_news)")
    cols = {row[1]: row[2] for row in cur.fetchall()}
    print('existing columns:', sorted(cols.keys()))

    if 'raw_text' not in cols:
        cur.execute("ALTER TABLE ai_news ADD COLUMN raw_text TEXT")
        print('added column: raw_text')

conn.commit()
conn.close()
print('schema patch done')
