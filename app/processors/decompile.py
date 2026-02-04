from __future__ import annotations
from pathlib import Path
from typing import List, Tuple

def decompile_rpyc_files(rpyc_files: List[Path], out_dir: Path, try_harder: bool = False) -> Tuple[List[Path], List[str]]:
    logs: List[str] = []
    produced: List[Path] = []

    import unrpyc as _unrpyc

    work_dir = out_dir / "decompiled"
    work_dir.mkdir(parents=True, exist_ok=True)

    for src in rpyc_files:
        dst_rpyc = work_dir / src.name
        dst_rpyc.write_bytes(src.read_bytes())

        ctx = _unrpyc.Context()
        try:
            _unrpyc.decompile_rpyc(dst_rpyc, ctx, overwrite=True, try_harder=try_harder)
            logs.extend(ctx.log_contents)
            out_text = dst_rpyc.with_suffix(".rpy")
            if out_text.exists():
                produced.append(out_text)
        except Exception as e:
            logs.append(f"[unrpyc] error on {src.name}: {e!r}")

    return produced, logs
