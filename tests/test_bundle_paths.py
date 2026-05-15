from __future__ import annotations

import sys

from server import config
from server import migrations


def test_resource_root_uses_pyinstaller_meipass(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert config._get_resource_root() == tmp_path


def test_alembic_config_uses_resource_root(monkeypatch, tmp_path):
    monkeypatch.setattr(migrations, "RESOURCE_ROOT", tmp_path)

    cfg = migrations._alembic_cfg()

    assert cfg.config_file_name == str(tmp_path / "alembic.ini")
    assert cfg.get_main_option("script_location") == str(tmp_path / "migrations")
