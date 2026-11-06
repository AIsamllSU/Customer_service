from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from atguigu.test.sqlalchemy.models import User


def main():

    # 1. 创建引擎对象
    # sqlite:// 轻量数据库访问协议
    # sqlite:/// 在当前目录
    # sqlite://// 在磁盘的根目录
    # echo=True： 控制台上输出执行的sql
    engine = create_engine("sqlite:///mydb", echo=True)

    # 2. 创建数据库和表
    # Base.metadata.create_all(engine)

    # 3. 批量插入数据
    # with Session(engine) as session:
    #     tom = User(
    #         name="tom"
    #     )
    #     jerry = User(
    #         name="jerry"
    #     )
    #     mike = User(
    #         name="mike"
    #     )
    #
    #     session.add_all([tom, jerry, mike])
    #     session.commit()

    # 4. 查询数据
    session = Session(engine)
    stmt = select(User).where(User.name.in_(["tom", "jerry"]))

    for user in session.scalars(stmt):
        print(user)


if __name__ == "__main__":
    main()
