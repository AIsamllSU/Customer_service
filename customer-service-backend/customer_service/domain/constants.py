# customer_service/domain/constants.py

"""
领域常量：把散落在各处的"魔法值"集中到一处。

原则：
- 只在确实跨模块复用、且语义固定的值放这里；
- 一次性的局部值不要为了"集中"而集中。
"""

# 聚焦对象类型（前端卡片 type 字段）
OBJECT_TYPE_ORDER = "order"
OBJECT_TYPE_PRODUCT = "product"

# 聚焦对象 -> 槽位 的映射键
SLOT_ORDER_NUMBER = "order_number"
SLOT_PRODUCT_ID = "product_id"

# 查询类 action 写回的槽位键（与 flow_config/user_flows.yml 保持一致）
SLOT_ORDER_STATUS = "order_status"
SLOT_ORDER_SUMMARY = "order_summary"
SLOT_TRACKING_NUMBER = "tracking_number"
SLOT_LOGISTICS_COMPANY = "logistics_company"
SLOT_LOGISTICS_STATUS = "logistics_status"

# 动作名称（与 flow_config/*.yml 的 action: 字段保持一致）
ACTION_RESPONSE = "action_response"
ACTION_LISTEN = "action_listen"
ACTION_LOOKUP_ORDER_STATUS = "action_lookup_order_status"
ACTION_LOOKUP_LOGISTICS = "action_lookup_logistics"
ACTION_RECOMMEND_SIMILAR_PRODUCTS = "action_recommend_similar_products"

# ActionResponse 的三种模式
RESPONSE_MODE_STATIC = "static"
RESPONSE_MODE_REPHRASE = "rephrase"
RESPONSE_MODE_GENERATE = "generate"

# generate 模式在 LLM 不可用时的兜底话术（rephrase 有底稿，可直接退回底稿）
ACTION_GENERATE_FALLBACK_TEXT = "抱歉，我这边暂时无法生成回复，请稍后再试。"

# 系统流程 id（与 flow_config/system_flows.yml 保持一致）
SYSTEM_FLOW_STARTED = "system_task_started"
SYSTEM_FLOW_INTERRUPTED = "system_task_interrupted"
SYSTEM_FLOW_RESUMED = "system_task_resumed"
SYSTEM_FLOW_CANCELED = "system_task_canceled"
SYSTEM_FLOW_COLLECT_INFORMATION = "system_collect_information"

# 会话与提示词窗口
SESSION_IDLE_TIMEOUT_SECONDS = 60 * 60
HISTORY_WINDOW_TURNS = 10
