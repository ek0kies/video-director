"""Persistent remote-run manifest and checkpoint helpers for Video Director."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional


REMOTE_RUN_MANIFEST_VERSION = 1


def stable_hash(value: Any) -> str:
    """Hash nested data deterministically for checkpoint matching."""
    encoded = json.dumps(_normalize_json(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_json(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, list):
        return [_normalize_json(item) for item in value]
    return value


class RemoteRunManifestStore:
    """Persist remote stage results so cloud production can resume safely."""

    def __init__(
        self,
        path: Path,
        *,
        job_id: str,
        dry_run: bool,
        enabled: bool,
        resume_enabled: bool,
    ) -> None:
        self.path = path
        self.job_id = job_id
        self.dry_run = dry_run
        self.enabled = enabled
        self.resume_enabled = resume_enabled
        self._data = self._load_or_initialize()

    @property
    def data(self) -> Dict[str, Any]:
        return copy.deepcopy(self._data)

    def bind_base_request_id(self, fallback: str) -> str:
        runtime = self._data.setdefault("runtime", {})
        existing = str(runtime.get("base_request_id", "")).strip()
        if self.resume_enabled and existing:
            return existing
        runtime["base_request_id"] = fallback
        self._save()
        return fallback

    def get_runtime_stage_success(self, stage_name: str, *, input_hash: str) -> Optional[Dict[str, Any]]:
        if not self.resume_enabled:
            return None
        runtime = self._data.setdefault("runtime", {})
        record = runtime.get(stage_name)
        return self._match_success_record(record, input_hash=input_hash)

    def mark_runtime_stage_reused(self, stage_name: str) -> None:
        runtime = self._data.setdefault("runtime", {})
        record = runtime.get(stage_name)
        if isinstance(record, dict):
            self._mark_reused(record)
            self._save()

    def save_runtime_stage(self, stage_name: str, record: Dict[str, Any]) -> None:
        runtime = self._data.setdefault("runtime", {})
        runtime[stage_name] = record
        self._save()

    def get_segment_stage_success(
        self,
        segment_id: str,
        stage_name: str,
        *,
        input_hash: str,
    ) -> Optional[Dict[str, Any]]:
        if not self.resume_enabled:
            return None
        segment = self._get_segment(segment_id)
        record = segment.get("stages", {}).get(stage_name)
        return self._match_success_record(record, input_hash=input_hash)

    def mark_segment_stage_reused(self, segment_id: str, stage_name: str) -> None:
        segment = self._get_segment(segment_id)
        record = segment.get("stages", {}).get(stage_name)
        if isinstance(record, dict):
            self._mark_reused(record)
            self._save()

    def save_segment_stage(
        self,
        segment_id: str,
        stage_name: str,
        record: Dict[str, Any],
        *,
        segment_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        segment = self._ensure_segment(segment_id, segment_meta=segment_meta)
        segment.setdefault("stages", {})[stage_name] = record
        self._save()

    def patch_segment_stage(
        self,
        segment_id: str,
        stage_name: str,
        patch: Dict[str, Any],
        *,
        segment_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        segment = self._ensure_segment(segment_id, segment_meta=segment_meta)
        current = segment.setdefault("stages", {}).get(stage_name)
        if not isinstance(current, dict):
            current = {"status": "unknown", "updated_at": int(time.time())}
        current.update(patch)
        current["updated_at"] = int(time.time())
        segment["stages"][stage_name] = current
        self._save()

    def _load_or_initialize(self) -> Dict[str, Any]:
        blank = self._blank_manifest()
        if not self.enabled or not self.path.is_file():
            return blank

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logging.warning("remote manifest unreadable, reset to blank: %s", exc)
            return blank

        if not isinstance(raw, dict):
            return blank
        if str(raw.get("job_id", "")).strip() != self.job_id:
            logging.info("remote manifest job_id mismatch, reset to blank: path=%s", self.path)
            return blank
        if bool(raw.get("dry_run", False)) != self.dry_run:
            logging.info("remote manifest dry_run mismatch, reset to blank: path=%s", self.path)
            return blank

        merged = self._blank_manifest()
        merged.update(raw)
        merged["runtime"] = raw.get("runtime", {}) if isinstance(raw.get("runtime"), dict) else {}
        merged["segments"] = raw.get("segments", {}) if isinstance(raw.get("segments"), dict) else {}
        merged["checkpointing"] = {
            "enabled": self.enabled,
            "resume_enabled": self.resume_enabled,
        }
        return merged

    def _blank_manifest(self) -> Dict[str, Any]:
        now = int(time.time())
        return {
            "manifest_version": REMOTE_RUN_MANIFEST_VERSION,
            "job_id": self.job_id,
            "dry_run": self.dry_run,
            "checkpointing": {
                "enabled": self.enabled,
                "resume_enabled": self.resume_enabled,
            },
            "created_at": now,
            "updated_at": now,
            "runtime": {},
            "segments": {},
        }

    def _save(self) -> None:
        if not self.enabled:
            return
        self._data["updated_at"] = int(time.time())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name(f"{self.path.name}.tmp")
        temp_path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.path)

    def _get_segment(self, segment_id: str) -> Dict[str, Any]:
        return self._data.setdefault("segments", {}).setdefault(segment_id, {"segment_id": segment_id, "stages": {}})

    def _ensure_segment(
        self,
        segment_id: str,
        *,
        segment_meta: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        segment = self._get_segment(segment_id)
        if segment_meta:
            for key, value in segment_meta.items():
                segment[key] = value
        segment.setdefault("stages", {})
        return segment

    @staticmethod
    def _match_success_record(record: Any, *, input_hash: str) -> Optional[Dict[str, Any]]:
        if not isinstance(record, dict):
            return None
        if str(record.get("status", "")).strip().lower() != "succeeded":
            return None
        if str(record.get("input_hash", "")).strip() != input_hash:
            return None
        return copy.deepcopy(record)

    @staticmethod
    def _mark_reused(record: Dict[str, Any]) -> None:
        record["reuse_count"] = int(record.get("reuse_count", 0) or 0) + 1
        record["last_reused_at"] = int(time.time())
        result = record.get("result")
        if isinstance(result, dict):
            result["resumed_from_checkpoint"] = True

