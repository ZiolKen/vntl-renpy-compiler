# VNTl Ren'Py Compiler (FastAPI)

API server for:
- Decompile `.rpyc` with **unrpyc**
- Extract `.rpa` with **unrpa**
- Extract `.rpi` (usually index) with **rpatool**
- Pack/Repack `.rpa` from any folder (after edits) with **rpatool**

Note: `rpatool` is vendored as a standalone script under `vendor/rpatool` because
the upstream project is not packaged for pip (no `setup.py`/`pyproject.toml`).

> Legal note: use only with files you own / have permission to modify.

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Docker
```bash
docker build -t renpy-backend .
docker run -p 8000:8000 renpy-backend
```

## Deploy
Best: Render/Railway/Fly/any Docker host. (This backend needs temp disk + subprocess.)

## API
- `POST /api/jobs` (multipart `files[]`) -> create job, upload files or ZIP(s)
- `POST /api/jobs/{id}/process?mode=auto|decompile|extract_rpa|extract_rpi|pack_rpa`
  - pack params:
    - `pack_source_where=input|output`
    - `pack_source_path=<folder path>` (relative, e.g. `rpa_extract/game` or `res` or empty)
    - `pack_name=packed.rpa`
    - `pack_version=2|3`
    - `pack_key_hex=0xDEADBEEF`
    - `pack_padding=0`
- `POST /api/jobs/{id}/repack` (JSON body) -> convenience wrapper around `pack_rpa_from_dir`
- `GET /api/jobs/{id}/tree?where=input|output`
- `GET /api/jobs/{id}/file?where=output&path=...` (text preview)
- `PUT /api/jobs/{id}/file?where=output&path=...` (save text)
- `GET /api/jobs/{id}/raw?where=output&path=...` (stream for image/audio/video preview)
- `GET /api/jobs/{id}/download?where=output&zip=1` (download ZIP)
- `GET /api/jobs/{id}/download?where=output&path=...` (download single file)
