"""高德地图 MCP Server — 提供 IP定位、天气查询、地理编码等工具"""

import os
from pathlib import Path

import requests
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# 加载 .env
_env_file = Path(__file__).resolve().parents[1] / ".env"
if _env_file.exists():
    with open(_env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

AMAP_KEY = os.getenv("AMAP_API_KEY", "")
server = Server("amap-mcp-server")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="amap_ip_location",
            description="通过IP定位获取当前所在城市，返回城市名称",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="amap_weather",
            description="通过高德天气API查询指定城市的实时天气",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称，如'北京市'、'深圳市'",
                    }
                },
                "required": ["city"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if not AMAP_KEY:
        return [TextContent(type="text", text="错误：未配置 AMAP_API_KEY")]

    if name == "amap_ip_location":
        try:
            resp = requests.get(
                "https://restapi.amap.com/v3/ip",
                params={"key": AMAP_KEY},
                timeout=5,
            )
            data = resp.json()
            if data.get("status") == "1":
                return [TextContent(type="text", text=data.get("city", "未知"))]
            return [TextContent(type="text", text=f"定位失败: {data.get('info')}")]
        except Exception as e:
            return [TextContent(type="text", text=f"请求异常: {e}")]

    if name == "amap_weather":
        city = arguments["city"]
        try:
            resp = requests.get(
                "https://restapi.amap.com/v3/weather/weatherInfo",
                params={"key": AMAP_KEY, "city": city, "extensions": "base"},
                timeout=5,
            )
            data = resp.json()
            if data.get("status") == "1" and data.get("lives"):
                live = data["lives"][0]
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"{live['city']}天气{live['weather']}，"
                            f"气温{live['temperature']}℃，"
                            f"湿度{live['humidity']}%，"
                            f"{live['winddirection']}风{live['windpower']}级"
                        ),
                    )
                ]
            return [TextContent(type="text", text=f"天气查询失败: {data.get('info')}")]
        except Exception as e:
            return [TextContent(type="text", text=f"请求异常: {e}")]

    return [TextContent(type="text", text=f"未知工具: {name}")]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
