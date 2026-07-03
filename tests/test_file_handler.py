"""测试 utils/file_handler.py"""

import hashlib
import os
import tempfile
from pathlib import Path

from utils.file_handler import get_file_md5_hex, listdir_with_allowed_type


class TestGetFileMd5Hex:
    """get_file_md5_hex 测试"""

    def test_valid_file_returns_correct_md5(self):
        """正常文件应返回正确的 MD5"""
        content = b"hello world"
        expected = hashlib.md5(content).hexdigest()

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            tmp_path = f.name

        try:
            result = get_file_md5_hex(tmp_path)
            assert result == expected
        finally:
            os.unlink(tmp_path)

    def test_nonexistent_file_returns_none(self):
        """不存在的文件返回 None"""
        result = get_file_md5_hex("/tmp/__nonexistent_file__.xyz")
        assert result is None

    def test_directory_not_file_returns_none(self):
        """传入目录路径返回 None"""
        result = get_file_md5_hex(tempfile.gettempdir())
        assert result is None

    def test_empty_file_returns_known_md5(self):
        """空文件返回 d41d8cd98f00b204e9800998ecf8427e"""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            tmp_path = f.name

        try:
            result = get_file_md5_hex(tmp_path)
            assert result == "d41d8cd98f00b204e9800998ecf8427e"
        finally:
            os.unlink(tmp_path)

    def test_large_file_chunked_reading(self, tmp_path: Path):
        """超过 4KB 的文件验证分块读取正确"""
        content = os.urandom(10000)  # > 4096 触发分块
        expected = hashlib.md5(content).hexdigest()

        file_path = tmp_path / "large.bin"
        file_path.write_bytes(content)

        result = get_file_md5_hex(str(file_path))
        assert result == expected


class TestListdirWithAllowedType:
    """listdir_with_allowed_type 测试"""

    def test_filters_by_extension(self, tmp_path: Path):
        """只返回匹配后缀的文件"""
        (tmp_path / "a.txt").touch()
        (tmp_path / "b.txt").touch()
        (tmp_path / "c.pdf").touch()
        (tmp_path / "d.jpg").touch()

        result = listdir_with_allowed_type(str(tmp_path), (".txt",))
        assert len(result) == 2
        assert all(p.endswith(".txt") for p in result)

    def test_multiple_allowed_types(self, tmp_path: Path):
        """支持多个后缀过滤"""
        (tmp_path / "a.txt").touch()
        (tmp_path / "b.pdf").touch()
        (tmp_path / "c.jpg").touch()

        result = listdir_with_allowed_type(str(tmp_path), (".txt", ".pdf"))
        assert len(result) == 2

    def test_empty_directory(self, tmp_path: Path):
        """空目录返回空元组"""
        result = listdir_with_allowed_type(str(tmp_path), (".txt",))
        assert result == tuple()

    def test_not_a_directory_returns_empty(self):
        """非目录路径返回空元组"""
        result = listdir_with_allowed_type("/tmp/__nonexistent_dir__", (".txt",))
        assert result == tuple()

    def test_returns_absolute_paths(self, tmp_path: Path):
        """返回的是绝对路径"""
        (tmp_path / "a.txt").touch()

        result = listdir_with_allowed_type(str(tmp_path), (".txt",))
        assert len(result) == 1
        assert os.path.isabs(result[0])
