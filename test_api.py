import sys
sys.path.insert(0, '/app/src')
import aiohttp, asyncio
from config import config

async def test():
    base = config.XUI_API_URL
    token = config.XUI_API_TOKEN
    print(f"Base URL: {base}")
    print(f"Token: {token[:10]}...")

    async with aiohttp.ClientSession() as s:
        for path in ["/login", "/panel/login", "/api/inbounds", "/panel/api/inbounds",
                      "/api/inbounds/get/1", "/panel/api/inbounds/get/1"]:
            url = base + path
            try:
                async with s.post(url, headers={"Authorization": f"Bearer {token}"}, ssl=False) as r:
                    print(f"POST {path} -> {r.status}")
                async with s.get(url, headers={"Authorization": f"Bearer {token}"}, ssl=False) as r:
                    body = await r.text()
                    print(f"GET  {path} -> {r.status} ({len(body)}b) {body[:80]}")
            except Exception as e:
                print(f"     {path} -> ERROR: {e}")

asyncio.run(test())
