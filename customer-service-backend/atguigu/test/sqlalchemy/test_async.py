from __future__ import annotations

import asyncio
import datetime

from sqlalchemy import ForeignKey, func, select
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload


class Base(AsyncAttrs, DeclarativeBase):
    pass


class B(Base):
    __tablename__ = "b"

    id: Mapped[int] = mapped_column(primary_key=True)
    a_id: Mapped[int] = mapped_column(ForeignKey("a.id"))
    data: Mapped[str]


class A(Base):
    __tablename__ = "a"

    id: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[str]
    create_date: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    bs: Mapped[list[B]] = relationship()


async def insert_objects(async_session: async_sessionmaker[AsyncSession]) -> None:

    # 创建session 对象
    async with async_session() as session, session.begin():
        session.add_all(
            [
                A(bs=[B(data="b1"), B(data="b2")], data="a1"),
                A(bs=[], data="a2"),
                A(bs=[B(data="b3"), B(data="b4")], data="a3"),
            ]
        )


async def select_and_update_objects(
    async_session: async_sessionmaker[AsyncSession],
) -> None:
    async with async_session() as session:
        stmt = select(A).order_by(A.id).options(selectinload(A.bs))
        result = await session.execute(stmt)
        for a in result.scalars():
            print(a, a.data)
            print(f"created at: {a.create_date}")
            for b in a.bs:
                print(b, b.data)
        result = await session.execute(select(A).order_by(A.id).limit(1))
        a1 = result.scalars().one()
        a1.data = "new data"
        await session.commit()
        # access attribute subsequent to commit; this is what
        # expire_on_commit=False allows
        print(a1.data)
        # alternatively, AsyncAttrs may be used to access any attribute
        # as an awaitable (new in 2.0.13)
        for b1 in await a1.awaitable_attrs.bs:
            print(b1, b1.data)


async def async_main() -> None:

    # 1. 创建异步引擎对象
    engine = create_async_engine("sqlite+aiosqlite:///async_mydb", echo=True)

    # 2. 创建异步 session 工厂
    # async_sessionmaker: a factory for new AsyncSession objects.
    # expire_on_commit - don't expire objects after transaction commit
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    # 3. 异步连接数据库并根据实体类的定义自动创建表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 4. 批量插入
    await insert_objects(async_session)
    # await select_and_update_objects(async_session)
    # for AsyncEngine created in function scope, close and
    # clean-up pooled connections

    # 5. 释放资源
    await engine.dispose()


asyncio.run(async_main())
