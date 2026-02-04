from __future__ import annotations
import os, time, uuid, shutil
from dataclasses import dataclass
from pathlib import Path

JOB_ROOT = Path(os.environ.get("JOB_ROOT", "/tmp/renpy-web-tool-jobs")).resolve()
JOB_ROOT.mkdir(parents=True, exist_ok=True)

def now_s() -> int:
    return int(time.time())

@dataclass
class JobPaths:
    root: Path
    inp: Path
    out: Path
    meta: Path

def job_paths(job_id: str) -> JobPaths:
    root = (JOB_ROOT / job_id).resolve()
    return JobPaths(root=root, inp=root/"input", out=root/"output", meta=root/"meta.json")

def new_job() -> str:
    job_id = uuid.uuid4().hex
    jp = job_paths(job_id)
    jp.inp.mkdir(parents=True, exist_ok=True)
    jp.out.mkdir(parents=True, exist_ok=True)
    touch_meta(job_id)
    return job_id

def touch_meta(job_id: str) -> None:
    jp = job_paths(job_id)
    if jp.meta.exists():
        os.utime(jp.meta, None)
    else:
        jp.meta.write_text("{}", encoding="utf-8")

def cleanup_jobs(ttl_seconds: int) -> int:
    removed = 0
    cutoff = now_s() - ttl_seconds
    for job_dir in JOB_ROOT.iterdir():
        try:
            meta = job_dir / "meta.json"
            ts = int(meta.stat().st_mtime) if meta.exists() else int(job_dir.stat().st_mtime)
            if ts < cutoff:
                shutil.rmtree(job_dir, ignore_errors=True)
                removed += 1
        except Exception:
            continue
    return removed
