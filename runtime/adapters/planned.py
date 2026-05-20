"""Plan-only adapters for targets that are not implemented yet."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from ..models import AdapterResult, KernelOutput, ProductionBundle, to_dict
from .base import OutputAdapter


class PlannedOutputAdapter(OutputAdapter):
    """Write an adapter request artifact without claiming a final render exists."""

    def __init__(self, target_name: str, config: Dict[str, Any]):
        super().__init__(config)
        self.target_name = target_name

    def render(
        self,
        *,
        output_dir: Path,
        bundle: ProductionBundle,
        kernel_output: KernelOutput,
        dry_run: bool,
    ) -> AdapterResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = output_dir / f"{self.target_name}.request.json"
        payload = {
            "target": self.target_name,
            "status": "planned_not_implemented",
            "dry_run": dry_run,
            "job_id": bundle.job_id,
            "timeline": to_dict(kernel_output.timeline),
            "notes": self.config.get(
                "notes",
                "Target adapter has been reserved but no exporter has been implemented yet.",
            ),
        }
        artifact_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return AdapterResult(
            target=self.target_name,
            status="planned",
            artifact_path=str(artifact_path),
            note="adapter placeholder only",
        )
