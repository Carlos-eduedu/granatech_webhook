"""Aplica as migrações do Alembic antes de subir o servidor.

Funciona com bancos novos (``upgrade head``) e com bancos criados pelo
``create_all`` antigo, que ainda não têm ``alembic_version``. Nesse caso,
faz-se ``stamp 0001_baseline`` antes do ``upgrade head``.
"""

import logging
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from .settings import get_settings

logger = logging.getLogger(__name__)

_TABELA_EVENTOS = "granatech_webhook_eventos"
_TABELA_ALEMBIC = "alembic_version"
_REVISAO_BASELINE = "0001_baseline"


def _base_dir() -> Path:
    """Acha a raiz do projeto tanto no fonte quanto no container (/app)."""
    candidatos = [Path.cwd(), Path(__file__).resolve().parents[2]]
    for candidato in candidatos:
        if (candidato / "alembic.ini").is_file():
            return candidato
    raise RuntimeError(
        "alembic.ini não encontrado; rode a partir da raiz do projeto "
        "ou defina o WORKDIR correto no container"
    )


def _config() -> Config:
    base = _base_dir()
    config = Config(str(base / "alembic.ini"))
    config.set_main_option("script_location", str(base / "migrations"))
    return config


def precisa_de_stamp(engine: Engine) -> bool:
    """Banco antigo: tabelas existem, mas o controle do Alembic não."""
    inspetor = inspect(engine)
    tabelas = set(inspetor.get_table_names())
    return _TABELA_EVENTOS in tabelas and _TABELA_ALEMBIC not in tabelas


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    settings = get_settings()
    config = _config()
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        if precisa_de_stamp(engine):
            logger.info(
                "banco antigo sem %s; aplicando stamp %s",
                _TABELA_ALEMBIC,
                _REVISAO_BASELINE,
            )
            command.stamp(config, _REVISAO_BASELINE)
        logger.info("aplicando migrações até head")
        command.upgrade(config, "head")
        logger.info("migrações aplicadas com sucesso")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
