from __future__ import annotations
import os, re, shutil, subprocess, zipfile
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

SAFE_PATH_RE = re.compile(r"^[a-zA-Z0-9_\-./]*$")

def ensure_safe_relpath(p: str) -> str:
    if p is None:
        raise ValueError("Invalid path")
    p = p.strip()
    if p == "":
        raise ValueError("Invalid path")
    if not SAFE_PATH_RE.match(p) or p.startswith("/") or ".." in Path(p).parts:
        raise ValueError("Invalid path")
    return p

def ensure_safe_relpath_allow_empty(p: str) -> str:
    if p is None or p == "":
        return ""
    return ensure_safe_relpath(p)

def which_any(names: Iterable[str]) -> Optional[str]:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None

def run_cmd(args: List[str], cwd: Optional[Path] = None, timeout_s: int = 300) -> Tuple[int, str, str]:
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_s,
    )
    return proc.returncode, proc.stdout, proc.stderr

def is_zip_path(p: Path) -> bool:
    return p.suffix.lower() == ".zip"

def extract_zip(zip_path: Path, out_dir: Path) -> None:
    with zipfile.ZipFile(zip_path, "r") as z:
        out_root = out_dir.resolve()
        for info in z.infolist():
            target = (out_dir / info.filename).resolve()
            if not str(target).startswith(str(out_root)):
                raise ValueError("Unsafe ZIP entry detected")
        z.extractall(out_dir)

def walk_tree(root: Path) -> list[dict]:
    root = root.resolve()

    def node_for_dir(d: Path) -> dict:
        children = []
        for p in sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
            if p.is_dir():
                children.append(node_for_dir(p))
            else:
                children.append({
                    "type": "file",
                    "name": p.name,
                    "path": str(p.relative_to(root)).replace(os.sep, "/"),
                    "size": p.stat().st_size,
                })
        return {
            "type": "dir",
            "name": d.name if d != root else "/",
            "path": str(d.relative_to(root)).replace(os.sep, "/") if d != root else "",
            "children": children,
        }

    return [node_for_dir(root)]
