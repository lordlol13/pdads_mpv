import asyncio
from app.backend.db.session import SessionLocal
from sqlalchemy import text

async def check():
    async with SessionLocal() as session:
        # Check ai_news count
        result = await session.execute(text('SELECT COUNT(*) FROM ai_news'))
        ai_count = result.scalar_one()
        
        # Check user_feed count  
        result = await session.execute(text('SELECT COUNT(*) FROM user_feed'))
        feed_count = result.scalar_one()
        
        # Check raw_news count
        result = await session.execute(text('SELECT COUNT(*) FROM raw_news'))
        raw_count = result.scalar_one()
        
        # Check user count
        result = await session.execute(text('SELECT COUNT(*) FROM users'))
        user_count = result.scalar_one()
        
        # Check ai_news sample
        result = await session.execute(text('SELECT id, final_title, ai_score, created_at FROM ai_news ORDER BY id DESC LIMIT 3'))
        ai_rows = result.mappings().all()
        
        # Check user_feed with join
        result = await session.execute(text('''
            SELECT uf.id, uf.user_id, uf.ai_news_id, an.final_title, an.ai_score
            FROM user_feed uf
            JOIN ai_news an ON an.id = uf.ai_news_id
            LIMIT 5
        '''))
        feed_rows = result.mappings().all()
        
        print('=== DATABASE STATUS ===')
        print(f'ai_news: {ai_count} records')
        print(f'user_feed: {feed_count} records')
        print(f'raw_news: {raw_count} records')
        print(f'users: {user_count} records')
        print()
        
        print('=== Last 3 ai_news ===')
        for row in ai_rows:
            title = row.final_title[:60] if row.final_title else 'N/A'
            print(f'ID {row.id}: {title}... (score: {row.ai_score})')
        
        print()
        print('=== user_feed with ai_news ===')
        for row in feed_rows:
            title = row.final_title[:50] if row.final_title else 'N/A'
            print(f'user_feed ID {row.id}: user={row.user_id}, ai_news={row.ai_news_id}, title={title}...')

if __name__ == '__main__':
    asyncio.run(check())
