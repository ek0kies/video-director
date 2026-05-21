"""Top-level workflow for Video Director."""

from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .adapters import JianyingDraftAdapter, PlannedOutputAdapter, RenderedVideoAdapter
from .cloud_production import CloudProductionGenerator
from .kernel import NarrationFirstEditKernel
from .material_planning import build_material_copy_plan
from .models import AdapterResult, KernelOutput, ProductionBundle, TimelineClip, to_dict
from .operation_confirmation import ensure_operation_confirmed
from .production import ProductionBundleBuilder


class WorkflowError(RuntimeError):
    """Raised when the Video Director workflow cannot complete."""


SENSITIVE_CONFIG_TOKENS = (
    "token",
    "api_key",
    "apikey",
    "access_key",
    "secret_key",
    "secret",
    "password",
)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _mask_sensitive_value(value: Any) -> Any:
    if value in (None, ""):
        return value
    return "***REDACTED***"


def _sanitize_config_snapshot(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).strip().lower()
            if any(token in normalized_key for token in SENSITIVE_CONFIG_TOKENS):
                sanitized[str(key)] = _mask_sensitive_value(item)
                continue
            sanitized[str(key)] = _sanitize_config_snapshot(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_config_snapshot(item) for item in value]
    return value


class VideoDirectorWorkflow:
    """Run the Video Director pipeline inside the dedicated new directory."""

    def __init__(self, config: Dict[str, Any], *, cwd: Path, dry_run: bool):
        self.config = config
        self.cwd = cwd
        self.dry_run = dry_run

    def run(self) -> Dict[str, Any]:
        ensure_operation_confirmed(self.config)
        builder = ProductionBundleBuilder(self.cwd)
        bundle = builder.build(self.config)
        job_root, output_root, run_id = self._resolve_output_layout(bundle)
        copy_plan_path = output_root / "Material_Copy_Plan.json"
        _write_json(copy_plan_path, build_material_copy_plan(self.config, cwd=self.cwd))
        kernel = self._build_kernel(pre_production=True)
        kernel_output = kernel.build(bundle)
        self._validate_visual_timeline(kernel_output)
        self._validate_timeline_handoff(kernel_output)
        remote_manifest_path = ""

        if self._use_remote_production():
            _write_json(output_root / "Production_Bundle.initial.json", to_dict(bundle))
            generator = CloudProductionGenerator(
                self.config["production"],
                cwd=self.cwd,
                output_root=output_root,
                manifest_root=job_root,
                dry_run=self.dry_run,
            )
            remote_manifest_path = str(generator.manifest_path.resolve()) if generator.checkpoint_enabled else ""
            bundle = generator.produce(bundle, kernel_output.beat_sheet)
            kernel_output = self._build_kernel(pre_production=False).build(bundle)
            self._validate_visual_timeline(kernel_output)
            self._validate_timeline_handoff(kernel_output)

        _write_json(output_root / "config.snapshot.json", _sanitize_config_snapshot(self.config))
        _write_json(output_root / "Production_Bundle.json", to_dict(bundle))
        _write_json(output_root / "BeatSheet.json", {"beats": to_dict(kernel_output.beat_sheet)})
        _write_json(output_root / "Edit_Decision_List.json", {"edl": to_dict(kernel_output.edit_decisions)})
        _write_json(output_root / "Timeline_Model.json", to_dict(kernel_output.timeline))

        adapter_results = self._render_targets(
            output_root=output_root,
            bundle=bundle,
            kernel_output=kernel_output,
        )
        self._write_latest_run_pointer(job_root=job_root, output_root=output_root, run_id=run_id)
        deliverables = self._public_deliverables(adapter_results)
        result: Dict[str, Any] = {
            "status": "rendered" if any(item.get("status") == "rendered" for item in deliverables) else "completed",
            "job_id": bundle.job_id,
            "run_id": run_id,
            "deliverables": deliverables,
            "latest_run": str(job_root / "latest_run.json"),
        }
        if self._should_report_internal_artifacts():
            result["internal"] = {
                "job_root": str(job_root),
                "output_root": str(output_root),
                "timeline_path": str(output_root / "Timeline_Model.json"),
                "beat_sheet_path": str(output_root / "BeatSheet.json"),
                "edl_path": str(output_root / "Edit_Decision_List.json"),
                "copy_plan_path": str(copy_plan_path),
                "remote_manifest_path": remote_manifest_path,
                "targets": [to_dict(adapter_result) for adapter_result in adapter_results],
            }
        return result

    def _build_kernel(self, *, pre_production: bool) -> NarrationFirstEditKernel:
        editing = copy.deepcopy(self.config.get("editing", {}))
        if pre_production and self._should_preserve_cloud_avatar_beats():
            editing["preserve_avatar_beats_without_clips"] = True
        return NarrationFirstEditKernel(editing)

    def _use_cloud_production(self) -> bool:
        production = self.config.get("production", {})
        return isinstance(production, dict) and str(production.get("mode", "config")).strip().lower() == "cloud"

    def _use_remote_production(self) -> bool:
        production = self.config.get("production", {})
        if not isinstance(production, dict):
            return False
        return self._use_cloud_production() or bool(production.get("enable_tts_generation", False))

    def _should_preserve_cloud_avatar_beats(self) -> bool:
        production = self.config.get("production", {})
        if not isinstance(production, dict):
            return False
        return self._use_cloud_production() and bool(production.get("enable_avatar_generation", False))

    def _should_report_internal_artifacts(self) -> bool:
        outputs = self.config.get("outputs", {})
        configured = bool(outputs.get("report_internal_artifacts", False)) if isinstance(outputs, dict) else False
        return configured or os.environ.get("VIDEO_DIRECTOR_VERBOSE_RESULT", "").strip() in {"1", "true", "yes"}

    @staticmethod
    def _validate_visual_timeline(kernel_output: KernelOutput) -> None:
        tracks = kernel_output.timeline.tracks
        visual_clips = list(tracks.get("material_track", [])) + list(tracks.get("avatar_track", []))
        usable = [
            clip
            for clip in visual_clips
            if VideoDirectorWorkflow._is_real_visual_source(str(clip.source_path or "").strip())
            and clip.end_ms > clip.start_ms
        ]
        if not usable:
            raise WorkflowError("final video requires at least one real visual asset; refusing subtitle-only output")

    @staticmethod
    def _is_real_visual_source(source: str) -> bool:
        if not source or source == "generated://black":
            return False
        lowered = source.lower()
        if lowered.startswith(("http://", "https://")):
            return True
        return Path(source).suffix.lower() in {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp"}

    @staticmethod
    def _validate_timeline_handoff(kernel_output: KernelOutput) -> None:
        timeline = kernel_output.timeline
        duration_ms = max(int(timeline.duration_ms), 1)
        tracks = timeline.tracks
        visual_clips = list(tracks.get("material_track", [])) + list(tracks.get("avatar_track", []))

        for clip in VideoDirectorWorkflow._all_timeline_clips(tracks):
            clip_duration_ms = clip.end_ms - clip.start_ms
            if clip.start_ms < 0 or clip_duration_ms <= 0:
                raise WorkflowError(
                    f"timeline handoff failed: {clip.track}:{clip.clip_id} has invalid time range "
                    f"{clip.start_ms}-{clip.end_ms}ms"
                )
            if clip.end_ms > duration_ms:
                raise WorkflowError(
                    f"timeline handoff failed: {clip.track}:{clip.clip_id} ends at {clip.end_ms}ms "
                    f"after timeline duration {duration_ms}ms"
                )
            VideoDirectorWorkflow._validate_clip_media_window(clip)

        for cue in timeline.subtitles:
            if cue.start_ms < 0 or cue.end_ms <= cue.start_ms:
                raise WorkflowError(
                    f"timeline handoff failed: subtitle {cue.cue_id} has invalid time range "
                    f"{cue.start_ms}-{cue.end_ms}ms"
                )
            if cue.end_ms > duration_ms:
                raise WorkflowError(
                    f"timeline handoff failed: subtitle {cue.cue_id} ends at {cue.end_ms}ms "
                    f"after timeline duration {duration_ms}ms"
                )
            if not VideoDirectorWorkflow._has_visual_coverage(visual_clips, cue.start_ms, cue.end_ms):
                raise WorkflowError(
                    f"timeline handoff failed: subtitle {cue.cue_id} has no visual coverage for "
                    f"{cue.start_ms}-{cue.end_ms}ms"
                )

    @staticmethod
    def _all_timeline_clips(tracks: Dict[str, List[TimelineClip]]) -> Iterable[TimelineClip]:
        for clips in tracks.values():
            for clip in clips:
                yield clip

    @staticmethod
    def _validate_clip_media_window(clip: TimelineClip) -> None:
        if clip.media_end_ms is None:
            return
        source = str(clip.source_path or "").strip()
        if clip.track in {"material_track", "avatar_track"} and VideoDirectorWorkflow._is_still_image_source(source):
            return

        target_duration_ms = max(int(clip.end_ms - clip.start_ms), 1)
        media_duration_ms = int(clip.media_end_ms) - int(clip.media_start_ms)
        if media_duration_ms >= target_duration_ms:
            return

        raise WorkflowError(
            f"timeline handoff failed: {clip.track}:{clip.clip_id} target duration "
            f"{target_duration_ms}ms exceeds source window {max(media_duration_ms, 0)}ms; "
            "refusing to stretch, loop, or pad media"
        )

    @staticmethod
    def _has_visual_coverage(visual_clips: List[TimelineClip], start_ms: int, end_ms: int) -> bool:
        return any(
            clip.start_ms <= start_ms
            and clip.end_ms >= end_ms
            and VideoDirectorWorkflow._is_real_visual_source(str(clip.source_path or "").strip())
            for clip in visual_clips
        )

    @staticmethod
    def _is_still_image_source(source: str) -> bool:
        return Path(source).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp"}

    def _resolve_output_layout(self, bundle: ProductionBundle) -> Tuple[Path, Path, str]:
        outputs = self.config.get("outputs", {})
        raw = str(outputs.get("output_root", "output/video_director")).strip() or "output/video_director"
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (self.cwd / path).resolve()
        job_root = path / bundle.job_id
        run_cfg = outputs.get("run_management", {}) if isinstance(outputs.get("run_management"), dict) else {}
        run_enabled = bool(run_cfg.get("enabled", True))
        if run_enabled:
            runs_dirname = str(run_cfg.get("runs_dirname", "runs")).strip() or "runs"
            run_id = str(run_cfg.get("run_id", "")).strip() or self._generate_run_id()
            output_root = job_root / runs_dirname / run_id
        else:
            run_id = ""
            output_root = job_root
        output_root.mkdir(parents=True, exist_ok=True)
        return job_root, output_root, run_id

    @staticmethod
    def _generate_run_id() -> str:
        return time.strftime("run-%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"

    def _write_latest_run_pointer(self, *, job_root: Path, output_root: Path, run_id: str) -> None:
        outputs = self.config.get("outputs", {})
        run_cfg = outputs.get("run_management", {}) if isinstance(outputs.get("run_management"), dict) else {}
        if not bool(run_cfg.get("enabled", True)):
            return
        pointer_name = str(run_cfg.get("latest_pointer_name", "latest_run.json")).strip() or "latest_run.json"
        _write_json(
            job_root / pointer_name,
            {
                "job_root": str(job_root),
                "run_id": run_id,
                "output_root": str(output_root),
                "updated_at": int(time.time()),
            },
        )

    @staticmethod
    def _public_deliverables(adapter_results: List[AdapterResult]) -> List[Dict[str, Any]]:
        deliverables: List[Dict[str, Any]] = []
        for result in adapter_results:
            artifact = str(result.artifact_path or "").strip()
            suffix = Path(artifact).suffix.lower()
            if suffix not in {".mp4", ".mov", ".m4v"}:
                continue
            deliverables.append(
                {
                    "target": result.target,
                    "status": result.status,
                    "type": "video",
                    "path": artifact,
                    "note": result.note,
                }
            )
        return deliverables

    def _render_targets(
        self,
        *,
        output_root: Path,
        bundle: ProductionBundle,
        kernel_output: KernelOutput,
    ) -> List[AdapterResult]:
        outputs = self.config.get("outputs", {})
        targets = self._normalize_targets(outputs)
        results: List[AdapterResult] = []
        for target in targets:
            adapter = self._build_adapter(target, outputs)
            target_dir = output_root / "targets" / target
            results.append(
                adapter.render(
                    output_dir=target_dir,
                    bundle=bundle,
                    kernel_output=kernel_output,
                    dry_run=self.dry_run,
                )
            )
        return results

    @staticmethod
    def _normalize_targets(outputs: Dict[str, Any]) -> List[str]:
        raw_targets = outputs.get("targets", ["final_render"])
        targets = [str(item).strip() for item in raw_targets if str(item).strip()]
        if outputs.get("preview_enabled", False):
            targets.append("preview_render")
        if outputs.get("final_render_enabled", False):
            targets.append("final_render")
        deduped: List[str] = []
        for target in targets:
            if target not in deduped:
                deduped.append(target)
        if not deduped:
            raise WorkflowError("outputs.targets resolved to an empty set")
        return deduped

    @staticmethod
    def _build_adapter(target: str, outputs: Dict[str, Any]):
        if target == "jianying_draft":
            return JianyingDraftAdapter(outputs.get("jianying", {}))
        if target in {"preview_render", "final_render"}:
            return RenderedVideoAdapter(target, outputs.get(target, {}))
        planned_targets = {"davinci_resolve", "premiere_xml", "preview_render", "final_render"}
        if target in planned_targets:
            return PlannedOutputAdapter(target, outputs.get(target, {}))
        raise WorkflowError(f"unsupported output target: {target}")
