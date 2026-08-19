from __future__ import annotations
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple
from app.utils import run_cmd, which_any

def pack_rpa_from_dir(
    source_dir: Path,
    out_dir: Path,
    archive_name: str = "packed.rpa",
    version: int = 3,
    key_hex: str = "0xDEADBEEF",
    padding: int = 0
) -> Tuple[Optional[Path], List[str]]:
    """Create an .rpa from a directory. Paths inside archive are relative to source_dir."""
    logs: List[str] = []
    if not source_dir.exists() or not source_dir.is_dir():
        logs.append(f"[pack] Source directory not found: {source_dir}")
        return None, logs

    try:
        key_int = int(str(key_hex), 16)
    except Exception:
        logs.append(f"[pack] Invalid key_hex: {key_hex!r} (expected hex like 0x1234)")
        return None, logs

    # Scratch copy lives outside out_dir (system temp) so it never lingers in
    # the job's output tree / download zip. Previously this was written to
    # out_dir/_packroot and never removed, so every pack (and every "auto"
    # run, which used to always pack too) left a full copy of the source
    # directory behind permanently.
    packroot = Path(tempfile.mkdtemp(prefix="rpapack_"))
    try:
        for src in source_dir.rglob("*"):
            if src.is_dir():
                continue
            rel = src.relative_to(source_dir)
            dst = packroot / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())

        entries = [p.name for p in packroot.iterdir()]
        if not entries:
            logs.append("[pack] Source directory is empty.")
            return None, logs

        cmd = which_any(["rpatool"]) or "rpatool"
        out_path = out_dir / archive_name
        if out_path.exists():
            out_path.unlink(missing_ok=True)

        # IMPORTANT: rpatool parses -k as a hex string (int(value, 16)).
        # Passing a decimal string here (the old `str(key_int)`) makes
        # rpatool re-interpret those decimal digits as hex, silently
        # producing a *different* obfuscation key than the one requested —
        # every packed .rpa was built with the wrong key. hex(key_int)
        # round-trips correctly since Python's int(x, 16) accepts "0x..." .
        args: List[str] = [
            cmd, "-2" if int(version) == 2 else "-3",
            "-k", hex(key_int),
            "-p", str(int(padding)),
            "-c", str(out_path),
        ] + entries

        code, out, err = run_cmd(args, cwd=packroot, timeout_s=300)
        logs.append(f"$ (cwd={packroot}) {' '.join(args)}")
        if out.strip(): logs.append(out)
        if err.strip(): logs.append(err)

        if code != 0 or not out_path.exists():
            logs.append(f"[pack] rpatool failed ({code}).")
            return None, logs

        return out_path, logs
    finally:
        shutil.rmtree(packroot, ignore_errors=True)
