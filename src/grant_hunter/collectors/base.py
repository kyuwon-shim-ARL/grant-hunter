"""BaseCollector abstract class."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from grant_hunter.models import Grant, GrantEncoder
from grant_hunter.config import SNAPSHOTS_DIR

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    name: str = "base"

    def __init__(self):
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def collect(self) -> List[Grant]:
        """Fetch grants from the remote API. Must be implemented by subclasses."""
        ...

    # ------------------------------------------------------------------
    # Snapshot helpers
    # ------------------------------------------------------------------

    def snapshot_path(self, run_date: Optional[str] = None) -> Path:
        date_str = run_date or datetime.utcnow().strftime("%Y%m%d")
        return SNAPSHOTS_DIR / f"{self.name}_{date_str}.json"

    def save_snapshot(self, grants: List[Grant], path: Optional[Path] = None) -> Path:
        target = path or self.snapshot_path()
        fd, tmp_path = tempfile.mkstemp(dir=str(target.parent), suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                json.dump([g.to_dict() for g in grants], fh, cls=GrantEncoder, ensure_ascii=False, indent=2)
            os.replace(tmp_path, str(target))
        except:
            os.unlink(tmp_path)
            raise
        logger.info("[%s] Saved %d grants to %s", self.name, len(grants), target)
        self._rotate_snapshots()
        return target

    def _rotate_snapshots(self, keep: int = 7) -> None:
        """Remove old snapshots, keeping the most recent `keep` files."""
        pattern = f"{self.name}_*.json"
        snapshots = sorted(
            SNAPSHOTS_DIR.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in snapshots[keep:]:
            old.unlink(missing_ok=True)

    def load_previous_snapshot(self, path: Optional[Path] = None) -> List[Grant]:
        """Load the most recent snapshot that is NOT today's file."""
        if path and path.exists():
            return self._load_snapshot_file(path)

        # Find latest existing snapshot for this source
        pattern = f"{self.name}_*.json"
        today_str = datetime.utcnow().strftime("%Y%m%d")
        files = sorted(SNAPSHOTS_DIR.glob(pattern))
        # Exclude today's file (which we may have just written)
        older = [f for f in files if today_str not in f.name]
        if not older:
            return []
        return self._load_snapshot_file(older[-1])

    def _load_snapshot_file(self, path: Path) -> List[Grant]:
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            grants = [Grant.from_dict(d) for d in raw]
            logger.info("[%s] Loaded %d grants from %s", self.name, len(grants), path)
            return grants
        except Exception as exc:
            logger.error("[%s] Failed to load snapshot %s: %s", self.name, path, exc)
            return []

    def has_previous_snapshot(self) -> bool:
        pattern = f"{self.name}_*.json"
        today_str = datetime.utcnow().strftime("%Y%m%d")
        files = [f for f in SNAPSHOTS_DIR.glob(pattern) if today_str not in f.name]
        return len(files) > 0
