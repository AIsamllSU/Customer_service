import asyncio

import httpx
from httpx import AsyncClient

# 同步方式
# r = httpx.get('http://localhost:18081/users/u1001/orders')
# print(r.json())

# 异步方式
# async def test():
#     async with httpx.AsyncClient() as client:
#         r = await client.get('http://localhost:18081/users/u1001/orders')
#         print(r.json()['data']['user_id'])
# asyncio.run(test())

http_client: AsyncClient | None = None


# 初始化
def init_http_client():
    global http_client
    http_client = httpx.AsyncClient()


# 关闭
async def close_http_client():
    if http_client is not None:
        await http_client.aclose()


if __name__ == "__main__":

    async def test():
        init_http_client()
        result = await http_client.get("http://localhost:18081/users/u1001/orders")
        print(result.json())
        await close_http_client()

    asyncio.run(test())
