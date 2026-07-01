from pathlib import Path

import pytest


@pytest.fixture
def sources_dir() -> Path:
    return Path(__file__).parent.parent / "sources"


@pytest.fixture
def pipeline_dir(tmp_path: Path) -> Path:
    return tmp_path / "pipeline"
