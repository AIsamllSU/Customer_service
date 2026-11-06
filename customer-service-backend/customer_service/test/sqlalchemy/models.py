from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    # 表名
    __tablename__ = "user_account"

    # 唯一标识
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30))

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, name={self.name!r})"


class Address(Base):
    # 表名
    __tablename__ = "address"

    # 唯一标识
    id: Mapped[int] = mapped_column(primary_key=True)
    email_address: Mapped[str]

    def __repr__(self) -> str:
        return f"Address(id={self.id!r}, email_address={self.email_address!r})"
