"""Optional CPU embeddings and four snapshot-bound FAISS indexes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from .knowledge import INDEXES, KnowledgeBase

LOCAL = Path(__file__).resolve().parents[1] / "workspace/knowledge/lsdyna_20261107"
MODEL = "Xenova/multilingual-e5-small@761b726dd34fb83930e26aab4e9ac3899aa1fa78:int8"
MODEL_FILES = {
    "tokenizer.json": "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
    "model_quantized.onnx": "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193",
}
DIMENSION = 384
SCHEMA = "r12_e5_index_v1"
# E5 scores can be high even for unrelated queries. Keep the cutoff specific
# to the pinned embedding model and report out-of-scope errors in evaluation.
MIN_SEMANTIC_SCORE = 0.85


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _passage(record: dict) -> str:
    recipe = record.get("recipe", {})
    return "\n".join([record["title"], " ".join(record["aliases"]), record["summary"],
                      " ".join(record.get("case_families", [])), " ".join(recipe.get("steps", [])),
                      " ".join(record.get("steps", []))])


class VectorStore:
    def __init__(self, kb: KnowledgeBase, *, local: Path = LOCAL):
        if not kb.snapshot:
            raise ValueError("semantic indexes require a sealed catalog snapshot")
        self.kb = kb
        runtime = str(local / "vector_runtime")
        if runtime not in sys.path:
            sys.path.append(runtime)
        import faiss
        import numpy
        import onnxruntime
        from tokenizers import Tokenizer

        self.faiss = faiss
        self.np = numpy
        self.root = local / "vector_indexes" / kb.snapshot
        model_dir = local / "embedding_model"
        for file, expected in MODEL_FILES.items():
            if _sha(model_dir / file) != expected:
                raise ValueError(f"unexpected embedding model file: {file}")
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=384)
        self.tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = onnxruntime.InferenceSession(str(model_dir / "model_quantized.onnx"), options,
                                                    providers=["CPUExecutionProvider"])
        self.loaded = {}

    def embed(self, texts: list[str], *, query: bool = False):
        np = self.np
        prefix = "query: " if query else "passage: "
        batch = self.tokenizer.encode_batch([prefix + text for text in texts])
        ids = np.asarray([item.ids for item in batch], dtype=np.int64)
        mask = np.asarray([item.attention_mask for item in batch], dtype=np.int64)
        inputs = {"input_ids": ids, "attention_mask": mask}
        if any(info.name == "token_type_ids" for info in self.session.get_inputs()):
            inputs["token_type_ids"] = np.zeros_like(ids)
        tokens = self.session.run(["last_hidden_state"], inputs)[0]
        vectors = (tokens * mask[..., None]).sum(axis=1) / mask.sum(axis=1)[:, None]
        vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        if vectors.shape != (len(texts), DIMENSION) or not np.isfinite(vectors).all():
            raise ValueError("invalid E5 embeddings")
        self.faiss.normalize_L2(vectors)
        return vectors

    def build(self) -> dict:
        self.kb.verify_all()
        self.root.mkdir(parents=True, exist_ok=True)
        manifest = {"schema": SCHEMA, "snapshot_sha256": self.kb.snapshot, "model": MODEL,
                    "dimensions": DIMENSION, "indexes": {}}
        for name in INDEXES:
            records = [r for r in self.kb.records if r["index"] == name and r["admitted"]]
            index = self.faiss.IndexFlatIP(DIMENSION)
            for start in range(0, len(records), 8):
                index.add(self.embed([_passage(r) for r in records[start:start + 8]]))
            path = self.root / f"{name}.faiss"
            staged = path.with_suffix(".tmp")
            self.faiss.write_index(index, str(staged))
            staged.replace(path)
            manifest["indexes"][name] = {"count": len(records), "sha256": _sha(path),
                                         "record_ids": [r["id"] for r in records]}
        staged = self.root / "manifest.tmp"
        staged.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        staged.replace(self.root / "manifest.json")
        self.loaded.clear()
        return {**manifest, "directory": str(self.root)}

    def _index(self, name: str):
        if name not in self.loaded:
            manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
            if (manifest["schema"], manifest["snapshot_sha256"], manifest["model"]) != (SCHEMA, self.kb.snapshot, MODEL):
                raise ValueError("vector index metadata changed; rebuild the indexes")
            spec = manifest["indexes"][name]
            path = self.root / f"{name}.faiss"
            if _sha(path) != spec["sha256"]:
                raise ValueError(f"vector index changed: {name}")
            index = self.faiss.read_index(str(path))
            expected_ids = [r["id"] for r in self.kb.records if r["index"] == name and r["admitted"]]
            if spec["record_ids"] != expected_ids or index.ntotal != len(expected_ids) or index.d != DIMENSION:
                raise ValueError(f"vector index does not match catalog records: {name}")
            self.loaded[name] = index, expected_ids
        return self.loaded[name]

    def candidates(self, name: str, vector, eligible: set[str], *, limit: int = 3) -> list[tuple[str, float]]:
        index, ids = self._index(name)
        positions = self.np.asarray([i for i, key in enumerate(ids) if key in eligible], dtype=self.np.int64)
        if not len(positions):
            return []
        selector = self.faiss.IDSelectorBatch(positions)
        scores, matched = index.search(vector, min(limit, len(positions)),
                                       params=self.faiss.SearchParameters(sel=selector))
        return [(ids[int(position)], float(score)) for position, score in zip(matched[0], scores[0]) if position >= 0]

    def verify_indexes(self) -> None:
        for name in INDEXES:
            self._index(name)

    def search(self, name: str, query: str, eligible: set[str]) -> dict[str, float]:
        query_vector = self.embed([query], query=True)
        return {key: score for key, score in self.candidates(name, query_vector, eligible)
                if score >= MIN_SEMANTIC_SCORE}
