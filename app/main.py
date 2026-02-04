from __future__ import annotations

import asyncio
import mimetypes
import os
import shutil
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from app.jobs import cleanup_jobs, job_paths, new_job, touch_meta
from app.utils import (
    ensure_safe_relpath,
    ensure_safe_relpath_allow_empty,
    extract_zip,
    is_zip_path,
    walk_tree,
)
from app.processors.decompile import decompile_rpyc_files
from app.processors.extract import extract_rpa_with_unrpa, extract_rpi_with_rpatool
from app.processors.pack import pack_rpa_from_dir

APP_NAME = "VNTl RenPy Compiler"
JOB_TTL_SECONDS = int(os.environ.get("JOB_TTL_SECONDS", "3600"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "11111"))

app = FastAPI(title=APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

class JobCreateResponse(BaseModel):
    job_id: str
    input_tree: list[dict]

class ProcessResponse(BaseModel):
    job_id: str
    mode: str
    output_tree: list[dict]
    logs: list[str]

class SaveRequest(BaseModel):
    content: str

class MoveRequest(BaseModel):
    where: Literal["input", "output"] = "output"
    src: str
    dst: str
    overwrite: bool = False

class DeleteRequest(BaseModel):
    where: Literal["input", "output"] = "output"
    path: str

class MkdirRequest(BaseModel):
    where: Literal["input", "output"] = "output"
    path: str

class RepackRequest(BaseModel):
    source_where: Literal["input", "output"] = "output"
    source_path: str = ""
    name: str = "repacked.rpa"
    version: int = 3
    key_hex: str = "0xDEADBEEF"
    padding: int = 0

async def _periodic_cleanup():
    while True:
        try:
            cleanup_jobs(JOB_TTL_SECONDS)
        except Exception:
            pass
        await asyncio.sleep(300)

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(_periodic_cleanup())

@app.get("/health")
def health():
    return {"ok": True, "name": APP_NAME}

@app.post("/api/jobs", response_model=JobCreateResponse)
async def create_job(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    job_id = new_job()
    jp = job_paths(job_id)

    total = 0
    for f in files:
        name = f.filename or "upload.bin"
        safe_name = name.replace("\\", "/").lstrip("/")
        if ".." in Path(safe_name).parts:
            raise HTTPException(status_code=400, detail=f"Unsafe filename: {name}")

        dest = jp.inp / safe_name
        dest.parent.mkdir(parents=True, exist_ok=True)

        with dest.open("wb") as out:
            while True:
                chunk = await f.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_MB * 1024 * 1024:
                    raise HTTPException(status_code=413, detail=f"Upload too large (>{MAX_UPLOAD_MB}MB)")
                out.write(chunk)

        if is_zip_path(dest):
            extract_zip(dest, jp.inp)
            dest.unlink(missing_ok=True)

    touch_meta(job_id)
    return JobCreateResponse(job_id=job_id, input_tree=walk_tree(jp.inp))

@app.get("/api/jobs/{job_id}/tree")
def job_tree(job_id: str, where: Literal["input", "output"] = "output"):
    jp = job_paths(job_id)
    root = jp.out if where == "output" else jp.inp
    if not root.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    touch_meta(job_id)
    return {"job_id": job_id, "where": where, "tree": walk_tree(root)}

@app.post("/api/jobs/{job_id}/process", response_model=ProcessResponse)
def process_job(
    job_id: str,
    mode: Literal["auto", "decompile", "extract_rpa", "extract_rpi", "pack_rpa"] = Query("auto"),
    try_harder: bool = Query(False),
    # pack params
    pack_source_where: Literal["input", "output"] = Query("input"),
    pack_source_path: str = Query(""),  # folder inside where
    pack_name: str = Query("packed.rpa"),
    pack_version: int = Query(3, ge=2, le=3),
    pack_key_hex: str = Query("0xDEADBEEF"),
    pack_padding: int = Query(0, ge=0, le=1_000_000),
):
    jp = job_paths(job_id)
    if not jp.root.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    if jp.out.exists():
        shutil.rmtree(jp.out, ignore_errors=True)
    jp.out.mkdir(parents=True, exist_ok=True)

    logs: list[str] = []
    touch_meta(job_id)

    rpyc_files = list(jp.inp.rglob("*.rpyc"))
    rpa_files = list(jp.inp.rglob("*.rpa"))
    rpi_files = list(jp.inp.rglob("*.rpi"))

    if mode in ("auto", "decompile"):
        if rpyc_files:
            _, l = decompile_rpyc_files(rpyc_files, jp.out, try_harder=try_harder)
            logs += l
        else:
            logs.append("[decompile] No .rpyc files found.")

    if mode in ("auto", "extract_rpa"):
        if rpa_files:
            _, l = extract_rpa_with_unrpa(rpa_files, jp.out)
            logs += l
        else:
            logs.append("[extract_rpa] No .rpa files found.")

    if mode in ("auto", "extract_rpi"):
        if rpi_files:
            _, l = extract_rpi_with_rpatool(rpi_files, jp.inp, jp.out)
            logs += l
        else:
            logs.append("[extract_rpi] No .rpi files found.")

    if mode in ("auto", "pack_rpa"):
        base = jp.inp if pack_source_where == "input" else jp.out
        rel = ensure_safe_relpath_allow_empty(pack_source_path)
        source_dir = (base / rel).resolve()
        if not str(source_dir).startswith(str(base.resolve())):
            raise HTTPException(status_code=400, detail="Invalid pack_source_path")
        out_path, l = pack_rpa_from_dir(
            source_dir=source_dir,
            out_dir=jp.out,
            archive_name=pack_name,
            version=pack_version,
            key_hex=pack_key_hex,
            padding=pack_padding,
        )
        logs += l
        if out_path:
            logs.append(f"[pack] created: {out_path.name}")

    return ProcessResponse(job_id=job_id, mode=mode, output_tree=walk_tree(jp.out), logs=logs)

@app.post("/api/jobs/{job_id}/repack", response_model=ProcessResponse)
def repack_job(job_id: str, payload: RepackRequest = Body(...)):
    jp = job_paths(job_id)
    if not jp.root.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    jp.out.mkdir(parents=True, exist_ok=True)
    logs: list[str] = []
    touch_meta(job_id)

    base = jp.inp if payload.source_where == "input" else jp.out
    rel = ensure_safe_relpath_allow_empty(payload.source_path)
    source_dir = (base / rel).resolve()
    if not str(source_dir).startswith(str(base.resolve())):
        raise HTTPException(status_code=400, detail="Invalid source_path")

    out_path, l = pack_rpa_from_dir(
        source_dir=source_dir,
        out_dir=jp.out,
        archive_name=payload.name,
        version=payload.version,
        key_hex=payload.key_hex,
        padding=payload.padding,
    )
    logs += l
    if out_path:
        logs.append(f"[repack] created: {out_path.name}")

    return ProcessResponse(job_id=job_id, mode="repack", output_tree=walk_tree(jp.out), logs=logs)

@app.get("/api/jobs/{job_id}/file")
def get_file(
    job_id: str,
    path: str = Query(...),
    where: Literal["input", "output"] = Query("output"),
    as_text: bool = Query(True),
):
    jp = job_paths(job_id)
    root = jp.out if where == "output" else jp.inp
    if not root.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    rel = ensure_safe_relpath(path)
    full = (root / rel).resolve()
    if not str(full).startswith(str(root.resolve())) or not full.exists() or not full.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    touch_meta(job_id)

    if as_text:
        if full.stat().st_size > 2 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="File too large to preview")
        data = full.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
        return PlainTextResponse(text)

    mime, _ = mimetypes.guess_type(full.name)
    return FileResponse(full, media_type=mime or "application/octet-stream", filename=full.name)

@app.get("/api/jobs/{job_id}/raw")
def get_raw(
    job_id: str,
    path: str = Query(...),
    where: Literal["input", "output"] = Query("output"),
):
    jp = job_paths(job_id)
    root = jp.out if where == "output" else jp.inp
    if not root.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    rel = ensure_safe_relpath(path)
    full = (root / rel).resolve()
    if not str(full).startswith(str(root.resolve())) or not full.exists() or not full.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    touch_meta(job_id)
    mime, _ = mimetypes.guess_type(full.name)
    return FileResponse(full, media_type=mime or "application/octet-stream")

@app.put("/api/jobs/{job_id}/file")
def save_file(
    job_id: str,
    payload: SaveRequest = Body(...),
    path: str = Query(...),
    where: Literal["input", "output"] = Query("output"),
):
    jp = job_paths(job_id)
    root = jp.out if where == "output" else jp.inp

    rel = ensure_safe_relpath(path)
    full = (root / rel).resolve()
    if not str(full).startswith(str(root.resolve())) or not full.exists() or not full.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    if len(payload.content.encode("utf-8")) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Content too large")

    full.write_text(payload.content, encoding="utf-8")
    touch_meta(job_id)
    return {"ok": True}

@app.post("/api/jobs/{job_id}/fs/move")
def fs_move(job_id: str, payload: MoveRequest = Body(...)):
    jp = job_paths(job_id)
    root = jp.out if payload.where == "output" else jp.inp
    if not root.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    src_rel = ensure_safe_relpath(payload.src)
    dst_rel = ensure_safe_relpath(payload.dst)

    src = (root / src_rel).resolve()
    dst = (root / dst_rel).resolve()

    if not str(src).startswith(str(root.resolve())) or not src.exists():
        raise HTTPException(status_code=404, detail="Source not found")
    if not str(dst).startswith(str(root.resolve())):
        raise HTTPException(status_code=400, detail="Invalid destination")

    if src.is_dir() and str(dst).startswith(str(src)):
        raise HTTPException(status_code=400, detail="Cannot move a folder into itself")

    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists():
        if not payload.overwrite:
            raise HTTPException(status_code=409, detail="Destination exists")
        if dst.is_dir():
            shutil.rmtree(dst, ignore_errors=True)
        else:
            dst.unlink(missing_ok=True)

    shutil.move(str(src), str(dst))
    touch_meta(job_id)
    return {"ok": True}

@app.post("/api/jobs/{job_id}/fs/mkdir")
def fs_mkdir(job_id: str, payload: MkdirRequest = Body(...)):
    jp = job_paths(job_id)
    root = jp.out if payload.where == "output" else jp.inp
    if not root.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    rel = ensure_safe_relpath(payload.path)
    d = (root / rel).resolve()
    if not str(d).startswith(str(root.resolve())):
        raise HTTPException(status_code=400, detail="Invalid path")
    d.mkdir(parents=True, exist_ok=True)
    touch_meta(job_id)
    return {"ok": True}

@app.delete("/api/jobs/{job_id}/fs")
def fs_delete(job_id: str, where: Literal["input", "output"] = Query("output"), path: str = Query(...)):
    jp = job_paths(job_id)
    root = jp.out if where == "output" else jp.inp
    if not root.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    rel = ensure_safe_relpath(path)
    full = (root / rel).resolve()
    if not str(full).startswith(str(root.resolve())) or not full.exists():
        raise HTTPException(status_code=404, detail="Not found")

    if full.is_dir():
        shutil.rmtree(full, ignore_errors=True)
    else:
        full.unlink(missing_ok=True)

    touch_meta(job_id)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/download")
def download(
    job_id: str,
    where: Literal["input", "output"] = Query("output"),
    zip_all: bool = Query(False, alias="zip"),
    path: Optional[str] = Query(None),
):
    jp = job_paths(job_id)
    root = jp.out if where == "output" else jp.inp
    if not root.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    touch_meta(job_id)

    if path:
        rel = ensure_safe_relpath(path)
        full = (root / rel).resolve()
        if not str(full).startswith(str(root.resolve())) or not full.exists() or not full.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        mime, _ = mimetypes.guess_type(full.name)
        return FileResponse(full, media_type=mime or "application/octet-stream", filename=full.name)

    if not zip_all:
        raise HTTPException(status_code=400, detail="Set zip=1 or provide path")

    zip_path = jp.root / f"{where}.zip"
    if zip_path.exists():
        zip_path.unlink(missing_ok=True)

    import zipfile
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for f in root.rglob("*"):
            if f.is_file():
                z.write(f, arcname=str(f.relative_to(root)).replace(os.sep, "/"))

    return FileResponse(zip_path, media_type="application/zip", filename=f"{where}.zip")
