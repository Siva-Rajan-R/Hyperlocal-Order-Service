from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from core.configs.settings_config import SETTINGS
from icecream import ic


ENGINE=create_async_engine(SETTINGS.PG_DATABASE_URL,echo=False)

BASE=declarative_base()


AsyncOrdersLocalSession=async_sessionmaker(ENGINE)

async def init_orders_pg_db():
    try:
        ic("initializing pg db...")
        async with ENGINE.connect() as conn:
            await conn.run_sync(BASE.metadata.create_all)
            await conn.commit()
        ic("...Databse initialized successfully...")
    except Exception as e:
        ic(f"Error : initializing pg db => {e}")


async def get_pg_async_session():
    Session=AsyncOrdersLocalSession()
    try:
        yield Session
    finally:
        await Session.close_all()