"""SQLite do backend, em DATA_DIR.

Em teste e produção, DATA_DIR é /data: um volume que sobrevive aos deploys.
Nada fora dele persiste — o contêiner é recriado a cada publicação. Produção
já tem dados: mudanças de esquema são sempre aditivas (CREATE TABLE IF NOT
EXISTS, ALTER TABLE ADD COLUMN), aplicadas em ``init_db`` na subida.
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator


def data_dir() -> str:
    path = os.environ.get("DATA_DIR", "./data")
    os.makedirs(path, exist_ok=True)
    return path


def db_path() -> str:
    return os.path.join(data_dir(), "app.db")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """A connection that commits on success and rolls back on error."""
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


#: Esquema, em ordem. Só acrescente comandos; nunca edite nem remova os que já rodaram.
SCHEMA: list[str] = []


def init_db() -> None:
    with connect() as conn:
        # WAL: leituras não esperam a escrita em andamento.
        conn.execute("PRAGMA journal_mode = WAL")
        for statement in SCHEMA:
            conn.execute(statement)
