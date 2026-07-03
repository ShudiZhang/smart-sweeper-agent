"""高德地图 API 客户端 — IP 定位 + 天气查询（带重试与降级）"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from utils.logger_handler import logger

# ---- 自动加载项目根目录的 .env 文件 ----
_env_file = Path(__file__).resolve().parents[1] / ".env"
if _env_file.exists():
    with open(_env_file, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))

# 高德 API 重试策略：网络/超时错误最多重试 3 次，指数退避
_AMAP_RETRY = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    reraise=True,
)


def _get_api_key() -> str:
    """从环境变量获取高德 API Key"""
    key = os.getenv("AMAP_API_KEY", "")
    if not key:
        logger.warning("[高德API] 未设置 AMAP_API_KEY 环境变量，将使用模拟数据")
    return key


# ---- 内部：带重试的 HTTP 请求 ----


@_AMAP_RETRY
def _request_ip_location(key: str) -> requests.Response:
    """IP 定位请求（带重试）"""
    return requests.get(
        "https://restapi.amap.com/v3/ip",
        params={"key": key},
        timeout=5,
    )


@_AMAP_RETRY
def _request_weather(key: str, city: str) -> requests.Response:
    """天气查询请求（带重试）"""
    return requests.get(
        "https://restapi.amap.com/v3/weather/weatherInfo",
        params={"key": key, "city": city, "extensions": "base"},
        timeout=5,
    )


# ---- 公开 API ----


@lru_cache(maxsize=1)
def get_location_by_ip() -> dict[str, str]:
    """
    通过 IP 定位获取当前城市信息（带重试，失败降级为模拟数据）
    返回: {"city": "深圳市", "adcode": "440300", "province": "广东省"}
    """
    key = _get_api_key()
    if not key:
        return _mock_location()

    try:
        resp = _request_ip_location(key)
        data: dict[str, Any] = resp.json()

        if data.get("status") == "1" and data.get("province"):
            return {
                "city": str(data.get("city", "")),
                "adcode": str(data.get("adcode", "")),
                "province": str(data.get("province", "")),
            }
        logger.warning(f"[高德API] IP定位失败: {data.get('info')}")
    except Exception as e:
        logger.error(f"[高德API] IP定位请求异常（已重试3次）: {e}")

    return _mock_location()


def get_weather_by_city(city: str) -> str:
    """
    根据城市名查询实时天气（带重试，失败降级为模拟数据）
    返回: 格式化的天气描述字符串
    """
    key = _get_api_key()
    if not key:
        return _mock_weather(city)

    try:
        resp = _request_weather(key, city)
        data: dict[str, Any] = resp.json()

        if data.get("status") == "1" and data.get("lives"):
            live = data["lives"][0]
            return (
                f"城市{live['city']}天气{live['weather']}，"
                f"气温{live['temperature']}℃，"
                f"风向{live['winddirection']}，"
                f"风力{live['windpower']}级，"
                f"湿度{live['humidity']}%"
            )
        logger.warning(f"[高德API] 天气查询失败: {data.get('info')}")
    except Exception as e:
        logger.error(f"[高德API] 天气请求异常（已重试3次）: {e}")

    return _mock_weather(city)


def _mock_location() -> dict[str, str]:
    """未配置 API Key 时的模拟定位"""
    return {"city": "深圳市", "adcode": "440300", "province": "广东省"}


def _mock_weather(city: str) -> str:
    """未配置 API Key 时的模拟天气"""
    return (
        f"城市{city}天气为晴天，气温26摄氏度，空气湿度50%，"
        f"南风1级，AQI21，最近6小时降雨概率极低"
    )
