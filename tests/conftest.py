"""测试共享 fixtures 和配置"""

import pytest


def pytest_configure(config):
    """注册自定义 marker"""
    config.addinivalue_line(
        "markers", "integration: 集成测试，需要外部服务（LLM、向量库等）"
    )


@pytest.fixture
def sample_md5_set() -> set[str]:
    """模拟的 MD5 去重集合"""
    return {"abc123def456", "789012abc345"}
