# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# 使用 uv 按 lock 文件安装依赖，保证与本地环境一致
RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache

COPY . .

EXPOSE 18081

CMD ["uv", "run", "--no-dev", "--no-sync", "uvicorn", "app.app:app", "--host", "0.0.0.0", "--port", "18081"]
