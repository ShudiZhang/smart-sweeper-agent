"""测试 utils/path_tool.py"""

import os

from utils.path_tool import get_abs_path, get_project_root


class TestGetProjectRoot:
    """get_project_root 测试"""

    def test_returns_string(self):
        result = get_project_root()
        assert isinstance(result, str)

    def test_returns_existing_directory(self):
        result = get_project_root()
        assert os.path.isdir(result)

    def test_ends_with_project_name(self):
        result = get_project_root()
        assert result.endswith("demo1_rag+agent")


class TestGetAbsPath:
    """get_abs_path 测试"""

    def test_returns_absolute_path(self):
        result = get_abs_path("config")
        assert os.path.isabs(result)

    def test_joins_under_project_root(self):
        result = get_abs_path("utils/path_tool.py")
        assert result.endswith("utils/path_tool.py")
        assert os.path.isfile(result)

    def test_relative_path_under_root(self):
        root = get_project_root()
        result = get_abs_path("pyproject.toml")
        expected = os.path.join(root, "pyproject.toml")
        assert result == expected
