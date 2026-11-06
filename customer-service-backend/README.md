# 客服后端

电商客服系统的对话服务，负责把用户的一句话送进大模型，规划出这一轮要做的事情，再调用电商接口拿真实数据，最后组织成回复返回给前端。

## 主要功能

- 多轮对话：按 `sender_id` 保存对话状态，刷新页面后仍能接着聊
- 意图规划：调用大模型输出结构化计划（走任务流、查知识、闲聊三种轨道）
- 防幻觉校验：对模型输出的计划做轨道与流程图校验，非法命令直接拒绝执行
- 业务流程：查物流、查订单状态、退款申请、催发货，流程用 YAML 定义
- 知识问答与闲聊：商品、订单等知识检索，以及普通寒暄
- 历史记录接口：按用户返回最近对话

## 技术栈

- Python 3.12 + FastAPI + Uvicorn
- LangChain + langchain-openai（通义千问，OpenAI 兼容协议）
- SQLAlchemy 2.0 异步引擎 + aiomysql，对话状态存 MySQL
- pydantic-settings 管理配置，Jinja2 渲染提示词，pytest + ruff

## 目录结构

```
customer-service-backend/
├── customer_service/
│   ├── api/                FastAPI 应用、路由、请求响应模型
│   ├── conf/               配置与日志
│   ├── domain/             领域模型、对话状态
│   ├── engine/             对话引擎
│   ├── infrastructure/     LLM、HTTP 客户端、数据库
│   ├── knowledge/          知识检索
│   ├── chitchat/           闲聊
│   ├── model/              ORM 模型
│   ├── plan/               计划生成与校验
│   ├── prompts/            提示词模板与历史构建
│   ├── repository/         状态持久化
│   ├── responder/          澄清回复
│   ├── service/            业务编排
│   ├── task/               命令处理、流程执行、动作体系
│   └── test/               单元测试
├── flow_config/            业务流程 YAML
├── .env.example            配置模板
└── pyproject.toml
```

## 运行

需要 Python 3.12、uv、MySQL 8。先执行 `docker/mysql/initdb/001_init_customer_service.sql` 建库建表。

```powershell
cd customer-service-backend
uv sync
copy .env.example .env     # 填入数据库连接和 LLM_API_KEY
uv run pytest              # 离线测试，不需要数据库和模型
uv run python -m customer_service.main
```

启动后接口文档在 `http://127.0.0.1:18082/docs`。

## 接口

- `POST /api/chat`：发送一条消息，返回机器人回复
- `GET /api/chat/history?sender_id=xxx`：查询历史对话

请求示例：

```bash
curl -X POST http://127.0.0.1:18082/api/chat \
  -H "Content-Type: application/json" \
  -d '{"sender_id":"u1001","text":"帮我查一下订单 A20260408002 的物流"}'
```

## 说明

`.env` 放数据库密码和模型 Key，已加入 `.gitignore`，不要提交到仓库。
