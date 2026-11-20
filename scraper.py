"""Resumable extractor for the public NPPES NPI Registry (US healthcare provider registry).

The API returns at most MAX_SKIP + PAGE records per query, so the scope is split into
partitions (postal-code prefix -> full postal code -> provider type -> name prefix)
until every partition fits under that cap. Progress is checkpointed in SQLite, so the
run can be stopped and restarted without re-fetching finished partitions.
"""

import argparse
import json
import logging
import sqlite3
import string
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import requests

API = "https://npiregistry.cms.hhs.gov/api/"
PAGE = 200
MAX_SKIP = 1000
USER_AGENT = "npi-registry-demo-extractor/1.0"
LETTERS = string.ascii_lowercase
ALNUM = string.ascii_lowercase + string.digits

log = logging.getLogger("scraper")


class RateLimiter:
    def __init__(self, per_second):
        self.interval = 1.0 / per_second
        self.lock = threading.Lock()
        self.next_slot = time.monotonic()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            slot = max(now, self.next_slot)
            self.next_slot = slot + self.interval
        time.sleep(max(0.0, slot - now))


class Client:
    def __init__(self, rate, retries=6):
        self.limiter = RateLimiter(rate)
        self.retries = retries
        self.local = threading.local()
        self.requests_made = 0

    def _session(self):
        if not hasattr(self.local, "session"):
            self.local.session = requests.Session()
            self.local.session.headers["User-Agent"] = USER_AGENT
        return self.local.session

    def fetch(self, params, skip):
        query = {"version": "2.1", "limit": PAGE, "skip": skip, **params}
        for attempt in range(self.retries):
            self.limiter.wait()
            self.requests_made += 1
            try:
                resp = self._session().get(API, params=query, timeout=60)
                if resp.status_code == 200:
                    body = resp.json()
                    if "Errors" in body:
                        raise ValueError(f"API error for {query}: {body['Errors']}")
                    return body.get("results", [])
                if resp.status_code not in (429, 500, 502, 503, 504):
                    resp.raise_for_status()
            except (
                requests.ConnectionError,
                requests.Timeout,
                json.JSONDecodeError,
            ) as exc:
                log.warning("retry %s for %s: %s", attempt + 1, query, exc)
            time.sleep(min(60, 2**attempt))
        raise RuntimeError(f"gave up after {self.retries} attempts: {query}")


def partition_params(part, state):
    params = {"state": state, "address_purpose": "LOCATION", "postal_code": part["zip"]}
    if part.get("type"):
        params["enumeration_type"] = part["type"]
    if part.get("name"):
        field = "last_name" if part["type"] == "NPI-1" else "organization_name"
        params[field] = part["name"] + "*"
    return params


def children(part):
    """Next level of the partition tree, or [] when it cannot be split further."""
    zip_ = part["zip"]
    if zip_.endswith("*"):
        prefix = zip_[:-1]
        if len(prefix) < 4:
            return [{"zip": f"{prefix}{d}*"} for d in string.digits]
        return [{"zip": f"{prefix}{d}"} for d in string.digits]
    if not part.get("type"):
        return [{"zip": zip_, "type": t} for t in ("NPI-1", "NPI-2")]
    if not part.get("name"):
        first = LETTERS if part["type"] == "NPI-1" else ALNUM
        return [{**part, "name": a + b} for a in first for b in first]
    if len(part["name"]) < 3:
        return [{**part, "name": part["name"] + c} for c in ALNUM]
    return []


def key_of(part):
    return "|".join([part["zip"], part.get("type", ""), part.get("name", "")])


def process(client, part, state):
    """Returns (records, capped). A capped partition holds more than the API will page through."""
    params = partition_params(part, state)
    records = client.fetch(params, 0)
    if len(records) < PAGE:
        return records, False
    tail = client.fetch(params, MAX_SKIP)
    records.extend(tail)
    if len(tail) == PAGE:
        return records, True
    for skip in range(PAGE, MAX_SKIP, PAGE):
        page = client.fetch(params, skip)
        records.extend(page)
        if len(page) < PAGE:
            break
    return records, False


def open_db(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS partitions (
            key TEXT PRIMARY KEY, spec TEXT NOT NULL, status TEXT NOT NULL,
            fetched INTEGER DEFAULT 0, finished_at TEXT);
        CREATE TABLE IF NOT EXISTS records (
            npi TEXT PRIMARY KEY, payload TEXT NOT NULL, partition TEXT NOT NULL, fetched_at TEXT NOT NULL);
        """
    )
    return db


def add_partitions(db, parts):
    db.executemany(
        "INSERT OR IGNORE INTO partitions (key, spec, status) VALUES (?, ?, 'pending')",
        [(key_of(p), json.dumps(p)) for p in parts],
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state", default="TX")
    ap.add_argument(
        "--zip-prefixes",
        nargs="+",
        required=True,
        help="3-digit postal prefixes, e.g. 770 771",
    )
    ap.add_argument("--db", default="data/npi.sqlite")
    ap.add_argument("--rate", type=float, default=5.0, help="max requests per second")
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    db = open_db(args.db)
    add_partitions(db, [{"zip": f"{p}*"} for p in args.zip_prefixes])
    db.commit()

    client = Client(args.rate)
    pending = [
        json.loads(r[0])
        for r in db.execute("SELECT spec FROM partitions WHERE status='pending'")
    ]
    log.info("starting with %d pending partitions", len(pending))
    started = time.monotonic()
    done_count = 0

    with ThreadPoolExecutor(args.workers) as pool:
        running = {}
        while pending or running:
            while pending and len(running) < args.workers * 4:
                part = pending.pop()
                running[pool.submit(process, client, part, args.state)] = part
            finished, _ = wait(running, return_when=FIRST_COMPLETED)
            for fut in finished:
                part = running.pop(fut)
                key = key_of(part)
                try:
                    records, capped = fut.result()
                except Exception as exc:
                    log.error(
                        "partition %s failed, left pending for the next run: %s",
                        key,
                        exc,
                    )
                    continue
                now = time.strftime("%Y-%m-%dT%H:%M:%S")
                db.executemany(
                    "INSERT OR REPLACE INTO records (npi, payload, partition, fetched_at) VALUES (?, ?, ?, ?)",
                    [
                        (
                            str(r["number"]),
                            json.dumps(r, separators=(",", ":")),
                            key,
                            now,
                        )
                        for r in records
                    ],
                )
                status = "done"
                if capped:
                    kids = children(part)
                    if kids:
                        add_partitions(db, kids)
                        pending.extend(kids)
                        status = "split"
                    else:
                        status = "truncated"
                        log.warning(
                            "partition %s exceeds the API cap and cannot be split further",
                            key,
                        )
                db.execute(
                    "UPDATE partitions SET status=?, fetched=?, finished_at=? WHERE key=?",
                    (status, len(records), now, key),
                )
                db.commit()
                done_count += 1
                if done_count % 200 == 0:
                    total = db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
                    log.info(
                        "partitions done=%d queued=%d | unique records=%d | requests=%d | %.0fs",
                        done_count,
                        len(pending) + len(running),
                        total,
                        client.requests_made,
                        time.monotonic() - started,
                    )

    total = db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    left = db.execute(
        "SELECT COUNT(*) FROM partitions WHERE status='pending'"
    ).fetchone()[0]
    log.info(
        "finished: %d unique records, %d requests, %d partitions still pending, %.0fs",
        total,
        client.requests_made,
        left,
        time.monotonic() - started,
    )


if __name__ == "__main__":
    main()
