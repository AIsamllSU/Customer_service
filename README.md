# 电商智能客服系统

一个基于大模型的电商客服系统，作为课程设计项目完成。用户在前端像聊天一样提问，后端调用大模型理解意图，再调用电商接口查询真实的订单、物流、商品数据，最后生成回复。整个项目拆成两个后端和一个前端，方便分开调试。

## 功能

**客服对话**
- 多轮聊天，对话状态按用户保存在 MySQL，刷新后可以接着聊
- 大模型负责意图理解，输出结构化的执行计划
- 计划会做合法性校验，模型给出不存在的流程或非法命令时直接拦截，避免乱执行
- 支持查物流、查订单状态、申请退款、催发货四类业务
- 支持商品知识问答和日常闲聊
- 历史记录接口（目前还是占位数据，真实历史会话后续补上）

**电商数据**
- 用户订单列表、订单详情、订单状态
- 物流公司与物流轨迹
- 商品详情
- 创建发货提醒、创建退款申请

**坐席工作台**
- 对话窗口，支持发送文本消息、查看机器人回复
- 侧边栏展示当前用户的订单和商品
- 页面加载时拉取历史消息

## 技术栈

| 部分 | 技术 |
| --- | --- |
| 客服后端 | Python 3.12、FastAPI、LangChain、SQLAlchemy 2.0（异步）、MySQL |
| 电商后端 | Python 3.12、FastAPI、SQLAlchemy、PyMySQL |
| 前端 | Vue 3、Vite |
| 部署 | Docker、Docker Compose、Nginx |

## 目录结构

```
.
├── customer-service-backend/     客服后端（对话、规划、流程、知识问答）
│   ├── customer_service/         源码包
│   ├── flow_config/              业务流程 YAML
│   └── Dockerfile
├── ecommerce-service-backend/    电商数据服务
│   ├── app/
│   └── Dockerfile
├── customer-service-frontend/    坐席工作台前端
│   ├── src/
│   ├── nginx.conf
│   └── Dockerfile
└── docker/
    ├── docker-compose.yml        一键部署全部服务
    ├── mysql/initdb/             建库建表和初始数据
    └── windows/initdb/           本机 MySQL 用的同一份脚本
```

## 本地运行

### 0. 环境准备

- Python 3.12、[uv](https://docs.astral.sh/uv/)
- Node.js 18 以上
- MySQL 8

### 1. 初始化数据库

用本机 MySQL 客户端依次执行（账号密码按自己的改）：

```bash
mysql -uroot -p < docker/mysql/initdb/001_init_customer_service.sql
mysql -uroot -p < docker/mysql/initdb/002_init_commerce.sql
```

两个脚本会创建 `customer_service` 和 `commerce` 两个库，并写入演示数据（3 个用户、6 个商品、8 个订单）。

### 2. 启动电商后端

```powershell
cd ecommerce-service-backend
uv sync
copy .env.example .env      # 改 DATABASE_URL 里的密码
uv run python main.py
```

地址 `http://127.0.0.1:18081`。

### 3. 启动客服后端

```powershell
cd customer-service-backend
uv sync
copy .env.example .env      # 填 DATABASE_URL 和 LLM_API_KEY
uv run python -m customer_service.main
```

地址 `http://127.0.0.1:18082`。大模型用的是通义千问，需要在[阿里云百炼](https://bailian.console.aliyun.com/)申请 API Key，也可以把 `LLM_BASE_URL`、`LLM_MODEL` 换成其他 OpenAI 兼容服务。

### 4. 启动前端

```powershell
cd customer-service-frontend
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。开发环境的接口代理在 `vite.config.js` 里配置：`/api` 转发到客服后端，`/commerce` 转发到电商后端。

## Docker 部署

`docker/` 目录下有完整的 compose 配置，包含 MySQL、两个后端和 Nginx 托管的前端：

```bash
cd docker
docker compose up -d --build
```

启动后访问 `http://localhost:8080` 即可打开工作台。首次启动会自动执行 `mysql/initdb` 下的脚本建表并写入数据。

注意：客服后端容器会读取 `customer-service-backend/.env` 里的模型配置，部署前需要先准备好这个文件。

## 接口说明

客服后端：

- `POST /api/chat`，请求体 `{"sender_id": "...", "text": "..."}`
- `GET /api/chat/history?sender_id=...`

电商后端的主要接口：

- `GET /health`
- `GET /users/{user_id}/orders`
- `GET /orders/{order_id}/logistics`
- `GET /products/{product_id}`
- `POST /orders/{order_id}/refund-applications`

完整接口文档在两个服务启动后可以直接看 `/docs`。

## 说明

- `.env` 里是数据库密码和模型 Key，已加入 `.gitignore`，仓库里只有 `.env.example`。
- 数据库里的用户、订单、商品都是脚本生成的模拟数据，仅用于功能演示。
- 前端发送语音的按钮调用了 `/api/chat/tts`，这个接口后端还没有实现，不影响文字聊天。
- 项目还在继续完善，后续打算补上语音播报、知识库向量检索和更细的权限控制。
