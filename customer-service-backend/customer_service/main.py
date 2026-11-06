# customer_service/main.py

"""
启动 uvicorn。

运行方式（必须在项目根目录 customer-service-backend 下）：
    uv run python -m customer_service.main
"""

import uvicorn

from customer_service.conf.config import settings
from customer_service.conf.logging import configure_logging

if __name__ == "__main__":
    configure_logging()
    uvicorn.run(
        app="customer_service.api.app:app",
        host=settings.app_host,
        port=settings.app_port,
    )
