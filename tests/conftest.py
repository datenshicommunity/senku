import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    def _load(name: str) -> str:
        with open(FIXTURES / name, encoding="utf-8-sig") as f:
            return f.read()

    return _load
