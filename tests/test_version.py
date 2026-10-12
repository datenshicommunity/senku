"""The version a user sees from `senku.__version__` must be the one the package is released as."""

import re
from pathlib import Path

import senku


def test_package_version_matches_pyproject():
    pyproject = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, flags=re.M).group(1)
    assert senku.__version__ == declared, (
        "senku.__version__ is %r but pyproject.toml releases %r; bump both together" % (senku.__version__, declared)
    )
