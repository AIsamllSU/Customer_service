# customer-service-backend（电商小二 · 客服后端）

电商智能客服系统的后端服务。核心命题：**用工程化方式驯服 LLM 的不确定性，让业务结果稳定可控**。

当前仓库进度：**Day 07 —— TaskHandler 与 CommandProcessor**。

## 一、当前已完成范围

| 模块 | 文件 | 说明 |
| --- | --- | --- |
| 配置加载 | `atguigu/conf/config.py` | `pydantic-settings` 从 `.env` 读取配置，全局 `settings` 单例 |
| 日志 | `atguigu/conf/logging.py` | 统一日志格式与级别，生产由 `APP_LOG_LEVEL` 控制 |
| LLM 接入 | `atguigu/infrastructure/llm.py` | `init_chat_model` 统一接入通义千问（OpenAI 兼容协议） |
| HTTP 客户端 | `atguigu/infrastructure/http_client.py` | `httpx.AsyncClient` 全局懒初始化 + 生命周期关闭 |
| 数据库 | `atguigu/infrastructure/database.py` | SQLAlchemy 2.0 异步引擎 + `async_sessionmaker`，SQL 回显由 `DATABASE_ECHO` 控制 |
| 接口层 | `atguigu/api/` | `POST /api/chat`、`GET /api/chat/history`；请求校验、异常兜底、CORS |
| 业务编排 | `atguigu/service/dialogue_service.py` | 加载状态 → 引擎处理 → 保存状态 |
| 对话引擎 | `atguigu/engine/dialogue_engine.py` | 会话管理、文本三轨分发、防幻觉校验、对象消息三场景 |
| 规划层 | `atguigu/plan/` | `TurnPlanner`（LLM 出计划、有限重试）、`TurnPlanValidator`（四重校验） |
| 任务层 | `atguigu/task/` | `CommandProcessor`（四种命令 + 任务生命周期）、`Action` 体系（注册表 / 执行器 / 内置与自定义动作）、`TaskHandler`（两阶段） |
| 澄清层 | `atguigu/responder/` | `ClarifyResponder` + Jinja2 模板，LLM 失败自动回退规则话术 |
| 流程定义 | `flow_config/*.yml` | 业务流 + 系统过场流，`start` / `collect` / `action` / `end` |
| 测试 | `atguigu/test/` | 88 个离线用例 + 真实 LLM / HTTP / 落库验证脚本 |

> 当前进度说明：`CommandProcessor` 已能把命令真正落到 `DialogueState`，Action 体系（查订单 / 查物流 / 推荐 / 回复三模式）已就绪；
> 按 YAML 推进流程并调用 action 的 `FlowExecutor` 在 Day09 实现。
> `knowledge` / `chitchat` 两条轨道已预留分发入口，处理器待后续章节补齐。
> `GET /api/chat/history` 仍是占位假数据，真实历史查询在后续章节实现。

## 二、环境要求

- Python 3.12
- [uv](https://docs.astral.sh/uv/) 包管理器
- MySQL 8（本机已装 8.0.26，服务 `MySQL80`，需提前建库 `customer_service`）

## 三、快速开始

```bash
# 1. 安装依赖（自动创建 .venv）
uv sync

# 2. 准备配置
copy .env.example .env    # Windows
# 然后填入自己的 LLM_API_KEY

# 3. 验证配置读取
uv run python -m atguigu.conf.config

# 4. 全量离线测试（不依赖 LLM / MySQL）
uv run pytest

# 5. 启动服务
uv run python -m atguigu.main

# 6. 端到端验证（真实 LLM + MySQL）
uv run python -m atguigu.test.plan.verify_day06
uv run python -m atguigu.test.api.verify_api
```

启动后访问 `http://127.0.0.1:18082/docs` 查看 OpenAPI 文档。

### 接口示例

```bash
curl -X POST http://127.0.0.1:18082/api/chat \
  -H "Content-Type: application/json" \
  -d '{"sender_id":"u1","message_id":"m1","type":"text","text":"我要退款"}'
```

## 四、目录结构

```
customer-service-backend/
├── atguigu/
│   ├── api/                  FastAPI 应用、路由、请求/响应模型、依赖注入
│   ├── conf/                 配置与日志
│   ├── domain/               领域模型、状态、上下文、常量
│   ├── engine/               对话引擎（三轨分发 + 校验 + 对象消息）
│   ├── infrastructure/       LLM / HTTP / 数据库
│   ├── knowledge/            知识意图定义
│   ├── model/                SQLAlchemy ORM 模型
│   ├── plan/                 计划生成、计划模型、防幻觉校验
│   ├── prompts/              提示词加载、历史构建、Jinja2 模板
│   ├── repository/           状态持久化
│   ├── responder/            澄清回复
│   ├── service/              业务编排
│   ├── task/                 command / flow DSL / action / handler
│   └── test/                 api / plan / task / domain / flow 测试与验证脚本
├── flow_config/              业务流程 YAML
├── data/                     本地 SQLite 文件（已 gitignore）
├── .env.example              配置模板
└── pyproject.toml
```

## 五、安全说明

`.env` 已加入 `.gitignore`，**不要提交真实 API Key**。若 Key 曾以明文形式出现在压缩包、聊天记录或截图中，请到阿里云百炼控制台作废并重新生成。
