#!/usr/bin/env python3
"""Summarize a Video Director run from workflow output or latest_run.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _resolve_paths(source: Path) -> Tuple[Path, Path, str]:
    if source.is_dir():
        latest = source / "latest_run.json"
        if latest.is_file():
            source = latest
        elif (source / "Timeline_Model.json").is_file():
            if source.parent.name == "runs":
                return source.parent.parent, source, source.name
            return source, source, ""
        else:
            raise FileNotFoundError(f"unsupported directory input: {source}")

    payload = _read_json(source)
    if "job_root" in payload and "output_root" in payload:
        return Path(payload["job_root"]), Path(payload["output_root"]), str(payload.get("run_id", ""))
    if "output_root" in payload and "job_root" in payload:
        return Path(payload["job_root"]), Path(payload["output_root"]), str(payload.get("run_id", ""))
    raise ValueError(f"unsupported json input: {source}")


def _artifact(path: Path) -> Dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
    }


def _load_targets(targets_root: Path) -> List[Dict[str, Any]]:
    if not targets_root.is_dir():
        return []
    results: List[Dict[str, Any]] = []
    for child in sorted(targets_root.iterdir()):
        if not child.is_dir():
            continue
        results.append(
            {
                "name": child.name,
                "path": str(child),
                "files": sorted(item.name for item in child.iterdir()),
            }
        )
    return results


def _beat_count(path: Path) -> Optional[int]:
    if not path.is_file():
        return None
    payload = _read_json(path)
    beats = payload.get("beats")
    return len(beats) if isinstance(beats, list) else None


def summarize_run(source: Path) -> Dict[str, Any]:
    resolved_source = source.expanduser().resolve()
    job_root, output_root, run_id = _resolve_paths(resolved_source)
    beat_sheet_path = output_root / "BeatSheet.json"
    return {
        "job_root": str(job_root),
        "output_root": str(output_root),
        "run_id": run_id,
        "artifacts": {
            "latest_run": _artifact(job_root / "latest_run.json"),
            "config_snapshot": _artifact(output_root / "config.snapshot.json"),
            "production_bundle": _artifact(output_root / "Production_Bundle.json"),
            "beat_sheet": _artifact(beat_sheet_path),
            "edl": _artifact(output_root / "Edit_Decision_List.json"),
            "timeline": _artifact(output_root / "Timeline_Model.json"),
            "remote_manifest": _artifact(job_root / "Remote_Run_Manifest.json"),
        },
        "beat_count": _beat_count(beat_sheet_path),
        "targets": _load_targets(output_root / "targets"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize a Video Director run")
    parser.add_argument("source", help="path to latest_run.json or a workflow result json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = summarize_run(Path(args.source))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
