"""Temporary Windows diagnostic: count TCP connections to Stash during Sync and build.

Usage: windows_churn_probe.py <stash dir containing stash-win.exe> <curator zip> <scenes>

Talks to Stash over one persistent connection so the probe adds no churn itself.
With CURATOR_PAGE=1, a headless browser keeps the Curator page open throughout.
"""

from __future__ import annotations

import collections
import csv
import http.client
import json
import os
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

ROOT = Path(sys.argv[1])
CURATOR_ZIP = Path(sys.argv[2])
SCENES = int(sys.argv[3])
PORT = 9999

conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=600)


def gql(query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}})
    conn.request("POST", "/graphql", body, {"Content-Type": "application/json"})
    data = json.loads(conn.getresponse().read())
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return data["data"]


def plugin_operation(operation: str) -> dict:
    return gql(
        'mutation Op($args: Map!) { runPluginOperation(plugin_id: "stash-curator", args: $args) }',
        {"args": {"operation": operation}},
    )["runPluginOperation"]


names: dict[str, str] = {}


def process_name(pid: str) -> str:
    if pid not in names:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True).stdout.strip()
        names[pid] = out.split('","')[0].strip('"') if out.startswith('"') else "exited"
    return names[pid]


def snapshot() -> tuple[int, int, collections.Counter]:
    """TIME_WAIT total, TIME_WAIT touching :9999, and open client connections by process
    (to :9999, and to any other port as "<name> other")."""
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
    total = stash = 0
    clients: collections.Counter = collections.Counter()
    for line in out.splitlines():
        fields = line.split()
        if len(fields) != 5 or fields[0] != "TCP":
            continue
        _, local, remote, state, pid = fields
        if state == "TIME_WAIT":
            total += 1
            if local.endswith(f":{PORT}") or remote.endswith(f":{PORT}"):
                stash += 1
        elif state == "ESTABLISHED" and remote.endswith(f":{PORT}"):
            clients[process_name(pid)] += 1
        elif state == "ESTABLISHED" and not local.endswith(f":{PORT}"):
            clients[process_name(pid) + " other"] += 1
    return total, stash, clients


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
    tags = [gql("mutation($n:String!){tagCreate(input:{name:$n}){id}}", {"n": f"Tag {i}"})["tagCreate"]["id"]
            for i in range(40)]
    performers = [gql("mutation($n:String!){performerCreate(input:{name:$n}){id}}", {"n": f"Performer {i}"})
                  ["performerCreate"]["id"] for i in range(150)]
    studios = [gql("mutation($n:String!){studioCreate(input:{name:$n}){id}}", {"n": f"Studio {i}"})
               ["studioCreate"]["id"] for i in range(20)]
    for i in range(SCENES):
        scene = {"title": f"Synthetic scene {i}", "tag_ids": [tags[(i * k) % len(tags)] for k in (1, 3, 7)],
                 "performer_ids": [performers[i % len(performers)], performers[(i * 7) % len(performers)]],
                 "studio_id": studios[i % len(studios)]}
        if i % 2 == 0:
            scene["stash_ids"] = [{"endpoint": "https://stashdb.org/graphql",
                                   "stash_id": f"00000000-0000-4000-8000-{i:012d}"}]
        if i % 5 == 0:
            scene["rating100"] = (i * 37) % 100 or 50
        scene_id = gql("mutation($i:SceneCreateInput!){sceneCreate(input:$i){id}}", {"i": scene})["sceneCreate"]["id"]
        if i % 10 == 0:
            gql("mutation($id:ID!){sceneAddPlay(id:$id){count}}", {"id": scene_id})
        if i % 1000 == 0:
            print(f"seeded {i} scenes", flush=True)


def main() -> None:
    (ROOT / "config.yml").write_text(
        f"generated: {ROOT / 'generated'}\ncache: {ROOT / 'cache'}\n"
        f"blobs_path: {ROOT / 'blobs'}\nblobs_storage: FILESYSTEM\n"
        f"database: {ROOT / 'stash-go.sqlite'}\nplugins_path: {ROOT / 'plugins'}\n"
        f"logfile: {ROOT / 'stash.log'}\nloglevel: Debug\n"
    )
    stash = subprocess.Popen([str(ROOT / "stash-win.exe"), "--nobrowser", "--config", str(ROOT / "config.yml")],
                             cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for_stash()
        print("status:", gql("{systemStatus{status appSchema databaseSchema}}"), flush=True)
        seed()
        print("scenes:", gql("{findScenes{count}}")["findScenes"]["count"], flush=True)

        with zipfile.ZipFile(CURATOR_ZIP) as archive:
            archive.extractall(ROOT / "plugins" / "stash-curator")
        gql("mutation{reloadPlugins}")
        print("plugins:", gql("{plugins{id enabled version}}")["plugins"], flush=True)

        print("waiting 130 s for seeding TIME_WAIT to expire", flush=True)
        time.sleep(130)
        baseline = snapshot()
        print(f"baseline TIME_WAIT total={baseline[0]} stash={baseline[1]} clients={dict(baseline[2])}", flush=True)

        rows: list[list] = []
        peak = [0, 0]
        peak_clients: collections.Counter = collections.Counter()
        stop = threading.Event()
        started = time.time()

        def sample() -> None:
            while not stop.is_set():
                total, to_stash, clients = snapshot()
                peak[0], peak[1] = max(peak[0], total), max(peak[1], to_stash)
                for name, count in clients.items():
                    peak_clients[name] = max(peak_clients[name], count)
                rows.append([round(time.time() - started), total, to_stash, json.dumps(dict(clients))])
                stop.wait(2)

        sampler = threading.Thread(target=sample)
        sampler.start()
        browser = None
        if os.environ.get("CURATOR_PAGE") == "1":
            from playwright.sync_api import sync_playwright

            playwright = sync_playwright().start()
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.on("console", lambda msg: msg.type == "error" and print("console:", msg.text, flush=True))
            page.goto(f"http://127.0.0.1:{PORT}/plugins/stash-curator", wait_until="networkidle")
            print("Curator page open", flush=True)
        print("task:", gql('mutation{runPluginTask(plugin_id:"stash-curator", task_name:"Sync and build recommendations")}'),
              flush=True)
        # Poll like the open Curator page does.
        jobs: list = []
        for _ in range(900):
            time.sleep(4)
            jobs = plugin_operation("get_job_status").get("jobs", [])
            if jobs and not any(job["state"] in ("queued", "running") for job in jobs):
                break
        elapsed = time.time() - started
        time.sleep(60 if browser else 10)
        if browser:
            page.screenshot(path=str(ROOT / "curator-page.png"))
            browser.close()
        stop.set()
        sampler.join()

        with open(ROOT / "churn.csv", "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["seconds", "time_wait_total", "time_wait_stash", "open_clients_to_stash"])
            writer.writerows(rows)
        print(f"jobs: {[(job['job_type'], job['state'], job.get('error')) for job in jobs][:5]}", flush=True)
        print(f"task duration ~{elapsed:.0f} s", flush=True)
        print(f"PEAK TIME_WAIT total={peak[0]} stash={peak[1]} (baseline {baseline[0]}/{baseline[1]})", flush=True)
        print(f"peak open connections to Stash by process: {dict(peak_clients)}", flush=True)
    finally:
        stash.terminate()


if __name__ == "__main__":
    main()
