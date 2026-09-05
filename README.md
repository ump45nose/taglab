# TagLab Delete Worker

A deliberately small fork of [TagLab](https://github.com/cdeschenes/taglab).
It keeps only one job: read song state from Navidrome and safely move matching
music files to `.trash/` inside the mounted media library.

There is no web UI, database, metadata editor, ffmpeg, or application
framework. Runtime dependencies: Python's standard library only.

## Rules

- `DELETE_BY_RATING=true`: move songs with an **explicit** Navidrome rating
  from 1 through `MAX_RATING` (default `1`). Unrated songs do not match.
- `DELETE_LIKED=true`: move songs favorited/starred in Navidrome.

The switches are independent. A song matching both is moved once. Files are
never permanently deleted: `Artist/Album/song.flac` becomes
`.trash/Artist/Album/song.flac`. Name collisions get a numeric suffix.

## Run with Docker Compose

```bash
cp .env.example .env
# Set HOST_MEDIA_PATH and the NAVIDROME_* values.
# Set PUID/PGID to an account that can write HOST_MEDIA_PATH.
# Leave DRY_RUN=true for the first run and inspect docker compose logs.
docker compose up -d --build
```

Then set one or both rule switches to `true`. After the dry-run output looks
right, set `DRY_RUN=false` and recreate the container:

```bash
docker compose up -d --force-recreate
```

`POLL_INTERVAL` is seconds between runs; set it to `0` for a single run. The
Navidrome user must be able to see the complete target library. Its reported
song paths must refer to the same mounted library. Enable **Report Real Path**
for the `taglab-delete-worker` player in Navidrome; `NAVIDROME_MUSIC_PATH`
(default `/music`) is stripped before resolving the path under `MEDIA_PATH`.

## Run without Docker

```bash
MEDIA_PATH=/music \
NAVIDROME_URL=http://localhost:4533 \
NAVIDROME_USER=admin \
NAVIDROME_PASSWORD=secret \
DELETE_BY_RATING=true \
DRY_RUN=true \
python delete_worker.py --once
```

Use `python -m unittest -v` for the small smoke test suite.

## Safety behavior

- Dry-run defaults to on.
- Both deletion rules default to off.
- Unrated songs are excluded from the rating rule.
- Absolute paths, traversal paths, symlinks escaping the media root, missing
  files, and paths already under `.trash/` are skipped.
- API failures make one-shot mode fail; continuous mode logs and retries.

This fork retains the upstream project's MIT licensing declaration and gives
credit to the original project.
