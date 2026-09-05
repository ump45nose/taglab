"""Minimal Navidrome-to-.trash worker. Standard library only."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import secrets
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import urlopen


LOG = logging.getLogger("delete_worker")


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def env_int(name: str, default: int, minimum: int, maximum: int | None = None) -> int:
    value = int(os.getenv(name, str(default)))
    if value < minimum or (maximum is not None and value > maximum):
        limit = f"{minimum}..{maximum}" if maximum is not None else f">= {minimum}"
        raise ValueError(f"{name} must be {limit}")
    return value


@dataclass(frozen=True)
class Config:
    media_path: Path
    navidrome_url: str
    navidrome_user: str
    navidrome_password: str
    delete_by_rating: bool
    max_rating: int
    delete_liked: bool
    dry_run: bool
    poll_interval: int

    @classmethod
    def from_env(cls) -> "Config":
        config = cls(
            media_path=Path(os.getenv("MEDIA_PATH", "/media")),
            navidrome_url=os.getenv("NAVIDROME_URL", "").rstrip("/"),
            navidrome_user=os.getenv("NAVIDROME_USER", ""),
            navidrome_password=os.getenv("NAVIDROME_PASSWORD", ""),
            delete_by_rating=env_bool("DELETE_BY_RATING"),
            max_rating=env_int("MAX_RATING", 1, 1, 5),
            delete_liked=env_bool("DELETE_LIKED"),
            dry_run=env_bool("DRY_RUN", True),
            poll_interval=env_int("POLL_INTERVAL", 300, 0),
        )
        if not config.navidrome_url or not config.navidrome_user or not config.navidrome_password:
            raise ValueError("NAVIDROME_URL, NAVIDROME_USER, and NAVIDROME_PASSWORD are required")
        if not config.media_path.is_dir():
            raise ValueError(f"MEDIA_PATH is not a directory: {config.media_path}")
        if not config.delete_by_rating and not config.delete_liked:
            LOG.warning("both deletion rules are disabled; nothing will be moved")
        return config


class Navidrome:
    def __init__(self, config: Config):
        self.base = config.navidrome_url
        self.user = config.navidrome_user
        self.password = config.navidrome_password

    def call(self, method: str, **params: object) -> dict:
        salt = secrets.token_hex(8)
        token = hashlib.md5((self.password + salt).encode(), usedforsecurity=False).hexdigest()
        query = urlencode({
            "u": self.user,
            "t": token,
            "s": salt,
            "c": "taglab-delete-worker",
            "v": "1.16.1",
            "f": "json",
            **params,
        })
        with urlopen(f"{self.base}/rest/{method}?{query}", timeout=30) as response:
            payload = json.load(response).get("subsonic-response", {})
        if payload.get("status") != "ok":
            error = payload.get("error", {})
            raise RuntimeError(f"Navidrome {method} failed: {error.get('message', payload.get('status'))}")
        return payload

    def all_songs(self) -> Iterable[dict]:
        offset = 0
        while True:
            payload = self.call("getAlbumList2", type="alphabeticalByName", size=500, offset=offset)
            albums = payload.get("albumList2", {}).get("album", [])
            for album in albums:
                album_payload = self.call("getAlbum", id=album["id"])
                yield from album_payload.get("album", {}).get("song", [])
            if len(albums) < 500:
                return
            offset += len(albums)

    def liked_songs(self) -> Iterable[dict]:
        payload = self.call("getStarred2")
        yield from payload.get("starred2", {}).get("song", [])


def select_candidates(config: Config, client: Navidrome) -> dict[str, set[str]]:
    candidates: dict[str, set[str]] = {}

    if config.delete_by_rating:
        for song in client.all_songs():
            rating = song.get("userRating")
            if isinstance(rating, int) and 1 <= rating <= config.max_rating:
                path = song.get("path")
                if path:
                    candidates.setdefault(path, set()).add(f"rating={rating}")

    if config.delete_liked:
        for song in client.liked_songs():
            path = song.get("path")
            if path:
                candidates.setdefault(path, set()).add("liked")

    return candidates


def safe_source(media_root: Path, reported_path: str) -> Path | None:
    relative = PurePosixPath(reported_path)
    if relative.is_absolute() or ".." in relative.parts or ".trash" in relative.parts:
        return None
    root = media_root.resolve()
    source = (root / Path(*relative.parts)).resolve()
    if not source.is_relative_to(root) or not source.is_file():
        return None
    return source


def trash_target(source: Path, media_root: Path) -> Path:
    root = media_root.resolve()
    target = root / ".trash" / source.relative_to(root)
    if not target.exists():
        return target
    counter = 1
    while True:
        candidate = target.with_name(f"{target.name}.{counter}")
        if not candidate.exists():
            return candidate
        counter += 1


def run_once(config: Config, client: Navidrome | None = None) -> tuple[int, int]:
    client = client or Navidrome(config)
    candidates = select_candidates(config, client)
    moved = 0
    skipped = 0

    for reported_path, reasons in sorted(candidates.items()):
        source = safe_source(config.media_path, reported_path)
        reason = ",".join(sorted(reasons))
        if source is None:
            skipped += 1
            LOG.warning("skip unsafe or missing path=%r reason=%s", reported_path, reason)
            continue
        target = trash_target(source, config.media_path)
        if config.dry_run:
            LOG.info("dry-run path=%s reason=%s target=%s", source, reason, target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        moved += 1
        LOG.info("moved path=%s reason=%s target=%s", source, reason, target)

    LOG.info("run complete candidates=%d moved=%d skipped=%d dry_run=%s", len(candidates), moved, skipped, config.dry_run)
    return moved, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="run once, ignoring POLL_INTERVAL")
    args = parser.parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")

    try:
        config = Config.from_env()
    except (TypeError, ValueError) as exc:
        LOG.error("configuration error: %s", exc)
        return 2

    while True:
        try:
            run_once(config)
        except Exception:
            LOG.exception("worker run failed")
            if args.once or config.poll_interval == 0:
                return 1
        if args.once or config.poll_interval == 0:
            return 0
        time.sleep(config.poll_interval)


if __name__ == "__main__":
    sys.exit(main())
