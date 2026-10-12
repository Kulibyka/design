"""Сохранить актуальную спецификацию API в openapi.yaml."""

from pathlib import Path

import yaml

from main import app


if __name__ == "__main__":
    Path(__file__).with_name("openapi.yaml").write_text(
        yaml.safe_dump(app.openapi(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
