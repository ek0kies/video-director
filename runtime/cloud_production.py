"""Cloud production interface migration for Video Director."""

from __future__ import annotations

import base64
import copy
import json
import logging
import math
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .models import AudioClip, AvatarClip, Beat, ProductionBundle
from .remote_manifest import RemoteRunManifestStore, stable_hash
from .retrying import RetryExhaustedError, RetryPolicy, call_with_retry


DEFAULT_CN_CHARS_PER_SECOND = 4.0
DOUBAO_TTS2_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
DOUBAO_TTS2_RESOURCE_ID = "seed-tts-2.0"
VOLATILE_FINGERPRINT_KEYS = {"request_id", "requestid", "timestamp", "nonce", "expires", "updated_at", "created_at"}


class CloudProductionError(RuntimeError):
    """Raised when cloud production cannot finish successfully."""


class TransientRequestError(RuntimeError):
    """Raised when an HTTP request is retryable."""


class TransientCloudStorageError(RuntimeError):
    """Raised when a TOS operation is retryable."""


def get_nested(data: Any, path: str, default: Any = None) -> Any:
    """Resolve a dotted path from nested dictionaries."""
    if not path:
        return data
    current = data
    for key in path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def render_template(value: Any, context: Dict[str, Any]) -> Any:
    """Recursively render a simple `{{key}}` string template."""
    if isinstance(value, str):
        if value.startswith("{{") and value.endswith("}}") and value.count("{{") == 1 and value.count("}}") == 1:
            key = value[2:-2].strip()
            if key in context:
                return context[key]
        rendered = value
        for key, val in context.items():
            rendered = rendered.replace("{{" + key + "}}", str(val))
        return rendered
    if isinstance(value, dict):
        return {k: render_template(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render_template(item, context) for item in value]
    return value


def prune_empty(value: Any) -> Any:
    """Drop empty string/None/list/dict values from payloads."""
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            pruned = prune_empty(item)
            if pruned is None:
                continue
            if isinstance(pruned, str) and pruned == "":
                continue
            if isinstance(pruned, (list, dict)) and len(pruned) == 0:
                continue
            out[key] = pruned
        return out
    if isinstance(value, list):
        items = [prune_empty(item) for item in value]
        return [item for item in items if item is not None and not (isinstance(item, str) and item == "")]
    return value


@dataclass
class TaskResult:
    """Async task response."""

    stage: str
    task_id: str
    response: Dict[str, Any]


class HttpClient:
    """Thin JSON HTTP client reused by generic trigger/status endpoints."""

    def __init__(self, config: Dict[str, Any], *, dry_run: bool, retry_policy: RetryPolicy):
        self.base_url = str(config["base_url"]).rstrip("/")
        self.timeout = int(config.get("timeout_seconds", 30))
        self.auth = config.get("auth", {})
        self.dry_run = dry_run
        self.retry_policy = retry_policy

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Accept": "application/json"}
        auth_type = self.auth.get("type", "none")
        if auth_type == "bearer" and self.auth.get("token"):
            headers["Authorization"] = f"Bearer {self.auth['token']}"
        elif auth_type == "api_key" and self.auth.get("api_key"):
            name = self.auth.get("header_name", "X-API-Key")
            headers[name] = self.auth["api_key"]
        return headers

    def request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = self._headers()
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        if self.dry_run:
            logging.info("[dry-run] %s %s payload=%s", method, url, payload)
            return {"dry_run": True, "url": url, "payload": payload or {}}

        def _request_once(_: int) -> Dict[str, Any]:
            req = urllib.request.Request(url=url, method=method.upper(), headers=headers, data=data)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    charset = resp.headers.get_content_charset() or "utf-8"
                    raw = resp.read().decode(charset)
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="ignore")
                if exc.code in self.retry_policy.retryable_http_statuses:
                    raise TransientRequestError(f"HTTP {exc.code} {method} {path} retryable: {body}") from exc
                raise CloudProductionError(f"HTTP {exc.code} {method} {path} failed: {body}") from exc
            except urllib.error.URLError as exc:
                raise TransientRequestError(f"Request {method} {path} failed: {exc}") from exc

        try:
            return call_with_retry(
                _request_once,
                policy=self.retry_policy,
                should_retry=lambda exc: isinstance(exc, TransientRequestError),
                label=f"{method.upper()} {path}",
                logger=logging.warning,
            )
        except RetryExhaustedError as exc:
            raise CloudProductionError(str(exc)) from exc


class CloudProductionGenerator:
    """Produce TTS and avatar assets by calling migrated cloud interfaces."""

    def __init__(
        self,
        config: Dict[str, Any],
        *,
        cwd: Path,
        output_root: Path,
        manifest_root: Optional[Path] = None,
        dry_run: bool,
    ):
        self.config = config
        self.cwd = cwd
        self.output_root = output_root
        self.dry_run = dry_run
        self.manifest_root = manifest_root or output_root
        self.poll_interval = int(config.get("poll_interval_seconds", 2))
        self.max_poll_attempts = int(config.get("max_poll_attempts", 120))
        self.estimated_chars_per_second = float(config.get("estimated_chars_per_second", DEFAULT_CN_CHARS_PER_SECOND))
        self.retry_policy = RetryPolicy.from_config(config.get("retry_policy", {}))
        api_cfg = config.get("api") if isinstance(config.get("api"), dict) else None
        self.timeout_seconds = int(config.get("timeout_seconds", (api_cfg or {}).get("timeout_seconds", 30)))
        self.client: Optional[HttpClient] = (
            HttpClient(api_cfg, dry_run=dry_run, retry_policy=self.retry_policy) if api_cfg else None
        )
        checkpoint_cfg = config.get("checkpointing", {}) if isinstance(config.get("checkpointing"), dict) else {}
        manifest_name = str(checkpoint_cfg.get("manifest_name", "Remote_Run_Manifest.json")).strip() or "Remote_Run_Manifest.json"
        self.manifest_path = self.manifest_root / manifest_name
        self.checkpoint_enabled = bool(checkpoint_cfg.get("enabled", True))
        self.resume_enabled = bool(checkpoint_cfg.get("resume_enabled", True))
        self._manifest: Optional[RemoteRunManifestStore] = None

    def produce(self, bundle: ProductionBundle, beats: Sequence[Beat]) -> ProductionBundle:
        enriched = copy.deepcopy(bundle)
        manifest = self._get_manifest(bundle)
        runtime_context = self._build_runtime_context(bundle, manifest)
        speaker_id = self._resolve_speaker_id(runtime_context, manifest)
        runtime_context["speaker_id"] = speaker_id or ""

        tts_clips: List[AudioClip] = []
        avatar_clips: List[AvatarClip] = []

        enable_tts = bool(self.config.get("enable_tts_generation", True))
        enable_avatar = bool(self.config.get("enable_avatar_generation", False))
        if enable_avatar and not enable_tts:
            raise CloudProductionError("production.enable_tts_generation=false 时不能启用 enable_avatar_generation")

        for index, beat in enumerate(beats, start=1):
            segment_meta = self._segment_meta(beat)
            beat_context = dict(runtime_context)
            beat_context.update(
                {
                    "segment_id": beat.beat_id,
                    "script_text": beat.text,
                    "text": beat.text,
                    "request_id": f"{runtime_context.get('request_id', bundle.job_id)}-seg{index:02d}",
                    "segment_type": beat.segment_type,
                    "start_ms": beat.start_ms,
                    "end_ms": beat.end_ms,
                    "tts_output_dir": str((self.output_root / "production" / "audio" / beat.beat_id).resolve()),
                }
            )

            audio_ref = ""
            audio_duration_ms = max(beat.end_ms - beat.start_ms, 1)
            tts_input_hash = ""
            if enable_tts:
                audio_ref, audio_duration_ms, tts_input_hash = self._generate_tts(
                    beat_context,
                    manifest,
                    segment_meta=segment_meta,
                )
                beat_context["audio_duration_ms"] = int(audio_duration_ms)
                # Match avatar generation cadence to the real TTS segment instead of a fixed clip length.
                beat_context["avatar_duration_seconds"] = max(int(math.ceil(max(audio_duration_ms, 1) / 1000.0)), 1)
                tts_clips.append(
                    AudioClip(
                        segment_id=beat.beat_id,
                        audio_path=audio_ref,
                        start_ms=beat.start_ms,
                        end_ms=beat.start_ms + max(int(audio_duration_ms or 0), 1),
                        text=beat.text,
                        metadata={"provider": str(self.config.get("tts", {}).get("provider", "generic"))},
                    )
                )

            if enable_avatar and beat.segment_type == "AVATAR":
                checkpoint_video_ref = self._get_avatar_checkpoint(
                    beat_context,
                    manifest,
                    audio_input_hash=tts_input_hash,
                )
                if checkpoint_video_ref:
                    avatar_clips.append(
                        AvatarClip(
                            segment_id=beat.beat_id,
                            video_path=checkpoint_video_ref,
                            audio_path=audio_ref,
                            start_ms=beat.start_ms,
                            end_ms=beat.start_ms + max(int(audio_duration_ms or 0), 1),
                            text=beat.text,
                            metadata={"provider": str(self.config.get("avatar", {}).get("provider", "generic"))},
                        )
                    )
                    continue

                avatar_succeeded = False
                try:
                    beat_context["audio_url"] = self._publish_tts_audio_if_needed(audio_ref, beat_context)
                    delivery_record = beat_context.get("_audio_delivery_manifest")
                    if isinstance(delivery_record, dict):
                        manifest.save_segment_stage(
                            beat.beat_id,
                            "audio_delivery",
                            delivery_record,
                            segment_meta=segment_meta,
                        )
                    if not self._is_remote_reference(beat_context["audio_url"]) and not self.dry_run:
                        raise CloudProductionError(
                            "avatar generation requires a remotely accessible audio_url; "
                            "configure production.audio_delivery or use a TTS provider that returns remote audio_url"
                        )
                    video_ref = self._generate_avatar(
                        beat_context,
                        manifest,
                        segment_meta=segment_meta,
                        audio_input_hash=tts_input_hash,
                    )
                    avatar_clips.append(
                        AvatarClip(
                            segment_id=beat.beat_id,
                            video_path=video_ref,
                            audio_path=audio_ref,
                            start_ms=beat.start_ms,
                            end_ms=beat.start_ms + max(int(audio_duration_ms or 0), 1),
                            text=beat.text,
                            metadata={"provider": str(self.config.get("avatar", {}).get("provider", "generic"))},
                        )
                    )
                    avatar_succeeded = True
                except Exception as exc:
                    delivery_record = beat_context.get("_audio_delivery_manifest")
                    if isinstance(delivery_record, dict):
                        manifest.patch_segment_stage(
                            beat.beat_id,
                            "audio_delivery",
                            {
                                "status": "failed",
                                "error": {"message": str(exc)},
                            },
                            segment_meta=segment_meta,
                        )
                    raise
                finally:
                    cleanup_patch = self._cleanup_audio_delivery_if_needed(beat_context, success=avatar_succeeded)
                    if cleanup_patch:
                        manifest.patch_segment_stage(
                            beat.beat_id,
                            "audio_delivery",
                            cleanup_patch,
                            segment_meta=segment_meta,
                        )

        enriched.tts_clips = tts_clips
        enriched.avatar_clips = avatar_clips
        enriched.full_tts_audio_path = tts_clips[0].audio_path if len(tts_clips) == 1 else ""
        enriched.full_tts_duration_ms = sum(max(clip.end_ms - clip.start_ms, 1) for clip in tts_clips) or None
        enriched.metadata = {
            **enriched.metadata,
            "source": "cloud",
            "speaker_id": speaker_id or "",
            "tts_clip_count": len(tts_clips),
            "avatar_clip_count": len(avatar_clips),
        }
        return enriched

    def _get_manifest(self, bundle: ProductionBundle) -> RemoteRunManifestStore:
        if self._manifest is None:
            self._manifest = RemoteRunManifestStore(
                self.manifest_path,
                job_id=bundle.job_id,
                dry_run=self.dry_run,
                enabled=self.checkpoint_enabled,
                resume_enabled=self.resume_enabled,
            )
        return self._manifest

    @staticmethod
    def _segment_meta(beat: Beat) -> Dict[str, Any]:
        return {
            "segment_id": beat.beat_id,
            "segment_type": beat.segment_type,
            "text": beat.text,
            "start_ms": beat.start_ms,
            "end_ms": beat.end_ms,
            "text_hash": stable_hash({"text": beat.text}),
        }

    @staticmethod
    def _build_stage_record(
        *,
        stage: str,
        status: str,
        provider: str,
        input_hash: str,
        request_id: str,
        result: Dict[str, Any],
        task_id: str = "",
        response: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        record = {
            "stage": stage,
            "status": status,
            "provider": provider,
            "input_hash": input_hash,
            "request_id": request_id,
            "task_id": task_id,
            "reuse_count": 0,
            "updated_at": int(time.time()),
            "result": result,
        }
        if response is not None:
            record["response"] = response
        if error is not None:
            record["error"] = error
        if metadata is not None:
            record["metadata"] = metadata
        return record

    @staticmethod
    def _normalize_fingerprint_value(value: Any, *, path: Tuple[str, ...] = (), audio_input_hash: str = "") -> Any:
        if isinstance(value, dict):
            normalized: Dict[str, Any] = {}
            for raw_key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
                key = str(raw_key)
                lowered_key = key.strip().lower()
                if lowered_key in VOLATILE_FINGERPRINT_KEYS:
                    continue
                normalized[key] = CloudProductionGenerator._normalize_fingerprint_value(
                    item,
                    path=(*path, lowered_key),
                    audio_input_hash=audio_input_hash,
                )
            return normalized
        if isinstance(value, list):
            return [
                CloudProductionGenerator._normalize_fingerprint_value(
                    item,
                    path=(*path, "[]"),
                    audio_input_hash=audio_input_hash,
                )
                for item in value
            ]
        if audio_input_hash and path and path[-1] == "audio_url":
            return f"audio-input:{audio_input_hash}"
        if audio_input_hash and len(path) >= 2 and path[-2:] == ("audio_url", "url"):
            return f"audio-input:{audio_input_hash}"
        return value

    def _build_stage_input_hash(self, stage: str, stage_cfg: Dict[str, Any], payload: Dict[str, Any]) -> str:
        fingerprint = {
            "stage": stage,
            "provider": str(stage_cfg.get("provider", stage)),
            "endpoint": str(stage_cfg.get("endpoint", "")),
            "trigger_path": get_nested(stage_cfg, "trigger.path", ""),
            "status_path": get_nested(stage_cfg, "status.path", ""),
            "payload": self._normalize_fingerprint_value(payload),
        }
        return stable_hash(fingerprint)

    def _build_tts_input_hash(self, tts_cfg: Dict[str, Any], context: Dict[str, Any], payload: Dict[str, Any]) -> str:
        fingerprint = {
            "provider": str(tts_cfg.get("provider", "generic")),
            "speaker_id": str(context.get("speaker_id", "")),
            "script_text": str(context.get("script_text", "")),
            "segment_id": str(context.get("segment_id", "")),
            "stage": self._build_stage_input_hash("tts", tts_cfg, payload),
        }
        return stable_hash(fingerprint)

    def _build_avatar_input_hash(
        self,
        avatar_cfg: Dict[str, Any],
        context: Dict[str, Any],
        payload: Dict[str, Any],
        *,
        audio_input_hash: str,
    ) -> str:
        fingerprint = {
            "provider": str(avatar_cfg.get("provider", "generic")),
            "segment_id": str(context.get("segment_id", "")),
            "script_text": str(context.get("script_text", "")),
            "avatar_path": str(context.get("avatar_path", "")),
            "audio_input_hash": audio_input_hash,
            "payload": self._normalize_fingerprint_value(payload, audio_input_hash=audio_input_hash),
            "trigger_path": get_nested(avatar_cfg, "trigger.path", ""),
            "status_path": get_nested(avatar_cfg, "status.path", ""),
        }
        return stable_hash(fingerprint)

    def _is_checkpoint_ref_available(self, raw: str) -> bool:
        if not raw:
            return False
        parsed = urllib.parse.urlparse(str(raw).strip())
        if parsed.scheme in {"http", "https"}:
            return True
        if self.dry_run and parsed.scheme:
            return True
        if parsed.scheme:
            return False
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = path.resolve()
        return path.is_file()

    def _materialize_checkpoint_ref_if_needed(self, ref: str, *, stage: str, segment_id: str) -> str:
        normalized_ref = str(ref or "").strip()
        if not normalized_ref:
            return normalized_ref

        parsed = urllib.parse.urlparse(normalized_ref)
        if parsed.scheme in {"http", "https"}:
            return normalized_ref
        if self.dry_run and parsed.scheme:
            return normalized_ref
        if parsed.scheme:
            return normalized_ref

        source_path = Path(normalized_ref).expanduser()
        if not source_path.is_absolute():
            source_path = source_path.resolve()
        if not source_path.is_file():
            return normalized_ref

        stage_dir = "audio" if stage == "tts" else stage
        target_path = (self.output_root / "production" / stage_dir / segment_id / source_path.name).resolve()
        if source_path == target_path:
            return str(source_path)

        target_path.parent.mkdir(parents=True, exist_ok=True)
        if not target_path.exists():
            shutil.copy2(source_path, target_path)
        return str(target_path)

    def _call_with_retry(self, label: str, fn, *, retry_type: type[Exception]):
        try:
            return call_with_retry(
                fn,
                policy=self.retry_policy,
                should_retry=lambda exc: isinstance(exc, retry_type),
                label=label,
                logger=logging.warning,
            )
        except RetryExhaustedError as exc:
            raise CloudProductionError(str(exc)) from exc

    def _build_runtime_context(self, bundle: ProductionBundle, manifest: RemoteRunManifestStore) -> Dict[str, Any]:
        runtime = self.config.get("runtime", {}) if isinstance(self.config.get("runtime"), dict) else {}
        context = dict(runtime)
        requested_request_id = str(context.get("request_id", "")).strip() or f"{bundle.job_id}-{int(time.time())}"
        context["request_id"] = manifest.bind_base_request_id(requested_request_id)
        context.setdefault("job_id", bundle.job_id)
        context.setdefault("topic_hint", bundle.topic_hint)
        if bundle.avatar_image_path:
            context.setdefault("avatar_path", bundle.avatar_image_path)
        return context

    def _resolve_speaker_id(self, context: Dict[str, Any], manifest: RemoteRunManifestStore) -> Optional[str]:
        tts_cfg = self.config.get("tts", {})
        fixed_speaker_id = tts_cfg.get("speaker_id")
        if fixed_speaker_id:
            return str(fixed_speaker_id)

        vc_cfg = self.config.get("voice_clone")
        if not isinstance(vc_cfg, dict) or not vc_cfg.get("enabled", False):
            return None

        vc_payload = self._build_payload(vc_cfg, context, default_payload={})
        input_hash = self._build_stage_input_hash("voice_clone", vc_cfg, vc_payload)
        checkpoint = manifest.get_runtime_stage_success("voice_clone", input_hash=input_hash)
        if checkpoint:
            speaker_id = str(get_nested(checkpoint, "result.speaker_id", "")).strip()
            if speaker_id:
                manifest.mark_runtime_stage_reused("voice_clone")
                context["voice_clone_task_id"] = str(checkpoint.get("task_id", "")).strip()
                return speaker_id

        try:
            vc_result = self._trigger_and_poll("voice_clone", vc_cfg, vc_payload)
            speaker_id = get_nested(vc_result.response, vc_cfg.get("status", {}).get("speaker_id_path", "data.speaker_id"))
            if self.dry_run and not speaker_id:
                speaker_id = "dry-speaker-id"
            if not speaker_id:
                raise CloudProductionError("voice_clone succeeded but did not return speaker_id")
            context["voice_clone_task_id"] = vc_result.task_id
            manifest.save_runtime_stage(
                "voice_clone",
                self._build_stage_record(
                    stage="voice_clone",
                    status="succeeded",
                    provider=str(vc_cfg.get("provider", "generic")),
                    input_hash=input_hash,
                    request_id=str(context.get("request_id", "")),
                    task_id=vc_result.task_id,
                    result={"speaker_id": str(speaker_id)},
                    response=vc_result.response,
                ),
            )
            return str(speaker_id)
        except Exception as exc:
            manifest.save_runtime_stage(
                "voice_clone",
                self._build_stage_record(
                    stage="voice_clone",
                    status="failed",
                    provider=str(vc_cfg.get("provider", "generic")),
                    input_hash=input_hash,
                    request_id=str(context.get("request_id", "")),
                    result={},
                    error={"message": str(exc)},
                ),
            )
            raise

    def _generate_tts(
        self,
        context: Dict[str, Any],
        manifest: RemoteRunManifestStore,
        *,
        segment_meta: Dict[str, Any],
    ) -> Tuple[str, int, str]:
        tts_cfg = self.config.get("tts", {})
        provider = str(tts_cfg.get("provider", "generic")).strip().lower()
        payload = self._build_payload(tts_cfg, context, default_payload={"script_text": context["script_text"]})
        input_hash = self._build_tts_input_hash(tts_cfg, context, payload)
        checkpoint = manifest.get_segment_stage_success(context["segment_id"], "tts", input_hash=input_hash)
        if checkpoint:
            audio_ref = str(get_nested(checkpoint, "result.audio_ref", "")).strip()
            duration_ms = self._optional_int(get_nested(checkpoint, "result.duration_ms"))
            if audio_ref and duration_ms and self._is_checkpoint_ref_available(audio_ref):
                audio_ref = self._materialize_checkpoint_ref_if_needed(
                    audio_ref,
                    stage="tts",
                    segment_id=str(context["segment_id"]),
                )
                manifest.mark_segment_stage_reused(context["segment_id"], "tts")
                return audio_ref, duration_ms, input_hash

        try:
            if provider == "doubao_tts2_v3_http_chunked":
                audio_ref, duration_ms = self._run_doubao_tts2_tts(tts_cfg, context, payload=payload)
                task_id = ""
                response: Dict[str, Any] = {"mode": "direct_http", "audio_ref": audio_ref}
            else:
                result = self._trigger_and_poll("tts", tts_cfg, payload)
                audio_url = get_nested(result.response, tts_cfg.get("status", {}).get("result_url_path", "data.audio_url"))
                duration_ms = get_nested(result.response, tts_cfg.get("status", {}).get("duration_ms_path", "data.duration_ms"))
                if self.dry_run and not audio_url:
                    audio_url = f"dry-run://tts/{context['segment_id']}.wav"
                if not audio_url:
                    raise CloudProductionError(f"tts for {context['segment_id']} succeeded but did not return audio_url")
                audio_ref = str(audio_url)
                duration_ms = self._resolve_audio_duration_ms(
                    audio_ref=audio_ref,
                    script_text=str(context.get("script_text", "")),
                    reported_duration_ms=duration_ms,
                )
                task_id = result.task_id
                response = result.response

            manifest.save_segment_stage(
                context["segment_id"],
                "tts",
                self._build_stage_record(
                    stage="tts",
                    status="succeeded",
                    provider=provider,
                    input_hash=input_hash,
                    request_id=str(context.get("request_id", "")),
                    task_id=task_id,
                    result={"audio_ref": str(audio_ref), "duration_ms": int(duration_ms)},
                    response=response,
                ),
                segment_meta=segment_meta,
            )
            return str(audio_ref), int(duration_ms), input_hash
        except Exception as exc:
            manifest.save_segment_stage(
                context["segment_id"],
                "tts",
                self._build_stage_record(
                    stage="tts",
                    status="failed",
                    provider=provider,
                    input_hash=input_hash,
                    request_id=str(context.get("request_id", "")),
                    result={},
                    error={"message": str(exc)},
                ),
                segment_meta=segment_meta,
            )
            raise

    def _get_avatar_checkpoint(
        self,
        context: Dict[str, Any],
        manifest: RemoteRunManifestStore,
        *,
        audio_input_hash: str,
    ) -> Optional[str]:
        avatar_cfg = self.config.get("avatar", {})
        payload = self._build_payload(
            avatar_cfg,
            context,
            default_payload={
                "audio_url": context.get("audio_url", ""),
                "avatar_path": context.get("avatar_path", ""),
                "script_text": context.get("script_text", ""),
            },
        )
        input_hash = self._build_avatar_input_hash(avatar_cfg, context, payload, audio_input_hash=audio_input_hash)
        checkpoint = manifest.get_segment_stage_success(context["segment_id"], "avatar", input_hash=input_hash)
        if not checkpoint:
            return None
        video_ref = str(get_nested(checkpoint, "result.video_ref", "")).strip()
        if not video_ref or not self._is_checkpoint_ref_available(video_ref):
            return None
        video_ref = self._materialize_checkpoint_ref_if_needed(
            video_ref,
            stage="avatar",
            segment_id=str(context["segment_id"]),
        )
        manifest.mark_segment_stage_reused(context["segment_id"], "avatar")
        return video_ref

    def _generate_avatar(
        self,
        context: Dict[str, Any],
        manifest: RemoteRunManifestStore,
        *,
        segment_meta: Dict[str, Any],
        audio_input_hash: str,
    ) -> str:
        avatar_cfg = self.config.get("avatar", {})
        payload = self._build_payload(
            avatar_cfg,
            context,
            default_payload={
                "audio_url": context.get("audio_url", ""),
                "avatar_path": context.get("avatar_path", ""),
                "script_text": context.get("script_text", ""),
            },
        )
        input_hash = self._build_avatar_input_hash(avatar_cfg, context, payload, audio_input_hash=audio_input_hash)
        checkpoint = manifest.get_segment_stage_success(context["segment_id"], "avatar", input_hash=input_hash)
        if checkpoint:
            video_ref = str(get_nested(checkpoint, "result.video_ref", "")).strip()
            if video_ref and self._is_checkpoint_ref_available(video_ref):
                video_ref = self._materialize_checkpoint_ref_if_needed(
                    video_ref,
                    stage="avatar",
                    segment_id=str(context["segment_id"]),
                )
                manifest.mark_segment_stage_reused(context["segment_id"], "avatar")
                return video_ref

        try:
            result = self._trigger_and_poll("avatar", avatar_cfg, payload)
            video_url = get_nested(result.response, avatar_cfg.get("status", {}).get("result_url_path", "data.video_url"))
            if self.dry_run and not video_url:
                video_url = f"dry-run://avatar/{context['segment_id']}.mp4"
            if not video_url:
                raise CloudProductionError(f"avatar for {context['segment_id']} succeeded but did not return video_url")
            resolved_video_ref = str(video_url)
            manifest.save_segment_stage(
                context["segment_id"],
                "avatar",
                self._build_stage_record(
                    stage="avatar",
                    status="succeeded",
                    provider=str(avatar_cfg.get("provider", "generic")),
                    input_hash=input_hash,
                    request_id=str(context.get("request_id", "")),
                    task_id=result.task_id,
                    result={"video_ref": resolved_video_ref, "audio_input_hash": audio_input_hash},
                    response=result.response,
                ),
                segment_meta=segment_meta,
            )
            return resolved_video_ref
        except Exception as exc:
            manifest.save_segment_stage(
                context["segment_id"],
                "avatar",
                self._build_stage_record(
                    stage="avatar",
                    status="failed",
                    provider=str(avatar_cfg.get("provider", "generic")),
                    input_hash=input_hash,
                    request_id=str(context.get("request_id", "")),
                    result={"audio_input_hash": audio_input_hash},
                    error={"message": str(exc)},
                ),
                segment_meta=segment_meta,
            )
            raise

    def _publish_tts_audio_if_needed(self, tts_audio_ref: str, context: Dict[str, Any]) -> str:
        delivery_cfg = self.config.get("audio_delivery", {}) if isinstance(self.config.get("audio_delivery"), dict) else {}
        if not delivery_cfg.get("enabled", False):
            context["_audio_delivery_manifest"] = self._build_stage_record(
                stage="audio_delivery",
                status="disabled",
                provider="none",
                input_hash="",
                request_id=str(context.get("request_id", "")),
                result={
                    "source_audio_ref": tts_audio_ref,
                    "published_url": tts_audio_ref,
                    "uploaded": False,
                },
            )
            return tts_audio_ref
        if self._is_remote_reference(tts_audio_ref):
            context["_audio_delivery_manifest"] = self._build_stage_record(
                stage="audio_delivery",
                status="reused_remote_url",
                provider="passthrough",
                input_hash="",
                request_id=str(context.get("request_id", "")),
                result={
                    "source_audio_ref": tts_audio_ref,
                    "published_url": tts_audio_ref,
                    "uploaded": False,
                },
            )
            return tts_audio_ref
        provider = str(delivery_cfg.get("provider", "tos")).strip().lower()
        if provider != "tos":
            raise CloudProductionError(f"audio_delivery.provider not supported: {provider}")

        local_path = Path(str(tts_audio_ref)).expanduser()
        if self.dry_run:
            object_key = self._build_audio_object_key(local_path.name or "tts.wav", context, delivery_cfg)
            published_url = f"dry-run://tos/{object_key}"
            context["_audio_delivery_cleanup"] = {
                "provider": "tos",
                "bucket": str(delivery_cfg.get("bucket", "")),
                "object_key": object_key,
                "version_id": "",
            }
            context["_audio_delivery_manifest"] = self._build_stage_record(
                stage="audio_delivery",
                status="succeeded",
                provider="tos",
                input_hash="",
                request_id=str(context.get("request_id", "")),
                result={
                    "source_audio_ref": tts_audio_ref,
                    "published_url": published_url,
                    "uploaded": True,
                    "bucket": str(delivery_cfg.get("bucket", "")),
                    "object_key": object_key,
                    "version_id": "",
                },
            )
            return published_url
        if not local_path.is_file():
            raise CloudProductionError(f"audio_delivery requires a local tts file, got: {tts_audio_ref}")
        return self._upload_to_tos(local_path, context, delivery_cfg)

    @staticmethod
    def _build_audio_object_key(filename: str, context: Dict[str, Any], cfg: Dict[str, Any]) -> str:
        prefix = str(cfg.get("object_prefix", "video-director-audio")).strip().strip("/")
        request_id = str(context.get("request_id", uuid.uuid4())).strip()
        safe_filename = re.sub(r"[^A-Za-z0-9._-]+", "-", filename) or "tts.wav"
        key = f"{request_id}-{safe_filename}"
        return f"{prefix}/{key}" if prefix else key

    def _upload_to_tos(self, local_path: Path, context: Dict[str, Any], cfg: Dict[str, Any]) -> str:
        try:
            import tos  # type: ignore
        except ImportError as exc:
            raise CloudProductionError("audio_delivery requires the tos package") from exc

        endpoint = str(cfg.get("endpoint", "")).strip()
        region = str(cfg.get("region", "")).strip()
        access_key = str(cfg.get("access_key", "")).strip()
        secret_key = str(cfg.get("secret_key", "")).strip()
        bucket = str(cfg.get("bucket", "")).strip()
        security_token = str(cfg.get("security_token", "")).strip() or None
        if not endpoint or not region or not access_key or not secret_key or not bucket:
            raise CloudProductionError("audio_delivery TOS config requires endpoint/region/access_key/secret_key/bucket")

        object_key = self._build_audio_object_key(local_path.name, context, cfg)
        client = tos.TosClientV2(access_key, secret_key, endpoint, region, security_token=security_token)
        try:
            content_type = str(cfg.get("content_type", "audio/wav")).strip() or "audio/wav"
            meta_cfg = cfg.get("meta", {})
            meta = None
            if isinstance(meta_cfg, dict) and meta_cfg:
                rendered_meta = {
                    str(key): str(render_template(value, context))
                    for key, value in meta_cfg.items()
                    if str(key).strip()
                }
                meta = rendered_meta or None
            output = self._call_with_retry(
                f"TOS upload {object_key}",
                lambda _: self._tos_put_object_from_file(
                    client=client,
                    bucket=bucket,
                    object_key=object_key,
                    local_path=local_path,
                    content_type=content_type,
                    meta=meta,
                ),
                retry_type=TransientCloudStorageError,
            )
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, CloudProductionError):
                raise
            raise CloudProductionError(f"TOS upload failed: {exc}") from exc

        cleanup_info = {
            "provider": "tos",
            "bucket": bucket,
            "object_key": object_key,
            "version_id": getattr(output, "version_id", None) or "",
        }
        context["_audio_delivery_cleanup"] = cleanup_info

        public_base_url = str(cfg.get("public_base_url", "")).strip().rstrip("/")
        if public_base_url:
            quoted_key = "/".join(urllib.parse.quote(part) for part in object_key.split("/"))
            published_url = f"{public_base_url}/{quoted_key}"
            context["_audio_delivery_manifest"] = self._build_stage_record(
                stage="audio_delivery",
                status="succeeded",
                provider="tos",
                input_hash="",
                request_id=str(context.get("request_id", "")),
                result={
                    "source_audio_ref": str(local_path),
                    "published_url": published_url,
                    "uploaded": True,
                    **cleanup_info,
                },
            )
            return published_url

        expires_seconds = max(int(cfg.get("expires_seconds", 3600)), 60)
        download_endpoint = str(cfg.get("download_endpoint", "")).strip() or None
        is_custom_domain = bool(cfg.get("is_custom_domain", False))
        try:
            signed = self._call_with_retry(
                f"TOS pre-sign {object_key}",
                lambda _: self._tos_presign_download_url(
                    client=client,
                    bucket=bucket,
                    object_key=object_key,
                    expires_seconds=expires_seconds,
                    download_endpoint=download_endpoint,
                    is_custom_domain=is_custom_domain,
                    tos_module=tos,
                ),
                retry_type=TransientCloudStorageError,
            )
            published_url = str(signed.signed_url)
            context["_audio_delivery_manifest"] = self._build_stage_record(
                stage="audio_delivery",
                status="succeeded",
                provider="tos",
                input_hash="",
                request_id=str(context.get("request_id", "")),
                result={
                    "source_audio_ref": str(local_path),
                    "published_url": published_url,
                    "uploaded": True,
                    **cleanup_info,
                },
            )
            return published_url
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, CloudProductionError):
                raise
            raise CloudProductionError(f"TOS pre-sign failed: {exc}") from exc

    def _cleanup_audio_delivery_if_needed(self, context: Dict[str, Any], *, success: bool) -> Optional[Dict[str, Any]]:
        cleanup_info = context.pop("_audio_delivery_cleanup", None)
        if not isinstance(cleanup_info, dict):
            return None

        delivery_cfg = self.config.get("audio_delivery", {}) if isinstance(self.config.get("audio_delivery"), dict) else {}
        cleanup_after_success = bool(delivery_cfg.get("cleanup_after_avatar_success", False))
        cleanup_after_failure = bool(delivery_cfg.get("cleanup_after_avatar_failure", False))
        if success and not cleanup_after_success:
            return {"cleanup": {"status": "retained", "reason": "cleanup_after_avatar_success_disabled"}}
        if not success and not cleanup_after_failure:
            return {"cleanup": {"status": "retained", "reason": "cleanup_after_avatar_failure_disabled"}}

        try:
            if self.dry_run:
                logging.info(
                    "[dry-run] cleanup uploaded audio provider=%s bucket=%s key=%s version_id=%s",
                    cleanup_info.get("provider"),
                    cleanup_info.get("bucket"),
                    cleanup_info.get("object_key"),
                    cleanup_info.get("version_id"),
                )
                return {"cleanup": {"status": "dry_run", **cleanup_info}}
            self._delete_from_tos(cleanup_info, delivery_cfg)
            return {"cleanup": {"status": "deleted", **cleanup_info}}
        except Exception as exc:  # noqa: BLE001
            logging.warning("cleanup uploaded audio failed: %s", exc)
            return {"cleanup": {"status": "failed", **cleanup_info, "error": str(exc)}}

    def _delete_from_tos(self, cleanup_info: Dict[str, Any], cfg: Dict[str, Any]) -> None:
        try:
            import tos  # type: ignore
        except ImportError as exc:
            raise CloudProductionError("audio_delivery cleanup requires the tos package") from exc

        endpoint = str(cfg.get("endpoint", "")).strip()
        region = str(cfg.get("region", "")).strip()
        access_key = str(cfg.get("access_key", "")).strip()
        secret_key = str(cfg.get("secret_key", "")).strip()
        security_token = str(cfg.get("security_token", "")).strip() or None
        bucket = str(cleanup_info.get("bucket", "")).strip()
        object_key = str(cleanup_info.get("object_key", "")).strip()
        version_id = str(cleanup_info.get("version_id", "")).strip() or None
        if not endpoint or not region or not access_key or not secret_key or not bucket or not object_key:
            raise CloudProductionError("audio_delivery cleanup requires endpoint/region/access_key/secret_key/bucket/object_key")

        client = tos.TosClientV2(access_key, secret_key, endpoint, region, security_token=security_token)
        self._call_with_retry(
            f"TOS delete {object_key}",
            lambda _: self._tos_delete_object(
                client=client,
                bucket=bucket,
                object_key=object_key,
                version_id=version_id,
            ),
            retry_type=TransientCloudStorageError,
        )

    def _tos_put_object_from_file(
        self,
        *,
        client: Any,
        bucket: str,
        object_key: str,
        local_path: Path,
        content_type: str,
        meta: Optional[Dict[str, str]],
    ) -> Any:
        try:
            return client.put_object_from_file(
                bucket,
                object_key,
                str(local_path),
                content_type=content_type,
                meta=meta,
            )
        except Exception as exc:  # noqa: BLE001
            self._raise_tos_operation_error("upload", exc)

    def _tos_presign_download_url(
        self,
        *,
        client: Any,
        bucket: str,
        object_key: str,
        expires_seconds: int,
        download_endpoint: Optional[str],
        is_custom_domain: bool,
        tos_module: Any,
    ) -> Any:
        try:
            return client.pre_signed_url(
                tos_module.HttpMethodType.Http_Method_Get,
                bucket,
                key=object_key,
                expires=expires_seconds,
                alternative_endpoint=download_endpoint,
                is_custom_domain=is_custom_domain,
            )
        except Exception as exc:  # noqa: BLE001
            self._raise_tos_operation_error("pre-sign", exc)

    def _tos_delete_object(self, *, client: Any, bucket: str, object_key: str, version_id: Optional[str]) -> None:
        try:
            client.delete_object(bucket, object_key, version_id=version_id)
        except Exception as exc:  # noqa: BLE001
            self._raise_tos_operation_error("delete", exc)

    def _raise_tos_operation_error(self, label: str, exc: Exception) -> None:
        status_code = getattr(exc, "status_code", None)
        message = getattr(exc, "message", str(exc))
        request_id = getattr(exc, "request_id", "")
        code = getattr(exc, "code", "")
        cause = getattr(exc, "cause", "")
        detail = f"TOS {label} error: code={code}, request_id={request_id}, message={message}, cause={cause}, http={status_code}"
        if status_code in self.retry_policy.retryable_http_statuses or (isinstance(status_code, int) and status_code >= 500):
            raise TransientCloudStorageError(detail) from exc
        if exc.__class__.__name__ == "TosClientError":
            raise TransientCloudStorageError(detail) from exc
        raise CloudProductionError(detail) from exc

    def _build_payload(self, stage_cfg: Dict[str, Any], context: Dict[str, Any], default_payload: Dict[str, Any]) -> Dict[str, Any]:
        payload_template = stage_cfg.get("payload_template")
        if payload_template is None:
            return prune_empty(default_payload)
        payload = render_template(payload_template, context)
        if not isinstance(payload, dict):
            raise CloudProductionError("payload_template must render to an object")
        return prune_empty(payload)

    def _run_doubao_tts2_tts(
        self,
        tts_cfg: Dict[str, Any],
        context: Dict[str, Any],
        *,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, int]:
        endpoint = str(tts_cfg.get("endpoint", DOUBAO_TTS2_ENDPOINT))
        output_dir = Path(str(context.get("tts_output_dir", self.output_root / "production" / "audio"))).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file_name = str(tts_cfg.get("output_file_name", "tts.wav"))
        output_path = output_dir / output_file_name

        payload = payload or self._build_payload(
            tts_cfg,
            context,
            default_payload={
                "request_id": str(uuid.uuid4()),
                "req_params": {
                    "speaker": context.get("speaker_id", ""),
                    "text": context.get("script_text", ""),
                    "audio_params": {"format": "wav"},
                },
            },
        )
        if self.dry_run:
            logging.info("[dry-run] POST %s payload=%s", endpoint, payload)
            output_path.write_bytes(b"dry-run-tts-audio")
            return str(output_path), self._estimate_duration_ms(str(context.get("script_text", "")))

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/octet-stream",
            "X-Api-Resource-Id": str(tts_cfg.get("resource_id", DOUBAO_TTS2_RESOURCE_ID)),
        }
        api_key = str(tts_cfg.get("api_key", "")).strip() or os.getenv("DOUBAO_TTS_API_KEY", "").strip()
        if not api_key:
            raise CloudProductionError("doubao tts requires tts.api_key or DOUBAO_TTS_API_KEY")
        headers["X-Api-Key"] = api_key
        request_id = str(payload.get("request_id", uuid.uuid4()))
        headers["X-Api-Request-Id"] = request_id

        req = urllib.request.Request(
            url=endpoint,
            method="POST",
            headers=headers,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )
        def _request_once(_: int) -> None:
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    content_type = (resp.headers.get("Content-Type") or "").lower()
                    if "application/json" in content_type or "text/plain" in content_type:
                        raw = resp.read().decode("utf-8", errors="ignore")
                        objects: List[Dict[str, Any]] = []
                        decoder = json.JSONDecoder()
                        idx = 0
                        while idx < len(raw):
                            while idx < len(raw) and raw[idx].isspace():
                                idx += 1
                            if idx >= len(raw):
                                break
                            obj, end = decoder.raw_decode(raw, idx)
                            if isinstance(obj, dict):
                                objects.append(obj)
                            idx = end
                        if not objects:
                            raise CloudProductionError("doubao tts returned JSON but no objects were parsed")

                        audio_parts: List[bytes] = []
                        success_codes = {None, 0, "0", 20000000, "20000000"}
                        for obj in objects:
                            code = obj.get("code")
                            if code not in success_codes:
                                raise CloudProductionError(f"doubao tts business error: code={code}, message={obj.get('message')}")
                            data_b64 = obj.get("data")
                            if isinstance(data_b64, str) and data_b64:
                                audio_parts.append(base64.b64decode(data_b64))
                        if not audio_parts:
                            raise CloudProductionError("doubao tts returned success but no audio payload")
                        output_path.write_bytes(b"".join(audio_parts))
                    else:
                        total_bytes = 0
                        with output_path.open("wb") as handle:
                            while True:
                                chunk = resp.read(8192)
                                if not chunk:
                                    break
                                handle.write(chunk)
                                total_bytes += len(chunk)
                        if total_bytes <= 0:
                            raise CloudProductionError("doubao tts returned empty audio")
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="ignore")
                if exc.code in self.retry_policy.retryable_http_statuses:
                    raise TransientRequestError(f"doubao tts retryable HTTP {exc.code}: {body}") from exc
                raise CloudProductionError(f"doubao tts request failed: HTTP {exc.code}, body={body}") from exc
            except urllib.error.URLError as exc:
                raise TransientRequestError(f"doubao tts request failed: {exc}") from exc

        self._call_with_retry(
            "doubao tts",
            _request_once,
            retry_type=TransientRequestError,
        )

        return str(output_path), self._resolve_audio_duration_ms(
            audio_ref=str(output_path),
            script_text=str(context.get("script_text", "")),
            reported_duration_ms=None,
        )

    def _estimate_duration_ms(self, text: str) -> int:
        chars = max(len(re.sub(r"\s+", "", text)), 1)
        return int(math.ceil(chars / max(self.estimated_chars_per_second, 0.1) * 1000))

    def _resolve_audio_duration_ms(self, *, audio_ref: str, script_text: str, reported_duration_ms: Any) -> int:
        estimated_duration_ms = self._estimate_duration_ms(script_text)
        reported_duration = self._optional_int(reported_duration_ms)
        if self.dry_run:
            return reported_duration or estimated_duration_ms
        if not audio_ref or self._is_remote_reference(audio_ref):
            return reported_duration or estimated_duration_ms

        audio_path = Path(str(audio_ref)).expanduser()
        if not audio_path.is_absolute():
            audio_path = audio_path.resolve()
        if not audio_path.is_file():
            return reported_duration or estimated_duration_ms

        probed_duration = self._probe_local_audio_duration_ms(audio_path)
        if probed_duration is not None:
            return probed_duration
        return reported_duration or estimated_duration_ms

    @staticmethod
    def _probe_local_audio_duration_ms(path: Path) -> Optional[int]:
        ffprobe_duration_ms = CloudProductionGenerator._probe_ffprobe_duration_ms(path)
        if ffprobe_duration_ms is not None:
            return ffprobe_duration_ms
        return CloudProductionGenerator._probe_wave_duration_ms(path)

    @staticmethod
    def _probe_wave_duration_ms(path: Path) -> Optional[int]:
        try:
            with wave.open(str(path), "rb") as handle:
                frame_rate = handle.getframerate()
                frame_count = handle.getnframes()
                if frame_rate <= 0 or frame_count <= 0:
                    return None
                return max(int(round(frame_count / frame_rate * 1000)), 1)
        except (wave.Error, EOFError, OSError):
            return None

    @staticmethod
    def _probe_ffprobe_duration_ms(path: Path) -> Optional[int]:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except (FileNotFoundError, OSError):
            return None
        if result.returncode != 0:
            return None
        raw = result.stdout.strip()
        if not raw:
            return None
        try:
            seconds = float(raw)
        except ValueError:
            return None
        return max(int(round(seconds * 1000)), 1)

    @staticmethod
    def _optional_int(value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_remote_reference(raw: str) -> bool:
        parsed = urllib.parse.urlparse(str(raw).strip())
        return parsed.scheme in {"http", "https"}

    def _trigger_and_poll(self, stage: str, stage_cfg: Dict[str, Any], payload: Dict[str, Any]) -> TaskResult:
        if self.client is None:
            raise CloudProductionError(f"{stage} requires production.api configuration")
        trigger_cfg = stage_cfg["trigger"]
        status_cfg = stage_cfg["status"]
        trigger_resp = self.client.request(trigger_cfg.get("method", "POST"), trigger_cfg["path"], payload)
        task_id = get_nested(trigger_resp, trigger_cfg.get("task_id_path", "data.task_id"))
        if self.dry_run and not task_id:
            task_id = f"dry-{stage}-task-id"
        if not task_id:
            raise CloudProductionError(f"{stage} did not return task_id")
        result = self._poll(stage, str(task_id), status_cfg)
        return TaskResult(stage=stage, task_id=str(task_id), response=result)

    def _poll(self, stage: str, task_id: str, status_cfg: Dict[str, Any]) -> Dict[str, Any]:
        success_statuses = set(status_cfg.get("success_statuses", ["succeeded", "done", "success"]))
        failure_statuses = set(status_cfg.get("failure_statuses", ["failed", "error", "canceled"]))
        status_path = status_cfg.get("status_path", "data.status")
        error_code_path = status_cfg.get("error_code_path", "error.code")
        error_message_path = status_cfg.get("error_message_path", "error.message")

        for index in range(1, self.max_poll_attempts + 1):
            path = status_cfg["path"].replace("{task_id}", urllib.parse.quote(task_id))
            resp = self.client.request(status_cfg.get("method", "GET"), path)
            status = str(get_nested(resp, status_path, "unknown")).lower()
            logging.info("阶段=%s 轮询=%d/%d task_id=%s status=%s", stage, index, self.max_poll_attempts, task_id, status)
            if self.dry_run:
                if index >= 2:
                    return {"status": "succeeded", "dry_run": True}
            elif status in success_statuses:
                return resp
            elif status in failure_statuses:
                code = get_nested(resp, error_code_path, "unknown_error")
                message = get_nested(resp, error_message_path, "no message")
                raise CloudProductionError(f"{stage} failed task_id={task_id}, code={code}, message={message}")
            time.sleep(self.poll_interval)
        raise CloudProductionError(f"{stage} polling timed out task_id={task_id}")
