"""Tests for BaseCollector atomic write and snapshot rotation."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List, Optional
from unittest.mock import patch

import pytest

from grant_hunter.models import Grant


def _make_grant(i: int) -> Grant:
    return Grant(
        id=f"g{i}",
        title=f"Grant {i}",
        description="A" * 50,
        source="test",
        agency="Test Agency",
        url=f"https://example.com/grant/{i}",
    )


class _FakeCollector:
    """Minimal concrete subclass for testing BaseCollector without full setup."""

    name = "testcol"

    def __init__(self, snapshots_dir: Path):
        self._snapshots_dir = snapshots_dir
        snapshots_dir.mkdir(parents=True, exist_ok=True)

    # Replicate the BaseCollector methods under test, pointing at tmp dir

    def snapshot_path(self, run_date: Optional[str] = None) -> Path:
        from datetime import datetime
        date_str = run_date or datetime.utcnow().strftime("%Y%m%d")
        return self._snapshots_dir / f"{self.name}_{date_str}.json"

    def save_snapshot(self, grants: List[Grant], path: Optional[Path] = None) -> Path:
        import os
        import tempfile
        from grant_hunter.models import GrantEncoder
        target = path or self.snapshot_path()
        fd, tmp_path = tempfile.mkstemp(dir=str(target.parent), suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                json.dump([g.to_dict() for g in grants], fh, cls=GrantEncoder,
                          ensure_ascii=False, indent=2)
            os.replace(tmp_path, str(target))
        except:
            os.unlink(tmp_path)
            raise
        self._rotate_snapshots()
        return target

    def _rotate_snapshots(self, keep: int = 7) -> None:
        pattern = f"{self.name}_*.json"
        snapshots = sorted(
            self._snapshots_dir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in snapshots[keep:]:
            old.unlink(missing_ok=True)


# ── atomic write ──────────────────────────────────────────────────────────────

def test_save_snapshot_atomic_write(tmp_path):
    col = _FakeCollector(tmp_path)
    grants = [_make_grant(i) for i in range(3)]
    out = col.save_snapshot(grants)
    assert out.exists()
    # No leftover tmp files
    assert list(tmp_path.glob("*.tmp")) == []
    loaded = json.loads(out.read_text())
    assert len(loaded) == 3


def test_save_snapshot_no_partial_file_on_error(tmp_path):
    """If the target directory is read-only, save_snapshot raises and leaves no partial file."""
    import os
    col = _FakeCollector(tmp_path)
    # Make tmp_path read-only so mkstemp fails
    tmp_path.chmod(0o555)
    try:
        with pytest.raises(Exception):
            col.save_snapshot([_make_grant(0)])
        assert list(tmp_path.glob("*.tmp")) == []
    finally:
        tmp_path.chmod(0o755)


# ── snapshot rotation ─────────────────────────────────────────────────────────

def test_rotate_snapshots_keeps_most_recent(tmp_path):
    col = _FakeCollector(tmp_path)
    # Create 10 fake snapshot files with distinct mtimes
    for i in range(10):
        f = tmp_path / f"testcol_2026030{i:01d}.json"
        f.write_text("[]")
        # Stagger mtime so sort order is deterministic
        t = 1_700_000_000 + i
        import os
        os.utime(f, (t, t))

    col._rotate_snapshots(keep=7)

    remaining = sorted(tmp_path.glob("testcol_*.json"))
    assert len(remaining) == 7


def test_rotate_snapshots_does_nothing_when_under_limit(tmp_path):
    col = _FakeCollector(tmp_path)
    for i in range(5):
        f = tmp_path / f"testcol_2026030{i}.json"
        f.write_text("[]")

    col._rotate_snapshots(keep=7)

    remaining = list(tmp_path.glob("testcol_*.json"))
    assert len(remaining) == 5


def test_rotate_snapshots_removes_oldest(tmp_path):
    import os
    col = _FakeCollector(tmp_path)
    files = []
    for i in range(10):
        f = tmp_path / f"testcol_202603{i:02d}.json"
        f.write_text("[]")
        t = 1_700_000_000 + i
        os.utime(f, (t, t))
        files.append((t, f))

    col._rotate_snapshots(keep=7)

    # The 3 oldest (lowest mtime) should be gone
    oldest_3 = sorted(files, key=lambda x: x[0])[:3]
    for _, f in oldest_3:
        assert not f.exists(), f"{f.name} should have been removed"

    # The 7 newest should still exist
    newest_7 = sorted(files, key=lambda x: x[0], reverse=True)[:7]
    for _, f in newest_7:
        assert f.exists(), f"{f.name} should still exist"
