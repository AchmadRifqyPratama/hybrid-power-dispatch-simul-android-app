"""Penyimpanan proyek berbasis SQLite: konfigurasi, profil data, hasil optimasi."""
from __future__ import annotations
import io
import json
import os
import sqlite3
from datetime import datetime

import numpy as np


class ProjectDB:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.execute("""CREATE TABLE IF NOT EXISTS project(
            id INTEGER PRIMARY KEY CHECK (id=1),
            name TEXT, customer TEXT, location TEXT,
            created TEXT, config TEXT)""")
        self.con.execute("""CREATE TABLE IF NOT EXISTS profiles(
            kind TEXT PRIMARY KEY, datetimes TEXT, data BLOB)""")
        self.con.execute("""CREATE TABLE IF NOT EXISTS opt_results(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created TEXT, objective TEXT, n_combos INTEGER, data BLOB)""")
        self.con.commit()

    # ---------------- project & config ----------------
    def save_project(self, cfg: dict):
        self.con.execute(
            "INSERT INTO project(id,name,customer,location,created,config) "
            "VALUES(1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "name=excluded.name, customer=excluded.customer, "
            "location=excluded.location, config=excluded.config",
            (cfg.get('project_name', ''), cfg.get('customer', ''),
             cfg.get('location', ''), datetime.now().isoformat(timespec='seconds'),
             json.dumps(cfg)))
        self.con.commit()

    def load_project(self) -> dict | None:
        row = self.con.execute(
            "SELECT name, customer, location, created, config FROM project "
            "WHERE id=1").fetchone()
        if not row:
            return None
        cfg = json.loads(row[4]) if row[4] else {}
        cfg['_created'] = row[3]
        return cfg

    # ---------------- profiles ----------------
    def save_profile(self, kind: str, datetimes, arr: np.ndarray):
        buf = io.BytesIO()
        np.save(buf, np.asarray(arr, float))
        dts = json.dumps([str(d) for d in datetimes]) if datetimes is not None else None
        self.con.execute(
            "INSERT INTO profiles(kind,datetimes,data) VALUES(?,?,?) "
            "ON CONFLICT(kind) DO UPDATE SET datetimes=excluded.datetimes, "
            "data=excluded.data", (kind, dts, buf.getvalue()))
        self.con.commit()

    def load_profile(self, kind: str):
        row = self.con.execute(
            "SELECT datetimes, data FROM profiles WHERE kind=?", (kind,)).fetchone()
        if not row:
            return None, None
        arr = np.load(io.BytesIO(row[1]))
        dts = json.loads(row[0]) if row[0] else None
        return dts, arr

    def delete_profile(self, kind: str):
        self.con.execute("DELETE FROM profiles WHERE kind=?", (kind,))
        self.con.commit()

    # ---------------- optimization results ----------------
    def save_opt(self, objective: str, res: dict):
        buf = io.BytesIO()
        np.savez_compressed(buf, **{k: np.asarray(v) for k, v in res.items()})
        self.con.execute(
            "INSERT INTO opt_results(created,objective,n_combos,data) "
            "VALUES(?,?,?,?)",
            (datetime.now().isoformat(timespec='seconds'), objective,
             int(len(res['kwp'])), buf.getvalue()))
        self.con.commit()

    def close(self):
        self.con.close()
