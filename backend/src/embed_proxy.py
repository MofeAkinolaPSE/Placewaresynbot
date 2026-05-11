"""embed_proxy.py — Local ONNX embedding inference (no external API calls).

Uses sentence-transformers/all-MiniLM-L6-v2 baked into the Docker image at
build time. Produces 384-dimensional L2-normalised embeddings compatible with
the Supabase pgvector `match_documents` RPC.

Model files are downloaded during `docker build` (Dockerfile model_downloader
stage) into `src/models/`. Zero runtime downloads; works fully offline.
"""
import logging
import numpy as np
from pathlib import Path

_MODELS_DIR = Path(__file__).parent / "models"
_EMBEDDING_DIM = 384
_MAX_LENGTH = 128

# Module-level singletons — loaded on first inference call, shared across workers
_session = None
_tokenizer = None


def _load_session():
    global _session
    if _session is not None:
        return _session
    import onnxruntime as ort

    model_path = _MODELS_DIR / "model.onnx"
    if not model_path.exists():
        raise FileNotFoundError(
            f"ONNX model not found at {model_path}. "
            "Ensure the Docker image was built (model is downloaded at build time)."
        )
    opts = ort.SessionOptions()
    opts.inter_op_num_threads = 1
    opts.intra_op_num_threads = 2
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    _session = ort.InferenceSession(str(model_path), sess_options=opts)
    logging.info("embed_proxy: ONNX model loaded from %s", model_path)
    return _session


def _load_tokenizer():
    global _tokenizer
    if _tokenizer is not None:
        return _tokenizer
    from tokenizers import Tokenizer

    tok_path = _MODELS_DIR / "tokenizer.json"
    if not tok_path.exists():
        raise FileNotFoundError(f"Tokenizer not found at {tok_path}.")
    _tokenizer = Tokenizer.from_file(str(tok_path))
    _tokenizer.enable_padding(pad_id=0, pad_token="[PAD]", length=_MAX_LENGTH)
    _tokenizer.enable_truncation(max_length=_MAX_LENGTH)
    logging.info("embed_proxy: tokenizer loaded from %s", tok_path)
    return _tokenizer


def _mean_pool(token_embeddings: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    """Weighted mean pool over token dimension, ignoring padding tokens."""
    mask = attention_mask[:, :, np.newaxis].astype(np.float32)  # (B, L, 1)
    summed = np.sum(token_embeddings * mask, axis=1)             # (B, H)
    counts = np.clip(mask.sum(axis=1), a_min=1e-9, a_max=None)  # (B, 1)
    return summed / counts                                        # (B, H)


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(norm == 0.0, 1.0, norm)


def get_embedding(query: str) -> list[float] | None:
    """Embed *query* using the local all-MiniLM-L6-v2 ONNX model.

    Returns a list of 384 floats (L2-normalised), or None on error.
    A None return triggers the graceful fallback path in /chat.
    """
    if not query or not query.strip():
        logging.warning("embed_proxy: empty query; returning None")
        return None
    try:
        tok = _load_tokenizer()
        sess = _load_session()

        enc = tok.encode(query)
        input_ids = np.array([enc.ids], dtype=np.int64)
        attention_mask = np.array([enc.attention_mask], dtype=np.int64)

        # Build feed dict — token_type_ids is optional depending on ONNX export
        feed: dict = {"input_ids": input_ids, "attention_mask": attention_mask}
        available_inputs = {inp.name for inp in sess.get_inputs()}
        if "token_type_ids" in available_inputs:
            feed["token_type_ids"] = np.zeros_like(input_ids, dtype=np.int64)

        output_names = [out.name for out in sess.get_outputs()]
        raw_outputs = sess.run(None, feed)
        output_map = dict(zip(output_names, raw_outputs))

        if "sentence_embedding" in output_map:
            # Model exported with pooling layer — use directly
            embedding = _l2_normalize(output_map["sentence_embedding"])  # (1, 384)
        else:
            # Standard BERT-style export — apply mean pooling manually
            hidden = output_map.get("last_hidden_state", raw_outputs[0])  # (1, L, 384)
            embedding = _l2_normalize(_mean_pool(hidden, attention_mask))  # (1, 384)

        result: list[float] = embedding[0].tolist()
        if len(result) != _EMBEDDING_DIM:
            logging.error(
                "embed_proxy: unexpected embedding dim %d (expected %d)",
                len(result), _EMBEDDING_DIM,
            )
            return None
        return result

    except Exception:
        logging.exception("embed_proxy: ONNX inference failed")
        return None