from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PipelineContext:
    """Immutable lineage passed through one deterministic decision cycle."""

    generation_id: str
    source_cutoff: datetime

    def as_metadata(self) -> dict[str, str]:
        return {
            "data_generation_id": self.generation_id,
            "source_cutoff": self.source_cutoff.isoformat(),
        }
