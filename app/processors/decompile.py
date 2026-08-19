from __future__ import annotations
from pathlib import Path
from typing import List, Tuple

def decompile_rpyc_files(
    rpyc_files: List[Path],
    input_root: Path,
    out_dir: Path,
    try_harder: bool = False,
) -> Tuple[List[Path], List[str]]:
    logs: List[str] = []
    produced: List[Path] = []

    import unrpyc as _unrpyc

    work_dir = out_dir / "decompiled"
    work_dir.mkdir(parents=True, exist_ok=True)

    for src in rpyc_files:
        # Preserve the path relative to the input root instead of flattening
        # to just the basename. RenPy translation projects routinely have
        # same-named files across many folders (e.g. game/script.rpyc,
        # game/tl/english/script.rpyc, game/tl/vietnamese/script.rpyc) —
        # flattening silently overwrote earlier results with later ones.
        try:
            rel = src.relative_to(input_root)
        except ValueError:
            rel = Path(src.name)

        dst_rpyc = work_dir / rel
        dst_rpyc.parent.mkdir(parents=True, exist_ok=True)
        dst_rpyc.write_bytes(src.read_bytes())

        ctx = _unrpyc.Context()
        try:
            _unrpyc.decompile_rpyc(dst_rpyc, ctx, overwrite=True, try_harder=try_harder)
            logs.extend(ctx.log_contents)
            out_text = dst_rpyc.with_suffix(".rpy")
            if out_text.exists():
                produced.append(out_text)
                # Clean up the intermediate .rpyc copy once we have the
                # decompiled .rpy so the output tree isn't cluttered with
                # duplicate binary copies of the input.
                dst_rpyc.unlink(missing_ok=True)
        except Exception as e:
            logs.append(f"[unrpyc] error on {rel.as_posix()}: {e!r}")
            # Keep dst_rpyc around on failure so it can be inspected/retried.

    return produced, logs
