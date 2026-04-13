import sqlite3

conn = sqlite3.connect('ai_news.db')
cur = conn.cursor()
cur.execute("PRAGMA table_info(ai_news)")
cols = {row[1] for row in cur.fetchall()}

if 'region' not in cols:
    cur.execute("ALTER TABLE ai_news ADD COLUMN region TEXT")
    print('added region')
else:
    print('region already exists')

conn.commit()
conn.close()
print('ok')
