import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "auto-seek" / "auto_seek.py"


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["auto_seek.py", str(tmp_path)])
    spec = importlib.util.spec_from_file_location("auto_seek_under_test", BACKEND)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server():
    files: dict[str, bytes] = {}
    ranges: list[str | None] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = files[self.path]
            ranges.append(self.headers.get("Range"))
            start = (
                int(self.headers["Range"].split("=")[1].rstrip("-"))
                if self.headers.get("Range")
                else 0
            )
            self.send_response(206 if start else 200)
            self.send_header("Content-Length", str(len(body) - start))
            self.end_headers()
            self.wfile.write(body[start:])

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", files, ranges
    httpd.shutdown()


def entry(base, files, name, body, *, sha=None):
    files[f"/{name}"] = body
    return {
        "path": f"sub/{name}",
        "url": f"{base}/{name}",
        "sha256": sha or hashlib.sha256(body).hexdigest(),
        "size": len(body),
    }


def test_download_resumes_and_verifies(backend, server):
    base, files, ranges = server
    big = os.urandom(300_000)
    backend.FILES = (
        entry(base, files, "a.bin", big),
        entry(base, files, "b.js", b"console.log(1)"),
    )
    partial = Path(backend.FILES_DIR, "sub", "a.bin.part")
    partial.parent.mkdir(parents=True)
    partial.write_bytes(big[:100_000])
    Path(backend.LOCK_PATH).write_text("1")

    backend.download()

    assert Path(backend.FILES_DIR, "sub", "a.bin").read_bytes() == big
    assert ranges[0] == "bytes=100000-"
    assert not partial.exists() and not Path(backend.LOCK_PATH).exists()
    status = backend.status()
    assert status["ready"] and not status["downloading"] and status["received"] == status["total"]


def test_download_removes_files_an_earlier_version_pinned(backend, server):
    base, files, _ = server
    backend.FILES = (entry(base, files, "new.bin", b"new model"),)
    old = Path(backend.FILES_DIR, "sub", "old.bin")
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old model")
    outside = Path(backend.DATA_DIR, "cache.sqlite3")
    outside.write_bytes(b"keep")
    Path(backend.VERIFIED_PATH).write_text(
        json.dumps({"sub/old.bin": "x", "../cache.sqlite3": "y"})
    )
    Path(backend.LOCK_PATH).write_text("1")

    backend.download()

    assert not old.exists() and outside.read_bytes() == b"keep"
    assert Path(backend.FILES_DIR, "sub", "new.bin").read_bytes() == b"new model"
    assert set(json.loads(Path(backend.VERIFIED_PATH).read_text())) == {"sub/new.bin"}
    assert backend.status()["ready"]


def test_checksum_failure_is_reported_and_not_marked_ready(backend, server):
    base, files, _ = server
    backend.FILES = (entry(base, files, "a.bin", b"tampered", sha="0" * 64),)
    Path(backend.DATA_DIR).mkdir()
    Path(backend.LOCK_PATH).write_text("1")

    backend.download()

    status = backend.status()
    assert not status["ready"] and not status["downloading"]
    assert "checksum" in status["error"]
    assert not Path(backend.FILES_DIR, "sub", "a.bin").exists()
    assert not Path(backend.FILES_DIR, "sub", "a.bin.part").exists()


def test_ensure_starts_one_detached_download(backend, server, monkeypatch):
    base, files, _ = server
    backend.FILES = (entry(base, files, "a.bin", b"x" * 10),)
    started = []
    monkeypatch.setattr(
        backend.subprocess, "Popen", lambda args, **options: started.append((args, options))
    )

    first = backend.ensure()
    second = backend.ensure()

    assert first["downloading"] and second["downloading"]
    assert len(started) == 1
    args, options = started[0]
    assert args[-2:] == [backend.PLUGIN_DIR, "download"]
    assert options.get("start_new_session") or options.get("creationflags")


def test_abandoned_lock_allows_a_new_download(backend, server, monkeypatch):
    base, files, _ = server
    backend.FILES = (entry(base, files, "a.bin", b"x" * 10),)
    Path(backend.DATA_DIR).mkdir()
    Path(backend.LOCK_PATH).write_text("1")
    old = os.path.getmtime(backend.LOCK_PATH) - backend.LOCK_STALE_SECONDS - 5
    os.utime(backend.LOCK_PATH, (old, old))
    started = []
    monkeypatch.setattr(backend.subprocess, "Popen", lambda args, **options: started.append(args))

    assert backend.ensure()["downloading"]
    assert len(started) == 1


def test_start_point_cache_round_trip(backend):
    assert backend.get_points({"scene_ids": ["7"]}) == {}
    backend.put_point(
        {
            "scene_id": 7,
            "start": 312.5,
            "duration": 1800,
            "model": "m1",
            "scores": [(150, 0.1), (312.5, 0.9)],
        }
    )
    # The frames behind the start come back for the player's chart.
    first = backend.get_points({"scene_ids": ["7"]})["7"]
    assert first["samples"] == [[150, 0.1], [312.5, 0.9]]
    assert first["threshold"] == backend.RULE["threshold"]
    backend.put_point({"scene_id": 7, "start": 300, "duration": 1800, "model": "m2"})

    point = backend.get_points({"scene_ids": [7, 8]})
    assert list(point) == ["7"]
    assert point["7"]["start"] == 300 and point["7"]["model"] == "m2"
    with pytest.raises(ValueError):
        backend.put_point({"scene_id": 7, "start": 2000, "duration": 1800})


def test_progress_shows_frames_scored_so_far(backend, monkeypatch):
    monkeypatch.setattr(backend, "status", lambda: {"ready": True, "supported": True})
    assert backend.scan_progress({"scene_id": 7}) == {}
    backend.write_progress("7", 1800.0, [[150, 0.1], [300, 0.9]])
    progress = backend.scan_progress({"scene_id": "7"})
    assert progress["samples"] == [[150, 0.1], [300, 0.9]] and progress["duration"] == 1800.0
    with pytest.raises(ValueError):
        backend.progress_path("../x")  # scene ids only


def test_results_saved_before_frame_times_have_no_chart(backend):
    assert backend.chart("[0.1, 0.9]") == {}
    assert backend.chart("") == {} and backend.chart("not json") == {}


def test_marked_start_wins_and_survives_recomputation(backend):
    backend.put_point({"scene_id": 7, "start": 300, "duration": 1800, "model": "m1"})
    backend.mark_point({"scene_id": 7, "start": 284, "duration": 1800})
    # A new model recomputes the scene; the viewer's mark still wins.
    backend.put_point({"scene_id": 7, "start": 320, "duration": 1800, "model": "m2"})
    point = backend.get_points({"scene_ids": ["7"]})["7"]
    assert (point["start"], point["model"]) == (284, "user")
    # The computed start at marking time is kept beside the mark, as a label.
    with backend.cache() as connection:
        row = connection.execute(
            "SELECT start_s, computed_start_s, computed_model FROM user_start"
        ).fetchone()
    assert row == (284, 300, "m1")
    backend.unmark_point({"scene_id": 7})
    assert backend.get_points({"scene_ids": ["7"]})["7"]["model"] == "m2"


def test_cache_from_version_1_gains_the_marks_table(backend):
    import sqlite3

    os.makedirs(backend.DATA_DIR, exist_ok=True)
    with sqlite3.connect(backend.CACHE_PATH) as connection:
        connection.executescript(
            "CREATE TABLE start_point (scene_id TEXT PRIMARY KEY, start_s REAL NOT NULL, "
            "duration_s REAL NOT NULL, model TEXT NOT NULL, scores TEXT NOT NULL DEFAULT '[]', "
            "computed_at TEXT NOT NULL);"
            "INSERT INTO start_point VALUES ('7', 300, 1800, 'm1', '[]', 'then');"
            "PRAGMA user_version = 1;"
        )
    assert backend.get_points({"scene_ids": ["7"]})["7"]["start"] == 300
    backend.mark_point({"scene_id": 7, "start": 290, "duration": 1800})
    assert backend.get_points({"scene_ids": ["7"]})["7"]["model"] == "user"


def test_raw_interface_replies_with_output_or_error(backend, monkeypatch, capsys):
    for request, key in (
        ({"args": {"op": "status"}}, "output"),
        ({"args": {"op": "nope"}}, "error"),
    ):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(request)))
        backend.main()
        assert key in json.loads(capsys.readouterr().out)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_frames_are_cut_as_raw_model_input(backend, tmp_path):
    video = tmp_path / "scene.mp4"
    source = "testsrc=duration=4:size=640x360:rate=10"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", source, str(video)], check=True
    )
    frames = backend.grab_frames(shutil.which("ffmpeg"), str(video), [1.5, 60, 3, 0.5])
    # Short side scaled to 224 and the centre square kept, as raw RGB.
    assert len(frames[0]) == 224 * 224 * 3
    assert frames[1] is None  # past the end: no frame there
    # ...without costing the other frames of the same ffmpeg run.
    assert frames[2] and frames[3] and frames[2] != frames[3]
    assert not backend.blank(frames[0])
    assert backend.blank(bytes(224 * 224 * 3)) and backend.blank(b"\x80" * (224 * 224 * 3))


def test_search_helpers(backend):
    rule = backend.RULE
    assert backend.parse_exclude("5%", 200) == 10 and backend.parse_exclude("12", 200) == 12
    assert backend.parse_exclude(None, 200) == 0 and backend.parse_exclude("x", 200) == 0
    times = backend.coarse_times(1200, {"previewSegments": 12})
    assert len(times) == 12 and times[1] == 100
    assert backend.coarse_times(1200, {"previewSegments": 12, "previewExcludeStart": "10%"})[
        :2
    ] == [
        120,
        210,
    ]
    assert backend.change_point([0.1, 0.1, 0.9, 0.95]) == 2
    assert backend.change_point([0.9, 0.9, 0.9]) == 0
    assert backend.change_point([0.1, 0.2, 0.1]) == 2
    assert backend.scan_window([0, 100, 200, 300], [0.1, 0.6, 0.7, 0.9], rule) == (0, 300)
    window = backend.scan_window([0, 100, 200, 300, 400], [0.1, 0.2, 0.95, 0.95, 0.95], rule)
    assert window == (100, 200)
    # A "maybe" frame before the jump moves the scan one sample back: the
    # start can lie before a frame the model was unsure about.
    window = backend.scan_window([0, 100, 200, 300, 400], [0.02, 0.04, 0.44, 0.99, 1.0], rule)
    assert window == (100, 300)
    # The jump at the very first frame scored (here 0:00 came out blank):
    # the start may lie before it, so the scan begins where sampling began.
    window = backend.scan_window([116, 232, 348], [0.98, 0.04, 0.92], rule, origin=0)
    assert window == (0, 116)
    assert backend.scan_times(0, 300, rule) == [0, 37.5, 75, 112.5, 150, 187.5, 225, 262.5, 300]
    assert backend.scan_times(100, 130, rule) == [100, 115, 130]
    assert backend.scan_times(200, 200, rule) == [200]
    assert backend.bisect_times(268, 289, 2) == [273.25, 278.5, 283.75]
    assert backend.bisect_times(100, 105, 3) == []


def test_search_finds_the_start_and_stops_early(backend):
    calls = []

    def score_at(times):
        calls.append(list(times))
        return [0.97 if t >= 437 else 0.05 for t in times]

    start, scores = backend.search(score_at, 1200, {"previewSegments": 12})
    # Coarse frames every 100 s, cut three at a time; the first two sure ones
    # (500, 600) end that pass, so nothing after the batch holding 600 is cut.
    assert calls[:3] == [[0, 100, 200], [300, 400, 500], [600, 700, 800]]
    # Scan 400..500, then bisection narrows the gap to within a few seconds.
    assert 437 <= start <= 437 + 15 / 8 + 1e-6
    assert all(400 <= t <= 500 for batch in calls[3:] for t in batch)
    # Cut but not needed: 700 and 800, and 460 and 475 after the first hit at 445.
    assert len(scores) == sum(len(batch) for batch in calls) - 4


def test_eager_search_asks_for_each_pass_at_once_with_the_same_answer(backend):
    def scorer(calls):
        def score_at(times):
            calls.append(list(times))
            return [0.97 if t >= 437 else 0.05 for t in times]

        return score_at

    lazy, eager = [], []
    expected = backend.search(scorer(lazy), 1200, {"previewSegments": 12})
    assert backend.search(scorer(eager), 1200, {"previewSegments": 12}, eager=True) == expected
    assert len(eager[0]) == 12 and len(eager) == 3  # coarse, scan, bisection points
    assert len(lazy) > len(eager)


def test_search_reports_its_passes_in_order(backend):
    phases = []
    backend.search(
        lambda times: [0.97 if t >= 437 else 0.05 for t in times],
        1200,
        {"previewSegments": 12},
        on_phase=phases.append,
    )
    assert phases == ["sampling", "zooming", "pinpointing"]


def test_progress_reports_the_first_download(backend, monkeypatch):
    monkeypatch.setattr(
        backend,
        "status",
        lambda: {
            "ready": False,
            "supported": True,
            "downloading": True,
            "received": 5,
            "total": 10,
            "error": None,
        },
    )
    assert backend.scan_progress({"scene_id": 7}) == {
        "phase": "downloading",
        "received": 5,
        "total": 10,
        "error": None,
    }


def test_search_gives_up_on_blank_frames(backend):
    with pytest.raises(ValueError, match="blank"):
        backend.search(lambda times: [None] * len(times), 1200, {})


def test_platform_choice(backend, monkeypatch):
    monkeypatch.setattr(backend.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(backend.sys, "platform", "linux")
    monkeypatch.setattr(backend.glob, "glob", lambda pattern: ["/lib/ld-musl-x86_64.so.1"])
    assert backend.platform_key() == "linux-x64-musl"
    monkeypatch.setattr(backend.glob, "glob", lambda pattern: [])
    monkeypatch.setattr(backend.platform, "libc_ver", lambda: ("glibc", "2.39"))
    assert backend.platform_key() == "linux-x64-glibc"
    monkeypatch.setattr(backend.sys, "platform", "win32")
    monkeypatch.setattr(backend.platform, "machine", lambda: "AMD64")
    assert backend.platform_key() == "windows-x64"
    monkeypatch.setattr(backend.sys, "platform", "darwin")
    monkeypatch.setattr(backend.platform, "machine", lambda: "x86_64")
    assert backend.platform_key() is None  # Intel Macs have no build
    monkeypatch.setattr(backend.sys, "platform", "win32")
    monkeypatch.setattr(backend.platform, "machine", lambda: "ARM64")
    assert backend.platform_key() == "windows-arm64"
    monkeypatch.setattr(backend.sys, "platform", "linux")
    monkeypatch.setattr(backend.platform, "machine", lambda: "armv7l")
    assert backend.platform_key() is None  # 32-bit ARM: only Alpine has a build
    monkeypatch.setattr(backend.glob, "glob", lambda pattern: ["/lib/ld-musl-armhf.so.1"])
    assert backend.platform_key() == "linux-armv7-musl"
    assert all(key in backend.RUNTIMES for key in ("linux-arm64-musl", "macos-arm64"))


def test_unsupported_server_never_downloads(backend, monkeypatch):
    monkeypatch.setattr(backend, "platform_key", lambda: None)
    started = []
    monkeypatch.setattr(backend.subprocess, "Popen", lambda *a, **k: started.append(a))
    status = backend.ensure()
    assert not status["supported"] and not status["ready"] and not started


@pytest.mark.parametrize("kind", ["tgz", "zip"])
def test_runtime_archives_keep_only_the_named_members(backend, server, kind, tmp_path):
    import tarfile
    import zipfile

    base, files, _ = server
    members = {"ort/lib/libonnxruntime.so.1.2.3": b"LIB", "ort/LICENSE": b"MIT", "ort/x.h": b"h"}
    archive = tmp_path / f"ort.{kind}"
    if kind == "zip":
        with zipfile.ZipFile(archive, "w") as bundle:
            for name, body in members.items():
                bundle.writestr(name, body)
    else:
        with tarfile.open(archive, "w:gz") as bundle:
            for name, body in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(body)
                bundle.addfile(info, io.BytesIO(body))
    runtime = entry(base, files, f"ort.{kind}", archive.read_bytes())
    runtime |= {
        "path": "runtime/ort",
        "members": {
            "ort/lib/libonnxruntime.so.1.2.3": "libonnxruntime.so",
            "ort/LICENSE": "LICENSE",
        },
        "library": "libonnxruntime.so",
    }
    backend.FILES = (runtime,)
    backend.download()
    folder = Path(backend.FILES_DIR, "runtime", "ort")
    assert sorted(p.name for p in folder.iterdir()) == ["LICENSE", "libonnxruntime.so"]
    assert (folder / "libonnxruntime.so").read_bytes() == b"LIB"
    assert backend.status()["received"] == backend.status()["total"]
    assert not Path(backend.FILES_DIR, "downloads", f"ort.{kind}.part").exists()


def test_model_is_read_from_a_local_copy_once_made(backend, monkeypatch, tmp_path):
    body = b"model bytes"
    monkeypatch.setattr(backend.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    monkeypatch.setitem(backend.MODEL, "size", len(body))
    shared = Path(backend.target_of(backend.MODEL))
    shared.parent.mkdir(parents=True)
    shared.write_bytes(body)
    assert backend.model_bytes() == body
    shared.write_bytes(b"x" * len(body))  # the share is not read again
    assert backend.model_bytes() == body
    copies = list((tmp_path / "tmp" / "auto-seek").iterdir())
    assert [p.name for p in copies] == [backend.MODEL["sha256"][:16] + ".onnx"]


def test_analyse_answers_from_the_cache(backend, monkeypatch):
    backend.put_point(
        {
            "scene_id": 7,
            "start": 300,
            "duration": 1800,
            "model": backend.MODEL_ID,
            "scores": [(300, 0.9)],
        }
    )
    backend.put_point({"scene_id": 8, "start": 300, "duration": 1800, "model": "older"})
    worked = []
    monkeypatch.setattr(
        backend,
        "analyse_scene",
        lambda scene_id, server, eager=False: worked.append(scene_id) or {},
    )
    assert backend.analyse({"scene_id": 7}, {})["start"] == 300
    backend.analyse({"scene_id": 8}, {})
    assert worked == ["8"]  # a result from an older model is worked out again
    # So is one saved before frame times were kept, once, for the player's chart.
    with backend.cache() as connection:
        connection.execute("UPDATE start_point SET scores = '[0.1, 0.9]' WHERE scene_id = '7'")
    backend.analyse({"scene_id": 7}, {})
    assert worked == ["8", "7"]


def test_library_task_skips_answered_scenes_and_records_failures(backend, monkeypatch):
    backend.put_point({"scene_id": 1, "start": 30, "duration": 900, "model": backend.MODEL_ID})
    backend.mark_point({"scene_id": 2, "start": 40, "duration": 900})
    pages = {1: ["1", "2", "3"], 2: ["4"]}
    monkeypatch.setattr(
        backend,
        "stash_query",
        lambda server, query, variables: {
            "findScenes": {
                "count": 4,
                "scenes": [{"id": i} for i in pages.get(variables["page"], [])],
            }
        },
    )
    monkeypatch.setattr(backend, "lower_priority", lambda: None)
    seen = []

    def analyse_scene(scene_id, server):
        seen.append(scene_id)
        if scene_id == "4":
            raise ValueError("broken file")
        backend.put_point(
            {"scene_id": scene_id, "start": 1, "duration": 9, "model": backend.MODEL_ID}
        )

    monkeypatch.setattr(backend, "analyse_scene", analyse_scene)
    assert backend.library_task({}, {}) == {"analysed": 1, "failed": 1, "skipped": 2}
    assert seen == ["3", "4"]
    # The next run neither retries the failure nor redoes the rest.
    seen.clear()
    assert backend.library_task({}, {})["skipped"] == 4 and not seen


def test_new_scenes_queue_for_one_worker(backend, monkeypatch):
    monkeypatch.setattr(
        backend, "stash_query", lambda *args: {"configuration": {"plugins": {"auto-seek": {}}}}
    )
    monkeypatch.setattr(backend, "status", lambda: {"ready": True})
    spawned = []

    class Child:
        def __init__(self, args, **options):
            spawned.append((args, options))
            self.stdin = io.BytesIO()
            self.stdin.close = lambda: spawned.append(("stdin", self.stdin.getvalue()))

    monkeypatch.setattr(backend.subprocess, "Popen", Child)
    server = {"Port": 9999, "SessionCookie": {"Name": "session", "Value": "secret"}}
    assert backend.hook({"hookContext": {"id": 5, "type": "Scene.Create.Post"}}, server)["queued"]
    args, options = spawned[0]
    assert args[-1] == "worker" and (
        options.get("start_new_session") or options.get("creationflags")
    )
    # The connection goes to the worker over stdin, not into a file.
    assert json.loads(spawned[1][1]) == server
    assert not any(
        "secret" in p.read_text(errors="ignore") for p in Path(backend.DATA_DIR).glob("*.json")
    )
    # A running worker (holding the lock) is left to pick the next one up.
    with open(backend.WORKER_LOCK_PATH, "a+b") as held:
        assert backend.try_lock(held)
        backend.hook({"hookContext": {"id": 6}}, server)
    assert len([s for s in spawned if s[0] != "stdin"]) == 1
    with backend.cache() as connection:
        assert [
            r[0] for r in connection.execute("SELECT scene_id FROM pending ORDER BY scene_id")
        ] == ["5", "6"]


def test_worker_drains_the_queue(backend, monkeypatch):
    with backend.cache() as connection:
        connection.executemany(
            "INSERT INTO pending VALUES (?, ?)", [("5", "a"), ("6", "b"), ("7", "c")]
        )
    backend.put_point({"scene_id": 6, "start": 1, "duration": 9, "model": backend.MODEL_ID})
    seen = []

    def analyse_scene(scene_id, server):
        seen.append((scene_id, server))
        if scene_id == "7":
            raise ValueError("broken file")

    monkeypatch.setattr(backend, "analyse_scene", analyse_scene)
    monkeypatch.setattr(backend, "lower_priority", lambda: None)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"Port": 1})))
    backend.worker()
    assert seen == [("5", {"Port": 1}), ("7", {"Port": 1})]
    assert backend.done_ids(["7"]) == {"7"}  # failed with this model: not retried
    with backend.cache() as connection:
        assert connection.execute("SELECT COUNT(*) FROM pending").fetchone()[0] == 0


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_frame_preview_is_a_small_jpeg_of_that_moment(backend, tmp_path, monkeypatch):
    import base64

    video = tmp_path / "scene.mp4"
    source = "testsrc=duration=4:size=640x360:rate=10"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", source, str(video)], check=True
    )
    monkeypatch.setattr(
        backend,
        "stash_query",
        lambda *a: {
            "findScene": {"files": [{"path": str(video), "duration": 4}]},
            "configuration": {"general": {"ffmpegPath": shutil.which("ffmpeg")}},
        },
    )
    frame = backend.frame_preview({"scene_id": 7, "time": 1.5}, {})
    assert base64.b64decode(frame["jpeg"])[:2] == b"\xff\xd8"
    assert backend.frame_preview({"scene_id": 7, "time": 60}, {})["jpeg"] is None


def test_ffmpeg_runs_are_limited_across_processes(backend, monkeypatch):
    monkeypatch.setattr(backend, "FFMPEG_SLOTS", 2)
    running = 0
    peak = 0
    lock = threading.Lock()

    def hold():
        nonlocal running, peak
        with backend.ffmpeg_slot():
            with lock:
                running += 1
                peak = max(peak, running)
            time.sleep(0.2)
            with lock:
                running -= 1

    # Threads open the lock files separately, so they contend for them as
    # separate ffmpeg-running processes would.
    threads = [threading.Thread(target=hold) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert peak == 2
