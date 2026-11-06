# 电商业务服务

一个用于客服系统联调的电商数据服务，提供订单、物流、商品等查询接口，以及发货提醒和退款申请两个写接口。数据用 MySQL 存储，启动时通过 SQL 脚本初始化一批模拟数据，覆盖待发货、运输中、已完成、已取消等常见订单状态。

## 功能

- 查询用户最近的订单和商品
- 查询订单详情、订单状态
- 查询物流公司与物流轨迹
- 查询商品详情
- 创建发货提醒、创建退款申请

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查 |
| GET | `/users/{user_id}/orders` | 用户最近订单 |
| GET | `/users/{user_id}/products` | 用户最近商品 |
| GET | `/orders/{order_id}` | 订单详情 |
| GET | `/orders/{order_id}/status` | 订单状态 |
| GET | `/orders/{order_id}/logistics` | 物流信息 |
| GET | `/products/{product_id}` | 商品详情 |
| POST | `/orders/{order_id}/shipping-reminders` | 创建发货提醒 |
| POST | `/orders/{order_id}/refund-applications` | 创建退款申请 |

## 运行

需要 Python 3.12、uv 和 MySQL 8。先在 MySQL 中执行 `docker/mysql/initdb/002_init_commerce.sql` 建库建表并写入初始数据，然后：

```powershell
cd ecommerce-service-backend
uv sync
copy .env.example .env
uv run python main.py
```

默认地址 `http://127.0.0.1:18081`，接口文档在 `/docs`。
