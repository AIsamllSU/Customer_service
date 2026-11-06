# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# 使用 uv 按 lock 文件安装依赖，保证与本地环境一致
# 国内网络下走镜像源，避免直连 PyPI 超时
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache

COPY . .

EXPOSE 18082

CMD ["uv", "run", "--no-dev", "--no-sync", "uvicorn", "atguigu.api.app:app", "--host", "0.0.0.0", "--port", "18082"]
