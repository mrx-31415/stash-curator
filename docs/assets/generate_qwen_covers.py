"""Generate the synthetic cover candidates declared in qwen-cover-prompts.json."""

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
CONFIG_PATH = Path.home() / ".config" / "cover-story" / "instance.json"
ENDPOINT = "https://api.runpod.ai/v2/qwen-image-t2i/runsync"
RUN_ENDPOINT = ENDPOINT.removesuffix("/runsync") + "/run"
STATUS_ENDPOINT = ENDPOINT.removesuffix("/runsync") + "/status/"


def api_key() -> str:
    if value := os.environ.get("RUNPOD_API_KEY"):
        return value
    return json.loads(CONFIG_PATH.read_text())["runpod_api_key"]


def generate(key: str, prompt: str, negative_prompt: str, size: str, seed: int) -> bytes:
    payload = json.dumps(
        {
            "input": {
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "size": size,
                "seed": seed,
                "enable_safety_checker": True,
            }
        }
    ).encode()
    request = urllib.request.Request(
        ENDPOINT,
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)
    while result.get("status") in {"IN_QUEUE", "IN_PROGRESS"}:
        time.sleep(1)
        status_request = urllib.request.Request(
            STATUS_ENDPOINT + result["id"], headers={"Authorization": f"Bearer {key}"}
        )
        with urllib.request.urlopen(status_request, timeout=180) as response:
            result = json.load(response)
    output = result.get("output") or {}
    image_url = output.get("image_url") if isinstance(output, dict) else None
    if not image_url:
        output_shape = list(output) if isinstance(output, dict) else type(output).__name__
        raise RuntimeError(
            f"Runpod image request failed: {result.get('status', 'unknown')} "
            f"{result.get('error', result.get('message', f'output fields: {output_shape}'))}"
        )
    with urllib.request.urlopen(image_url, timeout=180) as response:
        return response.read()


def submit(key: str, prompt: str, negative_prompt: str, size: str, seed: int) -> str:
    payload = json.dumps(
        {
            "input": {
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "size": size,
                "seed": seed,
                "enable_safety_checker": True,
            }
        }
    ).encode()
    request = urllib.request.Request(
        RUN_ENDPOINT,
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["id"]


def collect(key: str, jobs: list[dict[str, object]], output_dir: Path) -> int:
    complete = 0
    for job in jobs:
        output = output_dir / str(job["output"])
        if output.exists():
            complete += 1
            continue
        request = urllib.request.Request(
            STATUS_ENDPOINT + str(job["id"]), headers={"Authorization": f"Bearer {key}"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        output_data = result.get("output") or {}
        image_url = output_data.get("image_url") or output_data.get("result")
        if image_url:
            with urllib.request.urlopen(image_url, timeout=30) as response:
                output.write_bytes(response.read())
            complete += 1
        elif result.get("status") == "FAILED":
            raise RuntimeError(f"Runpod job failed: {job['id']}")
    return complete


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=ROOT / "qwen-cover-prompts.json")
    parser.add_argument("--output", type=Path, default=Path("/tmp/stash-curator-qwen-covers"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--collect", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    prompts = manifest["prompts"][: args.limit]
    jobs_path = args.output / "jobs.json"
    if args.submit:
        jobs = []
        for index, item in enumerate(prompts, start=1):
            output = f"{index:02d}-{item['id']}.png"
            jobs.append(
                {
                    "id": submit(
                        api_key(),
                        item["prompt"],
                        manifest["negative_prompt"],
                        manifest["size"],
                        index,
                    ),
                    "output": output,
                }
            )
            print(output)
        jobs_path.write_text(json.dumps(jobs, indent=2) + "\n")
        return
    if args.collect:
        jobs = json.loads(jobs_path.read_text())
        print(f"{collect(api_key(), jobs, args.output)}/{len(jobs)} complete")
        return
    for index, item in enumerate(prompts, start=1):
        output = args.output / f"{index:02d}-{item['id']}.png"
        for attempt in range(3):
            try:
                print(f"requesting {item['id']} ({attempt + 1}/3)", flush=True)
                image = generate(
                    api_key(),
                    item["prompt"],
                    manifest["negative_prompt"],
                    manifest["size"],
                    index + attempt * len(prompts),
                )
                print(f"downloaded {item['id']} ({len(image)} bytes)", flush=True)
                output.write_bytes(image)
                break
            except RuntimeError:
                if attempt == 2:
                    raise
                time.sleep(2)
        print(output.name)


if __name__ == "__main__":
    main()
