"""Base classes for output adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict

from ..models import AdapterResult, KernelOutput, ProductionBundle


class OutputAdapter(ABC):
    """Translate the canonical timeline model into one concrete output target."""

    target_name: str

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abstractmethod
    def render(
        self,
        *,
        output_dir: Path,
        bundle: ProductionBundle,
        kernel_output: KernelOutput,
        dry_run: bool,
    ) -> AdapterResult:
        """Render one output target into `output_dir`."""
