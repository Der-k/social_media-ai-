"""Tiny JSON-file store. Holds the whole demo state, writes atomically, can reset.

The store is deliberately simple: one JSON document, one lock. Repositories use
`read()` for queries and `update()` for changes; nothing else touches the file.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import date
from pathlib import Path
from typing import Any, Callable

from app.core.config import get_settings
from app.data.seed import SEED_VERSION, build_seed


class JsonStore:
    def __init__(self, path: Path, seed_factory: Callable[[], dict]):
        self._path = path
        self._seed_factory = seed_factory
        self._lock = threading.RLock()
        self._state: dict | None = None

    # -- internals ---------------------------------------------------------
    def _write(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=1), encoding="utf-8")
        os.replace(tmp, self._path)  # atomic on Windows and POSIX

    def _ensure_loaded(self) -> dict:
        with self._lock:
            if self._state is None:
                state = None
                if self._path.exists():
                    try:
                        state = json.loads(self._path.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        state = None
                if not state or state.get("meta", {}).get("version") != SEED_VERSION:
                    state = self._seed_factory()
                    self._state = state
                    self._write()
                else:
                    self._state = state
            return self._state

    # -- public API --------------------------------------------------------
    def read(self) -> dict[str, Any]:
        """Return the live state. Treat as read-only."""
        return self._ensure_loaded()

    def update(self, fn: Callable[[dict], Any]) -> Any:
        """Apply `fn(state)` under the lock and persist the result."""
        with self._lock:
            state = self._ensure_loaded()
            result = fn(state)
            self._write()
            return result

    def reset(self) -> None:
        """Discard all changes and regenerate the original demo data."""
        with self._lock:
            self._state = self._seed_factory()
            self._write()


    def randomize(self, seed: int) -> None:
        """Replace the sample data with a randomised variant. Drafts and proposed posts the user
        created (not the sample ones) are kept and re-numbered after the new records."""
        with self._lock:
            state = self._ensure_loaded()
            anchor = date.fromisoformat(state["meta"]["anchor_date"])
            keep = [p for p in state["posts"] if p["status"] in ("draft", "proposed") and p.get("source") != "sample"]
            new = build_seed(anchor, seed)
            nxt = 1 + max(int(p["id"].split("_")[1]) for p in new["posts"])
            for p in keep:
                p["id"] = f"post_{nxt:03d}"
                nxt += 1
                new["posts"].append(p)
            state.clear()
            state.update(new)
            self._write()


_store: JsonStore | None = None


def get_store() -> JsonStore:
    global _store
    if _store is None:
        _store = JsonStore(get_settings().state_file, lambda: build_seed(date.today()))
    return _store
