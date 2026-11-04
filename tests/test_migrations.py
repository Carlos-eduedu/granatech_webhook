"""As migrações sobem, descem e batem com os models (SQLite)."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _alembic(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_upgrade_downgrade_upgrade_e_check(tmp_path: Path) -> None:
    banco = tmp_path / "migracoes.db"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{banco}",
        "APP_ENV": "test",
    }

    comandos = [
        ("upgrade", "head"),
        ("downgrade", "base"),
        ("upgrade", "head"),
        ("check",),
    ]
    for comando in comandos:
        resultado = _alembic(env, *comando)
        assert resultado.returncode == 0, (
            f"alembic {' '.join(comando)} falhou:\n{resultado.stdout}\n{resultado.stderr}"
        )
