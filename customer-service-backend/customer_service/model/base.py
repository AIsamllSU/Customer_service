# customer_service/model/base.py

"""
ORM 基类：所有表模型都继承它，SQLAlchemy 才能统一管理它们的元数据。
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
