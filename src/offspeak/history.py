import json
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from offspeak.audio import save_wav

SCHEMA = """
CREATE TABLE IF NOT EXISTS recording (
    id TEXT PRIMARY KEY,
    datetime TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    mode TEXT NOT NULL,
    voice_model TEXT NOT NULL,
    language_model TEXT NOT NULL DEFAULT '',
    raw_text TEXT NOT NULL,
    result TEXT NOT NULL,
    app_name TEXT NOT NULL DEFAULT '',
    stt_ms INTEGER NOT NULL DEFAULT 0,
    llm_ms INTEGER NOT NULL DEFAULT 0,
    from_file INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_recording_datetime ON recording(datetime);
CREATE VIRTUAL TABLE IF NOT EXISTS recording_fts USING fts5(id UNINDEXED, raw_text, result, tokenize='unicode61');
"""


class History:
    def __init__(self, root: Path):
        self.root = root
        self.recordings_dir = root / "recordings"
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(root / "history.sqlite", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def add(self, audio: np.ndarray | None, meta: dict) -> str:
        rec_id = str(int(time.time() * 1000))
        folder = self.recordings_dir / rec_id
        folder.mkdir()
        if audio is not None and audio.size:
            save_wav(folder / "Output.wav", audio)
        # the context (selected text, clipboard, window title) only feeds the language model; never store it
        meta = {"id": rec_id, "datetime": datetime.now().isoformat(timespec="seconds"),
                **{k: v for k, v in meta.items() if k != "context"}}
        (folder / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO recording (id, datetime, duration_ms, mode, voice_model, language_model, raw_text,"
                " result, app_name, stt_ms, llm_ms, from_file) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec_id, meta["datetime"], meta.get("duration_ms", 0), meta.get("mode", ""),
                 meta.get("voice_model", ""), meta.get("language_model", ""), meta.get("raw_text", ""),
                 meta.get("result", ""), meta.get("app_name", ""), meta.get("stt_ms", 0),
                 meta.get("llm_ms", 0), int(meta.get("from_file", False))),
            )
            self._db.execute("INSERT INTO recording_fts (id, raw_text, result) VALUES (?,?,?)",
                             (rec_id, meta.get("raw_text", ""), meta.get("result", "")))
        return rec_id

    def recent(self, limit: int = 20) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute("SELECT * FROM recording ORDER BY datetime DESC, id DESC LIMIT ?", (limit,)).fetchall()

    def search(self, query: str, limit: int = 20) -> list[sqlite3.Row]:
        fts_query = " ".join('"' + w.replace('"', '""') + '"' for w in query.split())
        with self._lock:
            return self._db.execute(
                "SELECT r.* FROM recording_fts f JOIN recording r ON r.id = f.id "
                "WHERE recording_fts MATCH ? ORDER BY r.datetime DESC LIMIT ?", (fts_query, limit)).fetchall()

    def cleanup_audio(self, keep_days: int) -> int:
        """Delete audio older than keep_days, or all audio for 0; transcripts stay in the history."""
        cutoff = int((time.time() - max(0, keep_days) * 86400) * 1000)
        removed = 0
        for wav in self.recordings_dir.glob("*/Output.wav"):
            if wav.parent.name.isdigit() and int(wav.parent.name) < cutoff:
                wav.unlink()
                removed += 1
        return removed
