"""Composition root for LS-DYNA text and binary readers."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterator

from ..contracts import AdapterProbe, ResultAdapter, SolverQuality, StateChunk
from .d3plot_reader import FIELD_GROUPS, LassoD3plotReader
from .text_results import parse_d3hsp, parse_glstat


class LsdynaResultAdapter(ResultAdapter):
    adapter_id = "lsdyna_d3plot"
    adapter_version = "1.0.0"

    def __init__(self, reader_factory: Callable[[Path], object] | None = None):
        self._reader_factory = reader_factory or LassoD3plotReader
        self._readers: dict[Path, object] = {}

    def _reader(self, result_dir: Path) -> object:
        root = Path(result_dir).resolve(strict=True)
        reader = self._readers.get(root)
        if reader is None:
            reader = self._reader_factory(root / "d3plot")
            self._readers[root] = reader
        return reader

    def probe(self, result_dir: Path) -> AdapterProbe:
        binary = self._reader(result_dir).probe()
        d3hsp = parse_d3hsp(result_dir / "d3hsp")
        glstat_path = result_dir / "glstat"
        glstat = parse_glstat(glstat_path) if glstat_path.is_file() else None
        quality = SolverQuality(
            termination=d3hsp.termination,
            problem_time=d3hsp.problem_time,
            termination_time=d3hsp.termination_time,
            final_state_time=float(binary.timesteps[-1]),
            max_hourglass_ratio=glstat.max_hourglass_ratio if glstat else None,
            issues=d3hsp.issues + (glstat.issues if glstat else ()),
        )
        return AdapterProbe(
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            geometry=binary.geometry,
            state_count=binary.state_count,
            fields=binary.fields,
            solver_quality=quality,
        )

    def iter_state_chunks(self, result_dir: Path, chunk_size: int) -> Iterator[StateChunk]:
        reader = self._reader(result_dir)
        for field_group in FIELD_GROUPS:
            yield from reader.iter_state_chunks(field_group, chunk_size)
