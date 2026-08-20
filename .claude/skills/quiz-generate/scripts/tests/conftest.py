import shutil
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

FIXTURES = TESTS_DIR / "fixtures"


@pytest.fixture
def env_basic(tmp_path):
    """把 env-basic 迷你题库复制到 tmp_path，返回其根（含 jlpt-notes/ 的目录）。"""
    dst = tmp_path / "env"
    shutil.copytree(FIXTURES / "env-basic", dst)
    return dst


@pytest.fixture
def mutate():
    """对 env 内相对路径做恰好一次子串替换；目标不存在时立即使测试失败。"""
    def _mutate(root: Path, rel: str, old: str, new: str) -> None:
        p = root / rel
        text = p.read_text(encoding="utf-8")
        assert old in text, f"mutation target not found in {rel}: {old!r}"
        p.write_text(text.replace(old, new, 1), encoding="utf-8")
    return _mutate
