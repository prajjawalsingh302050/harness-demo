"""Runtime sensor: send traffic to the app and measure latency and errors (plus DB queries for diagnosis).

    python scripts/collect_runtime.py --base-url http://127.0.0.1:8000 --out reports/runtime-local.json
"""
import argparse
import asyncio
import json
import random
import re
import time
from pathlib import Path

import httpx

N_PEOPLE = 10_000


def pick_request(rnd):
    roll = rnd.random()
    if roll < 0.4:
        # The "Load 5000 people" button.
        return "people", "/api/people?limit=5000"
    if roll < 0.9:
        # About 20% of person lookups use an ID that does not exist.
        pid = rnd.randint(1, N_PEOPLE) if rnd.random() < 0.8 else rnd.randint(N_PEOPLE + 1, N_PEOPLE * 2)
        return "person", f"/api/people/{pid}"
    return "health", "/api/health"


def percentile(values, pct):
    if not values:
        return 0.0
    values = sorted(values)
    k = max(0, min(len(values) - 1, round(pct / 100 * (len(values) - 1))))
    return round(values[k], 1)


async def worker(client, deadline, samples, rnd):
    while time.monotonic() < deadline:
        name, path = pick_request(rnd)
        started = time.perf_counter()
        try:
            try:
                response = await client.get(path)
            except (httpx.ReadError, httpx.RemoteProtocolError):
                # The server closed a pooled keep-alive connection (it does after a 500). Retry once, like a browser.
                started = time.perf_counter()
                response = await client.get(path)
            status = response.status_code
            queries = int(response.headers.get("x-db-queries", 0))
            match = re.search(r"db;dur=([\d.]+)", response.headers.get("server-timing", ""))
            db_ms = float(match.group(1)) if match else None
        except httpx.HTTPError:
            status, queries, db_ms = 0, 0, None
        samples.append({
            "endpoint": name,
            "status": status,
            "ms": (time.perf_counter() - started) * 1000,
            "queries": queries,
            "db_ms": db_ms,
        })


async def run(base_url, duration, concurrency, seed):
    samples = []
    async with httpx.AsyncClient(base_url=base_url, timeout=30, follow_redirects=True) as client:
        for _ in range(3):  # warm-up so cold starts do not skew the numbers
            try:
                await client.get("/api/health")
            except httpx.HTTPError:
                pass
        deadline = time.monotonic() + duration
        await asyncio.gather(*(
            worker(client, deadline, samples, random.Random(seed + i)) for i in range(concurrency)
        ))
    return samples


def summarise(samples, base_url, duration):
    by_endpoint = {}
    for name in ("people", "person", "health"):
        rows = [s for s in samples if s["endpoint"] == name]
        latencies = [s["ms"] for s in rows]
        db = [s["db_ms"] for s in rows if s["db_ms"] is not None]
        by_endpoint[name] = {
            "requests": len(rows),
            "p50_ms": percentile(latencies, 50),
            "p95_ms": percentile(latencies, 95),
            "db_p95_ms": percentile(db, 95),
            "avg_db_queries": round(sum(s["queries"] for s in rows) / len(rows), 1) if rows else 0,
            "errors_5xx": sum(1 for s in rows if s["status"] >= 500 or s["status"] == 0),
        }
    total = len(samples)
    errors = sum(1 for s in samples if s["status"] >= 500 or s["status"] == 0)
    return {
        "base_url": base_url,
        "duration_s": duration,
        "requests": total,
        "error_rate_pct": round(100 * errors / total, 2) if total else 0,
        "by_endpoint": by_endpoint,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--duration", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    samples = asyncio.run(run(args.base_url.rstrip("/"), args.duration, args.concurrency, args.seed))
    summary = summarise(samples, args.base_url, args.duration)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(summary, indent=2))
    people = summary["by_endpoint"]["people"]
    print(f"{args.base_url}: {summary['requests']} requests, errors {summary['error_rate_pct']}%, "
          f"5000-people p95 {people['p95_ms']} ms, {people['avg_db_queries']} queries/request")


if __name__ == "__main__":
    main()
