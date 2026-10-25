from __future__ import annotations

import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

FAKE_ENGINE = Path(__file__).with_name("fake_engine.py")
FINISHED = ("succeeded", "failed")


def fake_engine_command(*flags: str) -> list[str]:
    return [sys.executable, str(FAKE_ENGINE), *flags]


def wait_for_job(client: TestClient, job_id: str, timeout: float = 15.0) -> dict:
    """Poll a job until it has finished and return its last state."""
    deadline = time.monotonic() + timeout
    while True:
        body = client.get(f"/v1/analyses/{job_id}").json()
        if body["status"] in FINISHED:
            return body
        if time.monotonic() > deadline:
            raise AssertionError(f"job {job_id} still {body['status']}")
        time.sleep(0.02)


def wait_for_status(
    client: TestClient, job_id: str, status: str, timeout: float = 15.0
) -> None:
    deadline = time.monotonic() + timeout
    while client.get(f"/v1/analyses/{job_id}").json()["status"] != status:
        if time.monotonic() > deadline:
            raise AssertionError(f"job {job_id} never became {status}")
        time.sleep(0.02)
