import logging
from contextlib import contextmanager
from os.path import exists
from sqlite3 import connect, Cursor

from constants import NUM_CAMERAS, NUM_BUTTONS, DB_FILE

LOG = logging.getLogger("db")


class Database:
    connection = None

    def __init__(self):
        if not exists(DB_FILE):
            LOG.info("Initialize sqlite database...")
            with self.cursor() as cur:
                cur.execute("CREATE TABLE positions ("
                            "cam INTEGER NOT NULL, "
                            "pos INTEGER NOT NULL, "
                            "name VARCHAR NOT NULL DEFAULT '', "
                            "btn_class VARCHAR NOT NULL DEFAULT 'btn-secondary', "
                            "focus INTEGER NOT NULL DEFAULT -1, "
                            "PRIMARY KEY (cam, pos))")
                for cam in range(NUM_CAMERAS):
                    for pos in range(NUM_BUTTONS):
                        cur.execute("INSERT INTO positions (cam, pos) VALUES (?, ?)", (cam, pos))
            LOG.info("Initialization complete")

    @contextmanager
    def dict_cursor(self) -> Cursor:
        connection = None
        try:
            connection = connect(DB_FILE)
            connection.row_factory = lambda cursor, row: {c[0]: row[i] for i, c in enumerate(cursor.description)}
            yield connection.cursor()
            connection.commit()
        finally:
            if connection is not None:
                connection.close()

    @contextmanager
    def cursor(self) -> Cursor:
        connection = None
        try:
            connection = connect(DB_FILE)
            yield connection.cursor()
            connection.commit()
        finally:
            if connection is not None:
                connection.close()

    def set_button(self, cam: int, pos: int, name: str, btn_class: str):
        with self.cursor() as cur:
            cur.execute("UPDATE positions SET name = ?, btn_class = ? WHERE cam = ? AND pos = ?",
                        (name, btn_class, cam, pos))

    def set_focus(self, cam: int, pos: int, focus: int):
        with self.cursor() as cur:
            cur.execute("UPDATE positions SET focus = ? WHERE cam = ? AND pos = ?", (focus, cam, pos))

    def get_focus(self, cam: int, pos: int) -> int:
        with self.cursor() as cur:
            cur.execute("SELECT focus FROM positions WHERE cam = ? AND pos = ?", (cam, pos))
            return cur.fetchone()[0]

    def get_data(self) -> list:
        with self.dict_cursor() as cur:
            return list(cur.execute("SELECT cam, pos, name, btn_class FROM positions ORDER BY cam, pos"))

    def clear_buttons(self):
        with self.cursor() as cur:
            cur.execute("UPDATE positions SET name = '', btn_class = 'btn-secondary'")
