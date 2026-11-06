import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from customer_service.conf.config import settings

logger = logging.getLogger(__name__)

engine: AsyncEngine | None = None
async_session: async_sessionmaker[AsyncSession] | None = None


# 初始化数据库链接资源
def init_db_engine() -> None:
    # 1. 声明全局对象
    global engine, async_session
    # 2. 创建引擎对象（是否回显 SQL 由配置决定，生产默认关闭）
    engine = create_async_engine(
        settings.database_url,
        echo=settings.database_echo,
        pool_pre_ping=True,
    )
    # 3. 创建 session 工厂
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    logger.info("数据库连接池已初始化：echo=%s", settings.database_echo)


# 释放数据库链接资源
async def close_db_engine() -> None:
    global engine, async_session
    if engine is not None:
        await engine.dispose()
        logger.info("数据库连接池已释放")
    engine = None
    async_session = None


async def create_tables() -> None:
    """
    根据 ORM 模型创建表（表已存在则跳过）。

    这里显式导入 DialogueStateRecord，确保它的元数据已经注册到 Base.metadata，
    否则 create_all 找不到这张表。
    """
    import customer_service.model.dialogue_state  # noqa: F401
    from customer_service.model.base import Base

    if engine is None:
        raise RuntimeError("数据库引擎尚未初始化，请先调用 init_db_engine()")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("数据表检查完成")


if __name__ == "__main__":
    # print(settings.database_url)

    init_db_engine()

    async def test():

        async with async_session() as session:
            # result = await session.execute(select(1))
            result = await session.execute(text("select 1"))
            print(result.scalars().one())

        await close_db_engine()

    asyncio.run(test())
