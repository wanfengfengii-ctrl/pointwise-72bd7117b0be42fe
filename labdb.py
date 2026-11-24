from contextlib import contextmanager
from pathlib import Path
import sqlite3


def open_database(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute('PRAGMA foreign_keys = ON')
    except BaseException:
        connection.close()
        raise
    return connection


def is_record_number(value: object) -> bool:
    return type(value) is int and 0 < value <= (1 << 63) - 1


@contextmanager
def write_transaction(connection: sqlite3.Connection):
    if connection.in_transaction:
        raise sqlite3.ProgrammingError('a ledger write requires an idle connection')
    connection.execute('BEGIN IMMEDIATE')
    try:
        yield
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def initialize(connection: sqlite3.Connection, *statements: str) -> None:
    with write_transaction(connection):
        for statement in statements:
            connection.execute(statement)
