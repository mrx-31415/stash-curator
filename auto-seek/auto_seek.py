#!/usr/bin/env python3
"""Auto Seek backend: finds where the action starts in each scene, on the server.

Stash runs this once per plugin operation, task and hook with the raw
interface: a JSON request on stdin ({"args": {"op": ...}}) and a JSON reply on
stdout ({"output": ...} or {"error": ...}). Only the standard library is used,
so the plugin needs nothing beyond the Python that Stash already runs plugins
with.

Scoring: Stash's own ffmpeg cuts frames as raw RGB, and a tuned CLIP image
model (int8 ONNX, CLIP's preprocessing inside the graph) scores each one
through ONNX Runtime's C API (``ort_api.py``). The search samples the scene at
the preview's segment times, scans the stretch where the score changes, and
bisects to the first frame past the threshold (see ``search``). Results are
kept per scene in ``data/cache.sqlite3``; the player reads them.

Files: the model and the ONNX Runtime build for this platform are downloaded
on first use into ``data/files``. The download runs in a detached child
process (``auto_seek.py <dir> download``) so the operation that starts it
returns at once. A lock file, refreshed while bytes arrive, keeps a second
download from starting; a lock that stops being refreshed counts as
abandoned. Partial files resume with HTTP Range requests, and every file is
checked against its pinned SHA-256 before it is used.

Background work: the "Find start points" task works through the library, and
a hook on new scenes queues them for a detached worker
(``auto_seek.py <dir> worker``), which runs one at a time at low priority.
"""

import base64
import contextlib
import glob
import hashlib
import json
import math
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ort_api

PLUGIN_ID = "auto-seek"
PLUGIN_DIR = os.path.realpath(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(__file__))
DATA_DIR = os.path.join(PLUGIN_DIR, "data")
FILES_DIR = os.path.join(DATA_DIR, "files")
STATE_PATH = os.path.join(DATA_DIR, "download.json")
LOCK_PATH = os.path.join(DATA_DIR, "download.lock")
VERIFIED_PATH = os.path.join(DATA_DIR, "verified.json")
CACHE_PATH = os.path.join(DATA_DIR, "cache.sqlite3")
WORKER_LOCK_PATH = os.path.join(DATA_DIR, "worker.lock")

# The model: CLIP ViT-B/32 (LAION-2B) with its last three blocks tuned on
# start points and acts, int8 weights, raw RGB bytes in. Pinned to a commit of
# https://huggingface.co/mrx-31415/auto-seek.
MODEL = {
    "path": "models/auto-seek-clip3-v1.onnx",
    "url": "https://huggingface.co/mrx-31415/auto-seek/resolve/"
    "545c2c0a146c18c2279e33186f9074783d140aaa/auto-seek-clip3-v1.onnx",
    "sha256": "94e1ecd4a67c2dffc64860d9ca19773d941b33c055804b91d027e31993ab230d",
    "size": 88661598,
}
# Part of every cached result: a new model or rule recomputes older results.
MODEL_ID = "clip3-v1+t60"
ACTS = ("ballerina", "cowgirl", "fingering", "from behind", "handjob",
        "missionary", "oral on her", "oral on him", "side/spoon", "titjob")  # fmt: skip

# ONNX Runtime per platform: Microsoft's release builds, and for musl (Stash's
# Docker image is Alpine) Alpine's own build with the libraries it needs. Only
# the files named in "members" are kept, under "path".
ORT = "https://github.com/microsoft/onnxruntime/releases/download/v1.31.1/"
MUSL = "https://github.com/mrx-31415/stash-curator/releases/download/auto-seek-runtime-v1/"
RUNTIMES = {
    "linux-x64-glibc": {
        "path": "runtime/ort-1.31.1-linux-x64",
        "url": ORT + "onnxruntime-linux-x64-1.31.1.tgz",
        "sha256": "c849e36a1ef3e22d4ff217b9d1ce4a3cf5b9467b975610913ae959ad5b16bdc9",
        "size": 11413655,
        "members": {
            "onnxruntime-linux-x64-1.31.1/lib/libonnxruntime.so.1.31.1": "libonnxruntime.so",
            "onnxruntime-linux-x64-1.31.1/LICENSE": "LICENSE",
            "onnxruntime-linux-x64-1.31.1/ThirdPartyNotices.txt": "ThirdPartyNotices.txt",
        },
        "library": "libonnxruntime.so",
    },
    "linux-arm64-glibc": {
        "path": "runtime/ort-1.31.1-linux-arm64",
        "url": ORT + "onnxruntime-linux-aarch64-1.31.1.tgz",
        "sha256": "5317505e2da99be65f8e2775ba3c2afd6d2961fd78aba1bd8f56159f48820c78",
        "size": 10332381,
        "members": {
            "onnxruntime-linux-aarch64-1.31.1/lib/libonnxruntime.so.1.31.1": "libonnxruntime.so",
            "onnxruntime-linux-aarch64-1.31.1/LICENSE": "LICENSE",
            "onnxruntime-linux-aarch64-1.31.1/ThirdPartyNotices.txt": "ThirdPartyNotices.txt",
        },
        "library": "libonnxruntime.so",
    },
    "macos-arm64": {
        "path": "runtime/ort-1.31.1-macos-arm64",
        "url": ORT + "onnxruntime-osx-arm64-1.31.1.tgz",
        "sha256": "2e1344a1926ee50eb25b38153cb6992c3567515aef0e677a1a520a1798896d6f",
        "size": 36936435,
        "members": {
            "onnxruntime-osx-arm64-1.31.1/lib/libonnxruntime.1.31.1.dylib": "libonnxruntime.dylib",
            "onnxruntime-osx-arm64-1.31.1/LICENSE": "LICENSE",
            "onnxruntime-osx-arm64-1.31.1/ThirdPartyNotices.txt": "ThirdPartyNotices.txt",
        },
        "library": "libonnxruntime.dylib",
    },
    "windows-x64": {
        "path": "runtime/ort-1.31.1-windows-x64",
        "url": ORT + "onnxruntime-win-x64-1.31.1.zip",
        "sha256": "5869e26bb25314375f2d5ef1877e3ea06b1543d6c710e6e4a1ec2f7177ab4b2c",
        "size": 82929944,
        "members": {
            "onnxruntime-win-x64-1.31.1/lib/onnxruntime.dll": "onnxruntime.dll",
            "onnxruntime-win-x64-1.31.1/LICENSE": "LICENSE",
            "onnxruntime-win-x64-1.31.1/ThirdPartyNotices.txt": "ThirdPartyNotices.txt",
        },
        "library": "onnxruntime.dll",
    },
    "windows-arm64": {
        "path": "runtime/ort-1.31.1-windows-arm64",
        "url": ORT + "onnxruntime-win-arm64-1.31.1.zip",
        "sha256": "817f4129073f84f81cde3ff92b1a4e06d007691e7208deed08a8b6d6df143f7f",
        "size": 85851069,
        "members": {
            "onnxruntime-win-arm64-1.31.1/lib/onnxruntime.dll": "onnxruntime.dll",
            "onnxruntime-win-arm64-1.31.1/LICENSE": "LICENSE",
            "onnxruntime-win-arm64-1.31.1/ThirdPartyNotices.txt": "ThirdPartyNotices.txt",
        },
        "library": "onnxruntime.dll",
    },
    # Built by scripts/build_auto_seek_runtime.sh (Alpine 3.23, ONNX Runtime 1.23).
    "linux-x64-musl": {
        "path": "runtime/ort-alpine-3.23-x64",
        "url": MUSL + "onnxruntime-alpine-3.23-x86_64.tar.gz",
        "sha256": "0534728cbec0ee55f04a57487b362c70f132951d9cc3d93b1ab4cb46ff5a3dd5",
        "size": 8956690,
        "members": "*",
        "library": "libonnxruntime.so",
    },
    "linux-arm64-musl": {
        "path": "runtime/ort-alpine-3.23-arm64",
        "url": MUSL + "onnxruntime-alpine-3.23-aarch64.tar.gz",
        "sha256": "1d1f351097f96aae6b3e8e0e8ed04500830cda45529addcbb5b5eb5b2227287c",
        "size": 7904545,
        "members": "*",
        "library": "libonnxruntime.so",
    },
    "linux-armv7-musl": {
        "path": "runtime/ort-alpine-3.23-armv7",
        "url": MUSL + "onnxruntime-alpine-3.23-armv7.tar.gz",
        "sha256": "99fdc41382c08f5afeb9f067d2e236fe435103366bc8b9d23233f4793ee8f297",
        "size": 7822880,
        "members": "*",
        "library": "libonnxruntime.so",
    },
}


def platform_key() -> str | None:
    """Which ONNX Runtime build runs here, or None if there is none."""
    arch = {
        "x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64",
        "armv7l": "armv7", "armv7": "armv7",
    }.get(platform.machine().lower())  # fmt: skip
    if sys.platform.startswith("linux"):
        musl = bool(glob.glob("/lib/ld-musl-*")) or platform.libc_ver()[0] != "glibc"
        key = f"linux-{arch}-{'musl' if musl else 'glibc'}"
    elif sys.platform == "win32":
        key = f"windows-{arch}"
    elif sys.platform == "darwin":
        key = f"macos-{arch}"
    else:
        return None
    return key if arch and key in RUNTIMES else None


def files_needed() -> tuple[dict, ...]:
    key = platform_key()
    return (MODEL, RUNTIMES[key]) if key in RUNTIMES else (MODEL,)


FILES = files_needed()

LOCK_STALE_SECONDS = 120
CHUNK = 1 << 20


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as source:
            return json.load(source)
    except (OSError, ValueError):
        return default


def write_json(path: str, value) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.{os.getpid()}.tmp"
    with open(temporary, "w", encoding="utf-8") as out:
        json.dump(value, out)
    os.replace(temporary, path)


# ── download ──────────────────────────────────────────────────────────────


def target_of(entry: dict) -> str:
    """The file a download provides: the model itself, or the library
    unpacked from a runtime archive."""
    if "members" in entry:
        return os.path.join(FILES_DIR, entry["path"], entry["library"])
    return os.path.join(FILES_DIR, entry["path"])


def file_ready(entry: dict, verified: dict) -> bool:
    """A file counts as ready when it is in place (with the pinned size, for a
    plain file) and was hashed once after download (hashing 89 MB on every
    status call would cost more than the call itself)."""
    target = target_of(entry)
    return (
        verified.get(entry["path"]) == entry["sha256"]
        and os.path.isfile(target)
        and ("members" in entry or os.path.getsize(target) == entry["size"])
    )


def lock_alive() -> bool:
    try:
        return time.time() - os.path.getmtime(LOCK_PATH) < LOCK_STALE_SECONDS
    except OSError:
        return False


def status() -> dict:
    verified = read_json(VERIFIED_PATH, {})
    missing = [entry for entry in FILES if not file_ready(entry, verified)]
    state = read_json(STATE_PATH, {})
    downloading = bool(missing) and lock_alive()
    total = sum(entry["size"] for entry in FILES)
    done = total - sum(entry["size"] for entry in missing)
    if downloading:
        done += int(state.get("received", 0))
    return {
        "supported": platform_key() in RUNTIMES,
        "platform": platform_key() or f"{sys.platform}-{platform.machine()}",
        "ready": not missing and platform_key() in RUNTIMES,
        "downloading": downloading,
        "received": min(done, total),
        "total": total,
        "error": None if downloading or not missing else state.get("error"),
        "files": {entry["path"]: entry["sha256"][:12] for entry in FILES},
    }


def ensure() -> dict:
    """Start the background download unless everything is present or a
    download is already running. Returns at once."""
    current = status()
    if current["ready"] or current["downloading"] or not current["supported"]:
        return current
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOCK_PATH, "w", encoding="utf-8") as lock:
        lock.write(str(os.getpid()))
    write_json(STATE_PATH, {"state": "starting", "received": 0, "updated_at": now()})
    arguments = [sys.executable, os.path.abspath(__file__), PLUGIN_DIR, "download"]
    options: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        options["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    subprocess.Popen(arguments, **options)
    return {**status(), "downloading": True}


def fetch(entry: dict, progress) -> None:
    """Download one file, resuming a partial copy, verify its hash, and put it
    in place (unpacking the wanted members of an archive)."""
    archive = "members" in entry
    target = os.path.join(FILES_DIR, entry["path"])
    if archive:
        partial = os.path.join(FILES_DIR, "downloads", os.path.basename(entry["url"]) + ".part")
    else:
        partial = target + ".part"
    os.makedirs(os.path.dirname(partial), exist_ok=True)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    offset = os.path.getsize(partial) if os.path.isfile(partial) else 0
    if offset > entry["size"]:
        os.remove(partial)
        offset = 0
    if offset < entry["size"]:
        request = urllib.request.Request(entry["url"], headers={"User-Agent": "stash-auto-seek"})
        if offset:
            request.add_header("Range", f"bytes={offset}-")
        with urllib.request.urlopen(request, timeout=60) as response:
            if offset and response.status != 206:
                offset = 0  # the server ignored the range; start over
            with open(partial, "ab" if offset else "wb") as out:
                received = offset
                while chunk := response.read(CHUNK):
                    out.write(chunk)
                    received += len(chunk)
                    progress(received)
    digest = hashlib.sha256()
    with open(partial, "rb") as source:
        while block := source.read(CHUNK):
            digest.update(block)
    if digest.hexdigest() != entry["sha256"]:
        os.remove(partial)
        raise ValueError(f"{entry['path']} failed its checksum; it will be fetched again")
    if archive:
        unpack(entry, partial)
        os.remove(partial)
    else:
        os.replace(partial, target)


def unpack(entry: dict, archive: str) -> None:
    """Copy the archive members the entry names (all regular files, flattened,
    for "*") into its folder, replacing an older copy as a whole."""
    target = os.path.join(FILES_DIR, entry["path"])
    staging = target + ".tmp"
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    wanted = entry["members"]

    def keep(name: str) -> str | None:
        if wanted == "*":
            base = os.path.basename(name)
            return base if base and not base.startswith(".") else None
        return wanted.get(name)

    def write(name: str, source) -> None:
        with open(os.path.join(staging, name), "wb") as out:
            shutil.copyfileobj(source, out, CHUNK)

    if archive.endswith(".zip.part") or zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                name = keep(info.filename)
                if name and not info.is_dir():
                    with bundle.open(info) as source:
                        write(name, source)
    else:
        with tarfile.open(archive, "r:*") as bundle:
            for member in bundle.getmembers():
                name = keep(member.name)
                if name and member.isfile():
                    write(name, bundle.extractfile(member))
    missing = [
        name
        for name in ([entry["library"]] if wanted == "*" else wanted.values())
        if not os.path.isfile(os.path.join(staging, name))
    ]
    if missing:
        shutil.rmtree(staging, ignore_errors=True)
        raise ValueError(f"{os.path.basename(entry['url'])} lacks {', '.join(missing)}")
    shutil.rmtree(target, ignore_errors=True)
    os.replace(staging, target)


def download() -> None:
    verified = read_json(VERIFIED_PATH, {})
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOCK_PATH, "a", encoding="utf-8"):
        pass  # refreshed while bytes arrive; ensure() normally made it already
    try:
        for entry in FILES:
            if file_ready(entry, verified):
                continue
            last = 0.0

            def progress(received: int, path: str = entry["path"]) -> None:
                nonlocal last
                if time.time() - last >= 1:
                    last = time.time()
                    write_json(
                        STATE_PATH,
                        {
                            "state": "downloading",
                            "file": path,
                            "received": received,
                            "updated_at": now(),
                        },
                    )
                    os.utime(LOCK_PATH)

            progress(0)
            fetch(entry, progress)
            verified[entry["path"]] = entry["sha256"]
            write_json(VERIFIED_PATH, verified)
        write_json(STATE_PATH, {"state": "ready", "received": 0, "updated_at": now()})
    except Exception as error:  # reported to the UI through status()
        write_json(
            STATE_PATH, {"state": "error", "error": str(error), "received": 0, "updated_at": now()}
        )
    finally:
        with contextlib.suppress(OSError):
            os.remove(LOCK_PATH)


# ── start-point cache ─────────────────────────────────────────────────────


def cache() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    connection = sqlite3.connect(CACHE_PATH, timeout=10)
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version < 1:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS start_point (
                scene_id TEXT PRIMARY KEY,
                start_s REAL NOT NULL,
                duration_s REAL NOT NULL,
                model TEXT NOT NULL,
                scores TEXT NOT NULL DEFAULT '[]',
                computed_at TEXT NOT NULL
            );
            PRAGMA user_version = 1;
            """
        )
    if version < 2:
        # Starts the viewer marked by hand. Kept apart from the computed ones,
        # which a new model replaces, and preferred over them; together with
        # the computed start at the time they are labels for a better model.
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS user_start (
                scene_id TEXT PRIMARY KEY,
                start_s REAL NOT NULL,
                duration_s REAL NOT NULL,
                computed_start_s REAL,
                computed_model TEXT,
                marked_at TEXT NOT NULL
            );
            PRAGMA user_version = 2;
            """
        )
    if version < 3:
        # Scenes the analysis failed on, so the library task doesn't retry them
        # with the same model on every run; and new scenes waiting for the
        # background worker.
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS failure (
                scene_id TEXT PRIMARY KEY,
                model TEXT NOT NULL,
                error TEXT NOT NULL,
                failed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pending (
                scene_id TEXT PRIMARY KEY,
                added_at TEXT NOT NULL
            );
            PRAGMA user_version = 3;
            """
        )
    return connection


def chart(scores: str) -> dict:
    """The frames behind a start point, for the player's chart: [time, score]
    pairs and the threshold they were judged against. Results saved before
    times were kept (bare scores) have none."""
    try:
        samples = [pair for pair in json.loads(scores or "[]") if isinstance(pair, list)]
    except ValueError:
        samples = []
    return {"samples": samples, "threshold": RULE["threshold"]} if samples else {}


def get_points(args: dict) -> dict:
    ids = [str(value) for value in args.get("scene_ids") or []][:500]
    if not ids or not os.path.isfile(CACHE_PATH):
        return {}
    marks = ",".join("?" * len(ids))
    with contextlib.closing(cache()) as connection:
        rows = connection.execute(
            "SELECT scene_id, start_s, duration_s, model, computed_at, scores FROM start_point "
            f"WHERE scene_id IN ({marks})",
            ids,
        ).fetchall()
        marked = connection.execute(
            "SELECT scene_id, start_s, duration_s, marked_at FROM user_start "
            f"WHERE scene_id IN ({marks})",
            ids,
        ).fetchall()
    points = {
        scene_id: {
            "start": start,
            "duration": duration,
            "model": model,
            "computed_at": computed_at,
            **chart(scores),
        }
        for scene_id, start, duration, model, computed_at, scores in rows
    }
    # A start the viewer marked wins over a computed one, whatever the model.
    for scene_id, start, duration, marked_at in marked:
        points[scene_id] = {
            **points.get(scene_id, {}),
            "start": start,
            "duration": duration,
            "model": "user",
            "computed_at": marked_at,
        }
    return points


def put_point(args: dict) -> dict:
    scene_id = str(args["scene_id"])
    start = float(args["start"])
    duration = float(args["duration"])
    if not 0 <= start <= duration:
        raise ValueError("start must lie within the scene")
    # Every frame the search looked at, as [time, score]: the player draws them.
    scores = json.dumps(
        [[round(float(t), 2), round(float(p), 4)] for t, p in args.get("scores") or []][:200]
    )
    with contextlib.closing(cache()) as connection, connection:
        connection.execute(
            "INSERT INTO start_point (scene_id, start_s, duration_s, model, scores, computed_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(scene_id) DO UPDATE SET "
            "start_s = excluded.start_s, duration_s = excluded.duration_s, model = excluded.model, "
            "scores = excluded.scores, computed_at = excluded.computed_at",
            (scene_id, start, duration, str(args.get("model") or ""), scores, now()),
        )
    return {"scene_id": scene_id, "start": start}


# ── frames ────────────────────────────────────────────────────────────────

FRAMES_PER_RUN = 3
FRAME_TIMEOUT_SECONDS = 30
# ffmpeg runs allowed at once across every operation on this server. Each
# input holds a decoder: about 60 MB at 1080p with one thread, twice that with
# ffmpeg's default thread count. Unbounded, a burst of requests can exhaust
# a NAS's memory and take Stash down with it.
FFMPEG_SLOTS = 4
SLOT_WAIT_SECONDS = 60
SCENE_QUERY = """
query AutoSeekScene($id: ID!) {
  findScene(id: $id) { files { path duration } }
  configuration {
    general { ffmpegPath previewSegments previewExcludeStart previewExcludeEnd }
    plugins(include: ["auto-seek"])
  }
}
"""


def stash_query(server: dict, query: str, variables: dict) -> dict:
    """One GraphQL call back to the Stash that started this process."""
    host = server.get("Host") or "127.0.0.1"
    if host == "0.0.0.0":
        host = "127.0.0.1"
    url = f"{server.get('Scheme') or 'http'}://{host}:{server.get('Port') or 9999}/graphql"
    request = urllib.request.Request(
        url,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Content-Type": "application/json"},
    )
    cookie = server.get("SessionCookie") or {}
    if cookie.get("Name") and cookie.get("Value"):
        request.add_header("Cookie", f"{cookie['Name']}={cookie['Value']}")
    # Stash passes its own proxy settings to plugins; a call to itself must
    # not go through them.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise ValueError(payload["errors"][0].get("message") or "Stash query failed")
    return payload["data"]


def find_ffmpeg(configured: str, server: dict) -> str:
    """Stash's configured ffmpeg, else the one on PATH, else the copy Stash
    downloads into its config folder."""
    candidates = [configured, shutil.which("ffmpeg")]
    if server.get("Dir"):
        name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        candidates.append(os.path.join(server["Dir"], name))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    raise ValueError("ffmpeg was not found")


def try_lock(handle) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


@contextlib.contextmanager
def ffmpeg_slot():
    """Hold one of FFMPEG_SLOTS lock files while ffmpeg runs. The operating
    system drops the lock when the holder exits, even if it crashes."""
    os.makedirs(DATA_DIR, exist_ok=True)
    deadline = time.monotonic() + SLOT_WAIT_SECONDS
    while True:
        for slot in range(FFMPEG_SLOTS):
            handle = open(os.path.join(DATA_DIR, f"ffmpeg-{slot}.lock"), "a+b")  # noqa: SIM115
            if try_lock(handle):
                try:
                    yield
                finally:
                    handle.close()  # closing releases the lock
                return
            handle.close()
        if time.monotonic() > deadline:
            raise TimeoutError("The server is busy cutting frames; try again shortly")
        time.sleep(0.05)


def grab_frames(ffmpeg: str, path: str, times: list[float]) -> list[bytes | None]:
    """The frames at `times` as the model takes them: short side scaled to
    224, centre square, raw RGB. One ffmpeg run, one input per time, each
    seeking on its own; None where the video has no frame. A time past the end
    fails only its own output, so every file is read on its own and the exit
    status is not trusted."""
    size = ort_api.FRAME_SIZE
    with tempfile.TemporaryDirectory(prefix="auto-seek-") as folder:
        inputs: list[str] = []
        outputs: list[str] = []
        for i, time_s in enumerate(times):
            inputs += ["-threads", "1", "-ss", f"{time_s:.3f}", "-i", path]
            outputs += [
                "-map", f"{i}:v:0", "-frames:v", "1", "-an", "-sn",
                "-vf", f"scale={size}:{size}:force_original_aspect_ratio=increase,"
                f"crop={size}:{size}",
                "-pix_fmt", "rgb24", "-f", "rawvideo", os.path.join(folder, f"{i}.rgb"),
            ]  # fmt: skip
        command = [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *inputs,
            *outputs,
        ]
        with ffmpeg_slot(), contextlib.suppress(subprocess.TimeoutExpired):
            subprocess.run(command, capture_output=True, timeout=FRAME_TIMEOUT_SECONDS, check=False)
        frames: list[bytes | None] = []
        for i in range(len(times)):
            try:
                with open(os.path.join(folder, f"{i}.rgb"), "rb") as image:
                    data = image.read()
            except OSError:
                data = b""
            frames.append(data if len(data) == ort_api.FRAME_BYTES else None)
        return frames


def frame_preview(args: dict, server: dict) -> dict:
    """One exact frame as a small JPEG, for the strip's hover preview."""
    scene_id = str(int(args["scene_id"]))
    time_s = max(0.0, float(args["time"]))
    data = stash_query(server, SCENE_QUERY, {"id": scene_id})
    files = (data.get("findScene") or {}).get("files") or []
    if not files:
        raise ValueError("This scene has no video file")
    general = data["configuration"].get("general") or {}
    ffmpeg = find_ffmpeg(general.get("ffmpegPath") or "", server)
    with tempfile.TemporaryDirectory(prefix="auto-seek-") as folder:
        out = os.path.join(folder, "frame.jpg")
        command = [
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-threads", "1", "-ss", f"{time_s:.3f}", "-i", files[0]["path"],
            "-frames:v", "1", "-an", "-sn", "-vf", "scale=320:-2", "-q:v", "5", out,
        ]  # fmt: skip
        with ffmpeg_slot(), contextlib.suppress(subprocess.TimeoutExpired):
            subprocess.run(command, capture_output=True, timeout=FRAME_TIMEOUT_SECONDS, check=False)
        try:
            with open(out, "rb") as image:
                return {"time": time_s, "jpeg": base64.b64encode(image.read()).decode()}
        except OSError:
            return {"time": time_s, "jpeg": None}


def blank(pixels: bytes) -> bool:
    """A grab whose RGB values barely vary (all black, or one flat colour)
    says nothing about the scene. Every 16th pixel is enough."""
    sample = pixels[0::48] + pixels[1::48] + pixels[2::48]
    return max(sample) - min(sample) < 12


# ── the search ────────────────────────────────────────────────────────────

# Tuned on hand-checked start points with the real search below (196 scenes:
# 77% within 60 s of the viewer's start).
RULE = {
    "threshold": 0.6,  # a frame at or above this counts as started
    "window_low": 0.5,  # the scan widens back over coarse frames this likely
    # A "maybe" frame just before the jump: the start may lie before it, so the
    # scan starts one sample earlier (+2 points on the checked scenes, 4 won,
    # 0 lost, under half a frame more per scene).
    "maybe": 0.3,
    "window_high": 0.8,  # ...and forward over ones not yet this sure
    "scan_min_step_s": 15,
    "scan_max_frames": 8,
    "coarse_sure": 0.95,  # the coarse pass ends after a run of frames this sure
    "coarse_sure_run": 2,
    "refine_depth": 3,  # bisection rounds between the last miss and first hit
}
EMPTY_FRAMES = "Too many frames of this scene came out blank to analyse it"


def parse_exclude(value, duration: float) -> float:
    """Stash's preview exclusions are seconds ("12") or a share ("5%")."""
    text = str(value if value is not None else "0").strip()
    try:
        number = float(text.rstrip("%") or 0)
    except ValueError:
        number = 0.0
    return duration * number / 100 if text.endswith("%") else number


def coarse_times(duration: float, config: dict) -> list[float]:
    """Where Stash's preview samples the scene: its segments, spaced evenly
    between the exclusions."""
    segments = max(1, int(config.get("previewSegments") or 12))
    start = parse_exclude(config.get("previewExcludeStart"), duration)
    end = parse_exclude(config.get("previewExcludeEnd"), duration)
    step = max(0.0, duration - start - end) / segments
    return [start + i * step for i in range(segments)]


def change_point(probs: list[float]) -> int:
    """The split that best separates "not started" from "started": the index
    that maximises the log-likelihood of all earlier frames being intro and
    all later ones action."""
    clipped = [min(1 - 1e-4, max(1e-4, p)) for p in probs]
    best, best_score = 0, -math.inf
    for i in range(len(clipped)):
        score = sum(math.log(1 - p) if j < i else math.log(p) for j, p in enumerate(clipped))
        if score > best_score:
            best, best_score = i, score
    return best


def scan_window(times: list[float], probs: list[float], rule: dict) -> tuple[float, float]:
    """The stretch to scan: from the change point, widened backwards over
    frames that already look likely and forwards over ones not yet sure."""
    index = change_point(probs)
    low = index - 1
    while low > 0 and probs[low - 1] >= rule["window_low"]:
        low -= 1
    if low > 0 and probs[low] >= rule.get("maybe", 1.0):
        low -= 1
    high = index
    while high < len(probs) - 1 and probs[high] < rule["window_high"]:
        high += 1
    return times[max(low, 0)], times[high]


def scan_times(start: float, end: float, rule: dict) -> list[float]:
    if not end > start:
        return [end]
    step = max(rule["scan_min_step_s"], (end - start) / rule["scan_max_frames"])
    times, t = [], start
    while t <= end + 1e-6 and len(times) <= rule["scan_max_frames"]:
        times.append(t)
        t += step
    return times


def bisect_times(miss: float, hit: float, depth: int) -> list[float]:
    """The points a bisection `depth` rounds deep could visit between a frame
    below the threshold and the next above it; none when they are close."""
    if hit - miss < 8:
        return []
    parts = 2**depth
    return [miss + (hit - miss) * (i + 1) / parts for i in range(parts - 1)]


def search(
    score_at, duration: float, config: dict, rule: dict = RULE, eager: bool = False
) -> tuple[float, list[tuple[float, float]]]:
    """The start point, and every frame it looked at as (time, score). `score_at(times)` cuts
    and scores frames, returning None for a blank one; it is called in time
    order with small batches, so the search can stop early. `eager` asks for
    each pass's frames all at once instead, so they can be cut in parallel:
    the same answer, sooner, for a few more frames' work."""
    seen: list[tuple[float, float]] = []

    def frames(times: list[float]):
        if eager:
            yield from zip(times, score_at(times), strict=True)
            return
        for i in range(0, len(times), FRAMES_PER_RUN):
            batch = times[i : i + FRAMES_PER_RUN]
            yield from zip(batch, score_at(batch), strict=True)

    # Coarse pass: once a few frames in a row are clearly past the start, the
    # later ones can't move the answer.
    coarse_t: list[float] = []
    coarse: list[float] = []
    looked = sure = 0
    for t, score in frames(coarse_times(duration, config)):
        looked += 1
        if score is not None:
            coarse_t.append(t)
            coarse.append(score)
        sure = sure + 1 if score is not None and score >= rule["coarse_sure"] else 0
        if sure >= rule["coarse_sure_run"]:
            break
    # With too many blank grabs the answer would come from position alone.
    if len(coarse) * 2 < looked:
        raise ValueError(EMPTY_FRAMES)
    seen += list(zip(coarse_t, coarse, strict=True))
    # Fine pass over the window, in time order, stopping at the first hit.
    low, high = scan_window(coarse_t, coarse, rule)
    start, last_miss = high, None
    found = False
    for t, score in frames(scan_times(low, high, rule)):
        if score is None:
            continue
        seen.append((t, score))
        if score >= rule["threshold"]:
            start, found = t, True
            break
        last_miss = t
    # The start lies between the last miss and the first hit: bisect the gap.
    if found and last_miss is not None:
        points = bisect_times(last_miss, start, rule["refine_depth"])
        known = dict(zip(points, score_at(points), strict=True)) if eager and points else {}
        low_i, high_i = 0, len(points) - 1
        while low_i <= high_i:
            middle = (low_i + high_i) // 2
            point = points[middle]
            score = known[point] if point in known else score_at([point])[0]
            if score is not None:
                seen.append((point, score))
            if score is not None and score >= rule["threshold"]:
                start = point
                high_i = middle - 1
            else:
                low_i = middle + 1
    return start, seen


# ── analysis ──────────────────────────────────────────────────────────────

_scorer: dict = {}
LOAD_TIMES: dict = {}  # how long the model took to load in this process


def model_bytes() -> bytes:
    """The model, from a copy in the system's temporary folder when there is
    one. Plugin folders often sit on a network share (Stash's config volume on
    a NAS), where reading 89 MB took 9 s against a fraction of a second from
    local disk, and every player request is a new process that reads it again."""
    local = os.path.join(tempfile.gettempdir(), "auto-seek", MODEL["sha256"][:16] + ".onnx")
    with contextlib.suppress(OSError):
        if os.path.getsize(local) == MODEL["size"]:
            with open(local, "rb") as source:
                return source.read()
    with open(target_of(MODEL), "rb") as source:
        model = source.read()
    with contextlib.suppress(OSError):  # no local copy: read from the share next time too
        os.makedirs(os.path.dirname(local), mode=0o700, exist_ok=True)
        temporary = f"{local}.{os.getpid()}.tmp"
        with open(temporary, "wb") as out:
            out.write(model)
        os.replace(temporary, local)
    return model


def scorer(threads: int) -> ort_api.Session:
    """The model, loaded once per process."""
    if threads not in _scorer:
        started = time.monotonic()
        verified = read_json(VERIFIED_PATH, {})
        runtime = RUNTIMES.get(platform_key() or "")
        if runtime is None:
            raise ValueError(
                f"Auto Seek can't run on this server ({sys.platform}, {platform.machine()})"
            )
        if not all(file_ready(entry, verified) for entry in (MODEL, runtime)):
            ensure()
            raise ValueError("The model is still downloading on the server")
        model = model_bytes()
        read = time.monotonic()
        _scorer.clear()
        _scorer[threads] = ort_api.Session(target_of(runtime), model, threads, len(ACTS))
        LOAD_TIMES.update(read=read - started, session=time.monotonic() - read)
    return _scorer[threads]


def plugin_settings(config: dict) -> dict:
    return (config.get("plugins") or {}).get(PLUGIN_ID) or {}


def threads_setting(settings: dict) -> int:
    try:
        return max(1, min(16, int(settings.get("threads") or 2)))
    except (TypeError, ValueError):
        return 2


def analyse_scene(scene_id: str, server: dict, eager: bool = False) -> dict:
    """Find the start of one scene and cache it. `eager` (someone is waiting
    for it) cuts each pass's frames in parallel."""
    started = time.monotonic()
    data = stash_query(server, SCENE_QUERY, {"id": scene_id})
    queried = time.monotonic()
    files = (data.get("findScene") or {}).get("files") or []
    if not files or not files[0].get("duration"):
        raise ValueError("This scene has no video file")
    path, duration = files[0]["path"], float(files[0]["duration"])
    config = data["configuration"]
    general = config.get("general") or {}
    session = scorer(threads_setting(plugin_settings(config)))
    ffmpeg = find_ffmpeg(general.get("ffmpegPath") or "", server)
    timings = {"cut": 0.0, "score": 0.0}
    live: list[list[float]] = []

    def score_at(times: list[float]) -> list[float | None]:
        t0 = time.monotonic()
        groups = [times[i : i + FRAMES_PER_RUN] for i in range(0, len(times), FRAMES_PER_RUN)]
        if len(groups) > 1:
            with ThreadPoolExecutor(min(FFMPEG_SLOTS, len(groups))) as pool:
                batches = pool.map(lambda group: grab_frames(ffmpeg, path, group), groups)
                grabs = [frame for batch in batches for frame in batch]
        else:
            grabs = grab_frames(ffmpeg, path, times)
        t1 = time.monotonic()
        out: list[float | None] = []
        for t, pixels in zip(times, grabs, strict=True):
            score = None
            if pixels is not None and not blank(pixels):
                score = session.score(pixels, [t / duration, t / 60, duration / 3600])[0]
                live.append([round(t, 2), round(score, 4)])
                if eager:  # someone is watching the strip fill in
                    write_progress(scene_id, duration, live)
            out.append(score)
        timings["cut"] += t1 - t0
        timings["score"] += time.monotonic() - t1
        return out

    try:
        start, scores = search(score_at, duration, general, eager=eager)
    finally:
        with contextlib.suppress(OSError):
            os.remove(progress_path(scene_id))
    put_point(
        {
            "scene_id": scene_id,
            "start": start,
            "duration": duration,
            "model": MODEL_ID,
            # Every frame scored, including ones cut in a batch that the
            # search ended up not needing: the player shows them all, and the
            # live view it drew while waiting must not lose bars afterwards.
            "scores": [(t, p) for t, p in live],
        }
    )
    with contextlib.closing(cache()) as connection, connection:
        connection.execute("DELETE FROM failure WHERE scene_id = ?", (scene_id,))
    return {
        "start": start,
        "duration": duration,
        "model": MODEL_ID,
        "frames": len(scores),
        "samples": live,
        "threshold": RULE["threshold"],
        "timings_ms": {
            key: round(value * 1000)
            for key, value in (timings | {"query": queried - started} | LOAD_TIMES).items()
        }
        | {"total": round((time.monotonic() - started) * 1000)},
    }


def progress_path(scene_id: str) -> str:
    return os.path.join(DATA_DIR, "progress", f"{int(scene_id)}.json")


def write_progress(scene_id: str, duration: float, samples: list) -> None:
    """The frames scored so far, for the player's strip while it waits."""
    with contextlib.suppress(OSError, ValueError):
        write_json(
            progress_path(scene_id),
            {"duration": duration, "threshold": RULE["threshold"], "samples": samples},
        )


def scan_progress(args: dict) -> dict:
    """The frames an analysis running in another process has scored so far."""
    path = progress_path(str(args["scene_id"]))
    with contextlib.suppress(OSError):
        if time.time() - os.path.getmtime(path) < 300:
            return read_json(path, {})
    return {}


def record_failure(scene_id: str, error: Exception) -> None:
    with contextlib.closing(cache()) as connection, connection:
        connection.execute(
            "INSERT OR REPLACE INTO failure (scene_id, model, error, failed_at) "
            "VALUES (?, ?, ?, ?)",
            (scene_id, MODEL_ID, str(error)[:500], now()),
        )


def analyse(args: dict, server: dict) -> dict:
    """The player's request: the cached start, or one worked out now."""
    scene_id = str(args["scene_id"])
    point = get_points({"scene_ids": [scene_id]}).get(scene_id)
    # A start saved before frame times were kept is worked out again once, so
    # the player can draw its chart; a start the viewer marked always stands.
    current = point and (
        point["model"] == "user" or (point["model"] == MODEL_ID and point.get("samples"))
    )
    if current and not args.get("force"):
        return point
    return analyse_scene(scene_id, server, eager=True)


def done_ids(ids: list[str]) -> set[str]:
    """Scenes with a current answer (computed by this model, marked by the
    viewer, or failed with this model)."""
    if not ids or not os.path.isfile(CACHE_PATH):
        return set()
    marks = ",".join("?" * len(ids))
    with contextlib.closing(cache()) as connection:
        rows = connection.execute(
            f"SELECT scene_id FROM start_point WHERE model = ? AND scene_id IN ({marks}) "
            f"UNION SELECT scene_id FROM user_start WHERE scene_id IN ({marks}) "
            f"UNION SELECT scene_id FROM failure WHERE model = ? AND scene_id IN ({marks})",
            [MODEL_ID, *ids, *ids, MODEL_ID, *ids],
        ).fetchall()
    return {row[0] for row in rows}


def lower_priority() -> None:
    with contextlib.suppress(AttributeError, OSError):
        os.nice(10)


def progress(fraction: float, message: str | None = None) -> None:
    """Stash's plugin log protocol: task progress and info lines on stderr."""
    if message:
        sys.stderr.write(f"\x01i\x02{message}\n")
    sys.stderr.write(f"\x01p\x02{max(0.0, min(1.0, fraction)):.4f}\n")
    sys.stderr.flush()


LIBRARY_QUERY = """
query AutoSeekLibrary($page: Int!) {
  findScenes(filter: { page: $page, per_page: 200, sort: "created_at", direction: DESC }) {
    count
    scenes { id }
  }
}
"""


def library_task(args: dict, server: dict) -> dict:
    """Tasks → Find start points: every scene without a current answer,
    newest first, one at a time at low priority. Stopping it loses nothing:
    each answer is saved as it is found."""
    lower_priority()
    ids: list[str] = []
    page = 1
    while True:
        found = stash_query(server, LIBRARY_QUERY, {"page": page})["findScenes"]
        ids += [scene["id"] for scene in found["scenes"]]
        if not found["scenes"] or len(ids) >= found["count"]:
            break
        page += 1
    done = set()
    for i in range(0, len(ids), 500):
        done |= done_ids(ids[i : i + 500])
    todo = [scene_id for scene_id in ids if scene_id not in done]
    analysed = failed = 0
    started = time.monotonic()
    progress(0, f"Auto Seek: {len(todo)} of {len(ids)} scenes to analyse")
    for n, scene_id in enumerate(todo, 1):
        if scene_id in done_ids([scene_id]):
            continue  # the worker or the player got there first
        try:
            analyse_scene(scene_id, server)
            analysed += 1
        except Exception as error:  # one bad file must not stop the run
            if "still downloading" in str(error) or "can't run" in str(error):
                raise
            record_failure(scene_id, error)
            failed += 1
        if n % 10 == 0 or n == len(todo):
            rate = (time.monotonic() - started) / n
            progress(n / len(todo), f"Auto Seek: {n}/{len(todo)} scenes, {rate:.1f} s each")
    return {"analysed": analysed, "failed": failed, "skipped": len(ids) - len(todo)}


# ── new scenes ────────────────────────────────────────────────────────────


def hook(args: dict, server: dict) -> dict:
    """Scene.Create.Post: queue the new scene for the background worker and
    make sure one is running. Returns at once; the scan carries on."""
    scene_id = str((args.get("hookContext") or {}).get("id") or "")
    if not scene_id:
        return {}
    config = stash_query(server, '{ configuration { plugins(include: ["auto-seek"]) } }', {})[
        "configuration"
    ]
    if plugin_settings(config).get("disableNewScenes") is True or not status()["ready"]:
        return {"queued": False}
    with contextlib.closing(cache()) as connection, connection:
        connection.execute(
            "INSERT OR IGNORE INTO pending (scene_id, added_at) VALUES (?, ?)", (scene_id, now())
        )
    start_worker(server)
    return {"queued": True}


def start_worker(server: dict) -> None:
    """A detached worker, unless one holds the worker lock already. The
    connection details go over stdin, so the session cookie never touches
    the disk."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(WORKER_LOCK_PATH, "a+b") as handle:
        if not try_lock(handle):
            return
    options: dict = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        options["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    child = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), PLUGIN_DIR, "worker"], **options
    )
    child.stdin.write(json.dumps(server).encode())
    child.stdin.close()


def worker() -> None:
    """Analyse queued scenes until none are left. One worker at a time."""
    server = json.loads(sys.stdin.read() or "{}")
    lower_priority()
    with open(WORKER_LOCK_PATH, "a+b") as handle:
        if not try_lock(handle):
            return
        while True:
            with contextlib.closing(cache()) as connection:
                row = connection.execute(
                    "SELECT scene_id FROM pending ORDER BY added_at LIMIT 1"
                ).fetchone()
            if row is None:
                return
            scene_id = row[0]
            if scene_id not in done_ids([scene_id]):
                try:
                    analyse_scene(scene_id, server)
                except Exception as error:
                    if "still downloading" in str(error):
                        return  # the queue keeps it for the next new scene
                    record_failure(scene_id, error)
            with contextlib.closing(cache()) as connection, connection:
                connection.execute("DELETE FROM pending WHERE scene_id = ?", (scene_id,))


def mark_point(args: dict) -> dict:
    scene_id = str(args["scene_id"])
    start = float(args["start"])
    duration = float(args["duration"])
    if not 0 <= start <= duration:
        raise ValueError("start must lie within the scene")
    with contextlib.closing(cache()) as connection, connection:
        computed = connection.execute(
            "SELECT start_s, model FROM start_point WHERE scene_id = ?", (scene_id,)
        ).fetchone() or (None, None)
        connection.execute(
            "INSERT OR REPLACE INTO user_start (scene_id, start_s, duration_s, computed_start_s, "
            "computed_model, marked_at) VALUES (?, ?, ?, ?, ?, ?)",
            (scene_id, start, duration, *computed, now()),
        )
    return {"scene_id": scene_id, "start": start}


def unmark_point(args: dict) -> dict:
    scene_id = str(args["scene_id"])
    with contextlib.closing(cache()) as connection, connection:
        connection.execute("DELETE FROM user_start WHERE scene_id = ?", (scene_id,))
    return {"scene_id": scene_id}


OPERATIONS = {
    "status": lambda args, server: status(),
    "ensure": lambda args, server: ensure(),
    "get": lambda args, server: get_points(args),
    "analyse": analyse,
    "progress": lambda args, server: scan_progress(args),
    "frame": frame_preview,
    "mark": lambda args, server: mark_point(args),
    "unmark": lambda args, server: unmark_point(args),
    "library": library_task,
    "hook": hook,
}


def main() -> None:
    if len(sys.argv) > 2 and sys.argv[2] == "download":
        download()
        return
    if len(sys.argv) > 2 and sys.argv[2] == "worker":
        worker()
        return
    try:
        request = json.loads(sys.stdin.read() or "{}")
        args = request.get("args") or {}
        handler = OPERATIONS.get(args.get("op"))
        if handler is None:
            raise ValueError(f"unknown operation: {args.get('op')!r}")
        reply = {"output": handler(args, request.get("server_connection") or {})}
    except Exception as error:
        reply = {"error": str(error)}
    sys.stdout.write(json.dumps(reply))


if __name__ == "__main__":
    main()
