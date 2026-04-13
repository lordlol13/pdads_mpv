import sqlite3

conn = sqlite3.connect('ai_news.db')
cur = conn.cursor()
print('raw_news=', cur.execute('select count(*) from raw_news').fetchone()[0])
print('ai_news=', cur.execute('select count(*) from ai_news').fetchone()[0])
print('user_feed=', cur.execute('select count(*) from user_feed').fetchone()[0])
print('generated_raw=', cur.execute("select count(*) from raw_news where process_status='generated'").fetchone()[0])
conn.close()
