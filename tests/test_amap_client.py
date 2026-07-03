"""集成测试：高德 API 客户端（Mock HTTP）"""

import json
from unittest.mock import patch

import requests

from utils.amap_client import _get_api_key, _mock_location, _mock_weather


class TestAmapClientMocked:
    """Mock 高德 API 响应，验证解析逻辑"""

    def test_ip_location_parses_correctly(self):
        """验证 IP 定位响应解析正确（mock 完整调用链）"""
        mock_resp = requests.Response()
        mock_resp.status_code = 200
        mock_resp._content = json.dumps(
            {
                "status": "1",
                "province": "广东省",
                "city": "深圳市",
                "adcode": "440300",
            }
        ).encode()

        # 在 amap_client 模块内 patch requests.get（tenacity 会通过此引用调用）
        with (
            patch("utils.amap_client.requests.get", return_value=mock_resp),
            patch.dict("os.environ", {"AMAP_API_KEY": "test_key"}),
        ):
            from utils.amap_client import get_location_by_ip

            # 清除 lru_cache 确保不走缓存
            get_location_by_ip.cache_clear()
            result = get_location_by_ip()

        assert result["city"] == "深圳市"
        assert result["province"] == "广东省"
        assert "adcode" in result

    def test_weather_parses_correctly(self):
        """验证天气响应解析正确"""
        mock_resp = requests.Response()
        mock_resp.status_code = 200
        mock_resp._content = json.dumps(
            {
                "status": "1",
                "lives": [
                    {
                        "city": "北京",
                        "weather": "晴",
                        "temperature": "25",
                        "winddirection": "北",
                        "windpower": "3",
                        "humidity": "40",
                    }
                ],
            }
        ).encode()

        with (
            patch("utils.amap_client.requests.get", return_value=mock_resp),
            patch.dict("os.environ", {"AMAP_API_KEY": "test_key"}),
        ):
            from utils.amap_client import get_weather_by_city

            result = get_weather_by_city("北京")

        assert "北京" in result
        assert "晴" in result

    def test_mock_location_has_required_keys(self):
        """模拟定位数据包含必要字段"""
        loc = _mock_location()
        assert "city" in loc
        assert "adcode" in loc

    def test_mock_weather_contains_city_name(self):
        """模拟天气包含城市名"""
        result = _mock_weather("上海")
        assert "上海" in result

    def test_get_api_key_empty_without_env(self):
        """无环境变量时返回空字符串"""
        with patch.dict("os.environ", {}, clear=True):
            key = _get_api_key()
            assert key == ""
