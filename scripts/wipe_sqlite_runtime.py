import sqlite3

db = "ai_news.db"
conn = sqlite3.connect(db)
cur = conn.cursor()

for table in ["feed_feature_log", "interactions", "user_feed", "ai_news", "raw_news", "users"]:
    try:
        cur.execute(f"DELETE FROM {table}")
        print(f"cleared: {table}")
    except Exception as e:
        print(f"skip {table}: {e}")

try:
    cur.execute("DELETE FROM sqlite_sequence")
    print("cleared: sqlite_sequence")
except Exception as e:
    print(f"skip sqlite_sequence: {e}")

conn.commit()
conn.close()
print("done")
