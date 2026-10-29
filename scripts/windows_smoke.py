"""Windows smoke test: run a Curator build against native Stash on Windows.

Usage: windows_smoke.py <dir containing stash-win.exe> <curator zip> [scenes]

Seeds a synthetic library, installs the plugin archive, runs Sync and build,
calls the status and diagnostic operations, keeps the Curator page open in a
headless browser, and fails on task failures, browser exceptions, Curator
errors in Stash's log, or connection churn above a budget. Talks to Stash over
one persistent connection so the script adds no churn itself.
"""

from __future__ import annotations

import http.client
import json
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(sys.argv[1])
CURATOR_ZIP = Path(sys.argv[2])
SCENES = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
PORT = 9999
PAGE_SECONDS = 60
# New TCP connections accepted on this machine. Measured on windows-latest:
# about 21 during Sync and build and 34 per minute with the page open before
# the shared status poll; each budget leaves headroom for runner noise.
TASK_OPENS_BUDGET = 150
PAGE_OPENS_BUDGET = 40

conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=600)
failures: list[str] = []


def gql(query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}})
    conn.request("POST", "/graphql", body, {"Content-Type": "application/json"})
    data = json.loads(conn.getresponse().read())
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return data["data"]


def plugin_operation(operation: str, **args: object) -> dict:
    return gql(
        'mutation Op($args: Map!) { runPluginOperation(plugin_id: "stash-curator", args: $args) }',
        {"args": {"operation": operation, **args}},
    )["runPluginOperation"]


def check(condition: bool, message: str) -> None:
    print(("ok   " if condition else "FAIL ") + message, flush=True)
    if not condition:
        failures.append(message)


def passive_opens() -> int:
    """Windows' cumulative accepted TCP connections, from netstat -s."""
    out = subprocess.run(
        ["netstat", "-s", "-p", "tcp"], capture_output=True, text=True, check=True
    ).stdout
    match = re.search(r"Passive Opens\s*=\s*(\d+)", out)
    return int(match.group(1)) if match else -1


def wait_for_stash() -> None:
    for _ in range(120):
        try:
            probe = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
            probe.request("GET", "/healthz")
            if probe.getresponse().status == 200:
                probe.close()
                return
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError("Stash did not start")


def seed() -> None:
    def create(kind: str, name: str) -> str:
        mutation = f"mutation($n:String!){{{kind}Create(input:{{name:$n}}){{id}}}}"
        return gql(mutation, {"n": name})[f"{kind}Create"]["id"]

    tags = [create("tag", f"Tag {i}") for i in range(40)]
    performers = [create("performer", f"Performer {i}") for i in range(150)]
    studios = [create("studio", f"Studio {i}") for i in range(20)]
    for i in range(SCENES):
        scene: dict = {
            "title": f"Synthetic scene {i}",
            "tag_ids": [tags[(i * k) % len(tags)] for k in (1, 3, 7)],
            "performer_ids": [
                performers[i % len(performers)],
                performers[(i * 7) % len(performers)],
            ],
            "studio_id": studios[i % len(studios)],
        }
        if i % 2 == 0:
            scene["stash_ids"] = [
                {
                    "endpoint": "https://stashdb.org/graphql",
                    "stash_id": f"00000000-0000-4000-8000-{i:012d}",
                }
            ]
        if i % 5 == 0:
            scene["rating100"] = (i * 37) % 100 or 50
        mutation = "mutation($i:SceneCreateInput!){sceneCreate(input:$i){id}}"
        scene_id = gql(mutation, {"i": scene})["sceneCreate"]["id"]
        if i % 10 == 0:
            gql("mutation($id:ID!){sceneAddPlay(id:$id){count}}", {"id": scene_id})


def run_page(page_errors: list[str]) -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.goto(f"http://127.0.0.1:{PORT}/plugins/stash-curator", wait_until="networkidle")
        before = passive_opens()
        time.sleep(PAGE_SECONDS)
        opens = passive_opens() - before
        page.goto(
            f"http://127.0.0.1:{PORT}/plugins/stash-curator?view=manage&section=diagnostics",
            wait_until="networkidle",
        )
        page.wait_for_selector(".curator-diagnostics-preview", timeout=60_000)
        report = page.inner_text(".curator-diagnostics-preview")
        check('"connection"' in report, "Diagnostics report includes the connection check")
        page.screenshot(path=str(ROOT / "curator-page.png"))
        browser.close()
    return opens


def main() -> None:
    (ROOT / "config.yml").write_text(
        f"generated: {ROOT / 'generated'}\ncache: {ROOT / 'cache'}\n"
        f"blobs_path: {ROOT / 'blobs'}\nblobs_storage: FILESYSTEM\n"
        f"database: {ROOT / 'stash-go.sqlite'}\nplugins_path: {ROOT / 'plugins'}\n"
        f"logfile: {ROOT / 'stash.log'}\nloglevel: Debug\n"
    )
    stash = subprocess.Popen(
        [str(ROOT / "stash-win.exe"), "--nobrowser", "--config", str(ROOT / "config.yml")],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_stash()
        seed()
        with zipfile.ZipFile(CURATOR_ZIP) as archive:
            archive.extractall(ROOT / "plugins" / "stash-curator")
        gql("mutation{reloadPlugins}")
        plugins = {
            plugin["id"]: plugin for plugin in gql("{plugins{id enabled version}}")["plugins"]
        }
        check("stash-curator" in plugins, f"plugin loaded: {plugins.get('stash-curator')}")

        before = passive_opens()
        gql(
            'mutation{runPluginTask(plugin_id:"stash-curator", '
            'task_name:"Sync and build recommendations")}'
        )
        jobs: list = []
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            time.sleep(4)
            jobs = plugin_operation("get_status")["jobs"]
            if jobs and not any(job["state"] in ("queued", "running") for job in jobs):
                break
        task_opens = passive_opens() - before
        sync = next(
            (job for job in jobs if job["job_type"] in ("sync-build", "full-sync-build")), None
        )
        check(sync is not None and sync["state"] == "complete", f"Sync and build: {sync}")
        check(
            task_opens <= TASK_OPENS_BUDGET,
            f"{task_opens} connections during Sync and build (budget {TASK_OPENS_BUDGET})",
        )

        status = plugin_operation("get_status")
        check(status["health"]["ready"] is True, "model ready after Sync and build")
        slate = plugin_operation("get_slate", lane="for_you", count=5)
        # The synthetic library carries no taste signal, so the slate may be
        # empty; the operation must still answer with its items list.
        check(
            isinstance(slate.get("items"), list), f"For You answered ({len(slate['items'])} items)"
        )
        connection = plugin_operation("get_connection_check")
        print("connection check:", json.dumps(connection), flush=True)
        check(connection["stash"]["ok"] is True, "connection check reached Stash")
        check("sockets" in connection, "connection check reports Windows socket counts")

        page_errors: list[str] = []
        page_opens = run_page(page_errors)
        check(not page_errors, f"no browser exceptions: {page_errors[:3]}")
        check(
            page_opens <= PAGE_OPENS_BUDGET,
            f"{page_opens} connections in {PAGE_SECONDS} s on the page "
            f"(budget {PAGE_OPENS_BUDGET})",
        )
    finally:
        stash.terminate()
        stash.wait(timeout=60)

    log = [
        line
        for line in (ROOT / "stash.log").read_text(errors="replace").splitlines()
        if "Stash Curator" in line
    ]
    check(bool(log), f"Stash's log names the plugin ({len(log)} lines)")
    curator_errors = [
        line for line in log if re.search(r"level=(error|fatal)|\bERRO\b", line, re.IGNORECASE)
    ]
    check(not curator_errors, f"no Curator errors in Stash's log: {curator_errors[:5]}")
    warnings = [line for line in log if re.search(r"level=warn|\bWARN\b", line, re.IGNORECASE)]
    print(f"{len(warnings)} Curator warnings in Stash's log: {warnings[:5]}", flush=True)
    daemon_log = ROOT / "plugins" / "stash-curator" / "data" / "curator-daemon.log"
    daemon_failures = [
        line
        for line in (
            daemon_log.read_text(errors="replace").splitlines() if daemon_log.exists() else []
        )
        if "request failed" in line or "returned" in line
    ]
    check(not daemon_failures, f"no request failures in the daemon log: {daemon_failures[:5]}")
    if failures:
        print(f"{len(failures)} check(s) failed", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
