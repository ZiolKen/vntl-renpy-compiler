from __future__ import annotations
from pathlib import Path
from typing import List, Tuple
from app.utils import run_cmd, which_any

def extract_rpa_with_unrpa(archives: List[Path], out_dir: Path) -> Tuple[List[Path], List[str]]:
    logs: List[str] = []
    produced_dirs: List[Path] = []

    for arc in archives:
        target = out_dir / f"rpa_extract/{arc.stem}"
        target.mkdir(parents=True, exist_ok=True)

        cmd = which_any(["unrpa"])
        args = [cmd, "-m", "-p", str(target), str(arc)] if cmd else ["python", "-m", "unrpa", "-m", "-p", str(target), str(arc)]

        code, out, err = run_cmd(args, timeout_s=300)
        logs.append(f"$ {' '.join(args)}")
        if out.strip(): logs.append(out)
        if err.strip(): logs.append(err)
        if code == 0:
            produced_dirs.append(target)
        else:
            logs.append(f"[unrpa] failed ({code}) for {arc.name}")

    return produced_dirs, logs

def extract_rpi_with_rpatool(rpi_files: List[Path], input_dir: Path, out_dir: Path) -> Tuple[List[Path], List[str]]:
    logs: List[str] = []
    produced_dirs: List[Path] = []
    cmd = which_any(["rpatool"]) or "rpatool"

    for rpi in rpi_files:
        target = out_dir / f"rpi_extract/{rpi.stem}"
        target.mkdir(parents=True, exist_ok=True)
        tried: List[Path] = []

        def _try_extract(archive: Path) -> int:
            args = [cmd, "-o", str(target), "-x", str(archive)]
            code, out, err = run_cmd(args, timeout_s=300)
            logs.append(f"$ {' '.join(args)}")
            if out.strip(): logs.append(out)
            if err.strip(): logs.append(err)
            return code

        code = _try_extract(rpi)
        tried.append(rpi)

        if code != 0:
            matching = input_dir / f"{rpi.stem}.rpa"
            if matching.exists() and matching not in tried:
                logs.append(f"[rpatool] .rpi extract failed; trying matching data archive: {matching.name}")
                code = _try_extract(matching)
                tried.append(matching)

        if code == 0:
            produced_dirs.append(target)
        else:
            logs.append(f"[rpatool] failed ({code}) for {', '.join(p.name for p in tried)}")

    return produced_dirs, logs
