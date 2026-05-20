"""Top-level workflow for Video Director."""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .adapters import JianyingDraftAdapter, PlannedOutputAdapter, RenderedVideoAdapter
from .cloud_production import CloudProductionGenerator
from .kernel import NarrationFirstEditKernel
from .models import AdapterResult, KernelOutput, ProductionBundle, to_dict
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
        builder = ProductionBundleBuilder(self.cwd)
        bundle = builder.build(self.config)
        job_root, output_root, run_id = self._resolve_output_layout(bundle)
        kernel = self._build_kernel(pre_production=True)
        kernel_output = kernel.build(bundle)
        remote_manifest_path = ""

        if self._use_cloud_production():
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
        return {
            "job_id": bundle.job_id,
            "job_root": str(job_root),
            "output_root": str(output_root),
            "run_id": run_id,
            "timeline_path": str(output_root / "Timeline_Model.json"),
            "beat_sheet_path": str(output_root / "BeatSheet.json"),
            "edl_path": str(output_root / "Edit_Decision_List.json"),
            "remote_manifest_path": remote_manifest_path,
            "targets": [to_dict(result) for result in adapter_results],
        }

    def _build_kernel(self, *, pre_production: bool) -> NarrationFirstEditKernel:
        editing = copy.deepcopy(self.config.get("editing", {}))
        if pre_production and self._should_preserve_cloud_avatar_beats():
            editing["preserve_avatar_beats_without_clips"] = True
        return NarrationFirstEditKernel(editing)

    def _use_cloud_production(self) -> bool:
        production = self.config.get("production", {})
        return isinstance(production, dict) and str(production.get("mode", "config")).strip().lower() == "cloud"

    def _should_preserve_cloud_avatar_beats(self) -> bool:
        production = self.config.get("production", {})
        if not isinstance(production, dict):
            return False
        return self._use_cloud_production() and bool(production.get("enable_avatar_generation", False))

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
        raw_targets = outputs.get("targets", ["jianying_draft"])
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
