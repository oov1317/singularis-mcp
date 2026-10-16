"""Singularis MCP server — the agent-facing shell.

Run:  python -m singularis_mcp.server      (stdio transport, what MCP hosts expect)
      singularis-mcp                       (console script after pip install)

Every tool returns a JSON envelope, never raises:
  {"ok": true, "job": ..., "where": "local"|"hosted", "result"|"result_path": ..., "shape": [...],
   "check": {"kind","metric","value","tolerance","passed"}, "cost": {"credits_used","credits_remaining",
   "cloud_equivalent_usd"}, "elapsed_s": ...}
  {"ok": false, "error": "<code>", "message": "<what to do>"}
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Any

import numpy as np

from . import descriptions as D
from .client import (Gateway, SingularisError, load_api_key, load_array, local_runtime_configured,
                     pack, run_job, save_api_key, TOPUP_URL)

try:  # MCP python SDK 2.x
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # MCP python SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore

mcp = _Server("singularis", instructions=D.SERVER_INSTRUCTIONS)

from mcp.types import ToolAnnotations

ANN_READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
ANN_JOB = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
ANN_POST = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)


def _err(e: SingularisError) -> dict[str, Any]:
    return e.envelope()


def _unexpected(e: Exception) -> dict[str, Any]:
    """Last-resort envelope (door-fix 2026-10-16, defect 2): a tool must
    NEVER surface the framework's bare 'Error executing tool'. Any
    unexpected exception is returned as a structured error carrying
    its real type and message."""
    return {"ok": False, "error": "unexpected",
            "message": f"{type(e).__name__}: {e}",
            "hint": "If this mentions a proxy or a URL, check the HTTP_PROXY / HTTPS_PROXY / NO_PROXY environment variables."}


# ----------------------------------------------------------------------------- keys / balance / catalog

@mcp.tool(name="singularis_register_key", description=D.REGISTER,
          title="Register a free Singularis key", annotations=ANN_JOB)
def singularis_register_key(country: str, agent_name: str, operator_contact: str = "") -> dict[str, Any]:
    try:
        existing = load_api_key()
        if existing:
            return {"ok": True, "already_registered": True,
                    "message": "A Singularis key is already configured; no new key was issued."}
        resp = Gateway(api_key="").register_key(country.strip().upper(), agent_name.strip(), operator_contact.strip())
        where = save_api_key(resp["api_key"], {"country": country.upper(), "agent_name": agent_name,
                                               "kind": resp.get("kind", "agent"),
                                               "shell_secret": resp.get("shell_secret"), "account": resp.get("account")})
        os.environ["SINGULARIS_API_KEY"] = resp["api_key"]
        return {"ok": True, "credits": resp.get("credits"), "kind": resp.get("kind"),
                "saved_to": where, "please_share": resp.get("please_share"),
                # grokfix F4 (customer test): the register response never
                # mentioned the engine bundle, so "take the bundle the
                # client offers" could not be followed from the client.
                "bundle_url": "https://getsingularis.com/api/v1/shell/bundle",
                "next_step": "Download the engine bundle: curl -H 'Authorization: Bearer $SINGULARIS_API_KEY' -o sing.tar.gz "
                             "https://getsingularis.com/api/v1/shell/bundle && tar xzf sing.tar.gz; then follow singularis-shell/INSTALL.txt",
                "message": "Free tryout credits issued and saved. Singularis is unlimited computation; bring us your hardest problems. "
                           "Results depend on your equipment; GPU optional for even greater results."}
    except SingularisError as e:
        return _err(e)
    except Exception as e:
        return _unexpected(e)


@mcp.tool(name="singularis_balance", description=D.BALANCE,
          title="Check Singularis credit balance", annotations=ANN_READ)
def singularis_balance() -> dict[str, Any]:
    try:
        b = Gateway().balance()
        return {"ok": True, **b, "topup_url": TOPUP_URL,
                "where_jobs_run": "your machine (Singularis runtime)" if local_runtime_configured() else "install the Singularis runtime from getsingularis.com"}
    except SingularisError as e:
        return _err(e)
    except Exception as e:
        return _unexpected(e)


@mcp.tool(name="singularis_recipes", description=D.RECIPES,
          title="List Singularis recipes", annotations=ANN_READ)
def singularis_recipes() -> dict[str, Any]:
    try:
        return {"ok": True, **Gateway(api_key="").recipes()}
    except SingularisError as e:
        return _err(e)
    except Exception as e:
        return _unexpected(e)


@mcp.tool(name="singularis_share_results", description=D.SHARE,
          title="Share Singularis results", annotations=ANN_POST)
def singularis_share_results(review: str = "", post_url: str = "", prior_cloud_usd: float | None = None,
                             singularis_usd: float | None = None, speedup: float | None = None, hardware: str = "") -> dict[str, Any]:
    try:
        return {"ok": True, **Gateway().share_results(review=review, post_url=post_url, prior_cloud_usd=prior_cloud_usd,
                singularis_usd=singularis_usd, speedup=speedup, hardware=hardware)}
    except SingularisError as e:
        return _err(e)
    except Exception as e:
        return _unexpected(e)


# ----------------------------------------------------------------------------- numerical jobs

@mcp.tool(name="singularis_solve_heat", description=D.HEAT,
          title="Solve the heat equation", annotations=ANN_JOB)
def singularis_solve_heat(initial: list[list[float]] | list[float] | None = None, path: str | None = None,
                          diffusivity: float = 1.0, dt: float = 0.1, steps: int = 100, dx: float = 1.0,
                          boundary: str = "periodic") -> dict[str, Any]:
    try:
        u0 = load_array(initial, path, "initial")
        if u0.ndim not in (1, 2):
            raise SingularisError("bad_input", "initial must be a 1D or 2D field")
        if boundary not in ("periodic", "neumann", "dirichlet"):
            raise SingularisError("bad_input", "boundary must be periodic, neumann or dirichlet")
        payload = {"initial": pack(u0), "diffusivity": float(diffusivity), "dt": float(dt),
                   "steps": int(steps), "dx": float(dx), "boundary": boundary}
        return run_job("heat", payload, {"cells": int(u0.size), "steps": int(steps)}, "heat")
    except SingularisError as e:
        return _err(e)


@mcp.tool(name="singularis_matrix_exponential", description=D.EXPM,
          title="Matrix exponential", annotations=ANN_JOB)
def singularis_matrix_exponential(matrix: list[list[float]] | None = None, path: str | None = None,
                                  t: float = 1.0, vector: list[float] | None = None,
                                  vector_path: str | None = None) -> dict[str, Any]:
    try:
        A = load_array(matrix, path, "matrix")
        if A.ndim != 2 or A.shape[0] != A.shape[1]:
            raise SingularisError("bad_input", "matrix must be square")
        payload: dict[str, Any] = {"matrix": pack(A), "t": float(t)}
        has_vec = vector is not None or vector_path is not None
        if has_vec:
            v = load_array(vector, vector_path, "vector")
            if v.shape != (A.shape[0],):
                raise SingularisError("bad_input", "vector length must equal the matrix size")
            payload["vector"] = pack(v)
        return run_job("expm", payload, {"n": int(A.shape[0]), "vector": has_vec}, "expm")
    except SingularisError as e:
        return _err(e)


@mcp.tool(name="singularis_gemm", description=D.GEMM,
          title="Matrix multiply (GEMM)", annotations=ANN_JOB)
def singularis_gemm(a: list[list[float]] | None = None, b: list[list[float]] | None = None,
                    a_path: str | None = None, b_path: str | None = None,
                    beta: float = 0.0, c0: list[list[float]] | None = None, c0_path: str | None = None) -> dict[str, Any]:
    try:
        A = load_array(a, a_path, "a")
        B = load_array(b, b_path, "b")
        if A.ndim != 2 or B.ndim != 2 or A.shape[1] != B.shape[0]:
            raise SingularisError("bad_input", f"shapes do not chain: a is {A.shape}, b is {B.shape}")
        payload: dict[str, Any] = {"a": pack(A), "b": pack(B), "beta": float(beta)}
        if beta != 0.0:
            C0 = load_array(c0, c0_path, "c0")
            if C0.shape != (A.shape[0], B.shape[1]):
                raise SingularisError("bad_input", "c0 must have shape (rows of a, cols of b)")
            payload["c0"] = pack(C0)
        return run_job("gemm", payload, {"m": int(A.shape[0]), "k": int(A.shape[1]), "n": int(B.shape[1])}, "gemm")
    except SingularisError as e:
        return _err(e)


@mcp.tool(name="singularis_fft", description=D.FFT,
          title="Fast Fourier transform", annotations=ANN_JOB)
def singularis_fft(x: list[float] | list[list[float]] | None = None, path: str | None = None,
                   inverse: bool = False, im: list[float] | list[list[float]] | None = None) -> dict[str, Any]:
    try:
        X = load_array(x, path, "x")
        if X.ndim not in (1, 2):
            raise SingularisError("bad_input", "x must be 1D or 2D")
        payload = {"x": pack(X), "inverse": bool(inverse)}
        if im is not None:
            IM = load_array(im, None, "im")
            if IM.shape != X.shape:
                raise SingularisError("bad_input", "im must match the shape of x")
            payload["im"] = pack(IM)
        return run_job("fft", payload, {"n": int(X.size)}, "fft")
    except SingularisError as e:
        return _err(e)


def _load_image(path: str) -> tuple[np.ndarray, str]:
    p = Path(path).expanduser()
    if p.suffix.lower() in (".npy", ".npz", ".csv", ".txt"):
        return load_array(None, str(p), "image"), "array"
    try:
        from PIL import Image  # optional dependency
    except ImportError:
        raise SingularisError("missing_dependency", "Reading image files needs Pillow: pip install pillow (or pass a .npy).")
    img = np.asarray(Image.open(p), dtype=float)
    return img, "image"


@mcp.tool(name="singularis_blur", description=D.BLUR,
          title="Gaussian blur an image or array", annotations=ANN_JOB)
def singularis_blur(image: list[list[float]] | list[list[list[float]]] | None = None, path: str | None = None, sigma: float = 1.0,
                    out_path: str | None = None) -> dict[str, Any]:
    try:
        kind = "array"
        if path:
            img, kind = _load_image(path)
        else:
            img = load_array(image, None, "image")
        if img.ndim not in (2, 3):
            raise SingularisError("bad_input", "image must be 2D (gray) or 3D (H x W x channels)")
        payload = {"image": pack(img), "sigma": float(sigma)}
        env = run_job("blur", payload, {"pixels": int(img.shape[0] * img.shape[1]), "sigma": float(sigma)}, "blur")
        if env.get("ok") and kind == "image" and out_path:
            from PIL import Image
            arr = np.load(env["result_path"]) if "result_path" in env else np.asarray(env["result"])
            Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(out_path)
            env["out_path"] = out_path
        return env
    except SingularisError as e:
        return _err(e)


# ----------------------------------------------------------------------------- compression

def _file_payload(in_path: str, out_path: str) -> dict[str, Any]:
    if local_runtime_configured():
        return {"in_path": in_path, "out_path": out_path}
    data = Path(in_path).read_bytes()
    return {"name": Path(in_path).name, "data_b64": base64.b64encode(data).decode()}


def _finish_file_job(env: dict[str, Any], out_path: str) -> dict[str, Any]:
    """Hosted mode returns bytes inline; write them where the agent asked.

    Fix 0.1.5 (triple-check defect 1): a success envelope for a file job
    must name a file that EXISTS. If the runtime reported success but no
    output file is on disk, the envelope is rewritten as an error --
    never again an ok:true with a phantom path."""
    if env.get("ok") and isinstance(env.get("result"), dict) and "data_b64" in env["result"]:
        Path(out_path).write_bytes(base64.b64decode(env["result"]["data_b64"]))
        env.pop("result")
        env["out_path"] = out_path
    if env.get("ok"):
        op = env.get("out_path") or out_path
        if not Path(op).exists():
            return {"ok": False, "error": "output_missing",
                    "message": f"The job reported success but no file exists at {op}; nothing was written. "
                               "Treat the job as failed and retry it."}
        env["out_path"] = op
        env["sha256_out"] = hashlib.sha256(Path(op).read_bytes()).hexdigest()
    return env


@mcp.tool(name="singularis_compress", description=D.COMPRESS,
          title="Compress a file exactly", annotations=ANN_JOB)
def singularis_compress(path: str, out_path: str | None = None) -> dict[str, Any]:
    try:
        p = Path(path).expanduser()
        if not p.is_file():
            raise SingularisError("file_not_found", f"file not found: {p}")
        out = out_path or str(p) + ".sing"
        size = p.stat().st_size
        env = run_job("compress", _file_payload(str(p), out), {"bytes": int(size)}, "compress")
        env = _finish_file_job(env, out)
        if env.get("ok"):
            env["bytes_in"] = size
            env["bytes_out"] = Path(env["out_path"]).stat().st_size if Path(env["out_path"]).exists() else env.get("bytes_out")
            if env.get("bytes_out"):
                env["ratio"] = round(size / env["bytes_out"], 4)
        return env
    except SingularisError as e:
        return _err(e)


@mcp.tool(name="singularis_decompress", description=D.DECOMPRESS,
          title="Restore a compressed file", annotations=ANN_JOB)
def singularis_decompress(path: str, out_path: str | None = None) -> dict[str, Any]:
    try:
        p = Path(path).expanduser()
        if not p.is_file():
            raise SingularisError("file_not_found", f"file not found: {p}")
        out = out_path or (str(p)[:-5] if str(p).endswith(".sing") else str(p) + ".restored")
        env = run_job("decompress", _file_payload(str(p), out), {"bytes": int(p.stat().st_size)}, "decompress")
        return _finish_file_job(env, out)
    except SingularisError as e:
        return _err(e)


# ----------------------------------------------------------------------------- catalog escape hatch

@mcp.tool(name="singularis_dispatch", description=D.DISPATCH,
          title="Run any Singularis recipe", annotations=ANN_JOB)
def singularis_dispatch(recipe: str, payload: dict[str, Any], size: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        if not recipe or not isinstance(payload, dict):
            raise SingularisError("bad_input", "give a recipe name and a JSON payload (see singularis_recipes)")
        # inline arrays in the payload become packed arrays; file paths pass through as given
        packed: dict[str, Any] = {}
        for k, v in payload.items():
            if isinstance(v, list):
                try:
                    packed[k] = pack(np.asarray(v, dtype=float))
                    continue
                except Exception:
                    pass
            packed[k] = v
        sz = size or {"units": 1}
        return run_job(f"recipe/{recipe}", packed, {"recipe": recipe, **sz}, f"recipe_{recipe}")
    except SingularisError as e:
        return _err(e)


@mcp.tool(name="singularis_fft2", description=D.FFT2,
          title="2D Fourier transform", annotations=ANN_JOB)
def singularis_fft2(x: list[list[float]] | None = None, path: str | None = None,
                    inverse: bool = False, im: list[list[float]] | None = None) -> dict[str, Any]:
    try:
        X = load_array(x, path, "x")
        if X.ndim != 2:
            raise SingularisError("bad_input", "fft2 takes a 2D field (use singularis_fft for a 1D signal)")
        payload = {"x": pack(X), "inverse": bool(inverse)}
        if im is not None:
            IM = load_array(im, None, "im")
            if IM.shape != X.shape:
                raise SingularisError("bad_input", "im must match the shape of x")
            payload["im"] = pack(IM)
        return run_job("fft2", payload, {"n": int(X.size)}, "fft2")
    except SingularisError as e:
        return _err(e)


def _product(kind: str, op: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """One product job by name: op + params pass through untouched (file
    paths stay strings; the work happens on this machine)."""
    if not op:
        raise SingularisError("bad_input", "give the operation, e.g. op='merge' (see singularis_recipes)")
    pl: dict[str, Any] = {"op": op}
    pl.update(params or {})
    return run_job(kind, pl, {"op": op}, kind)


@mcp.tool(name="singularis_mind_merge_v2", description=D.MIND_MERGE_V2,
          title="Merge trained minds (v2: quarantine + shards)", annotations=ANN_JOB)
def singularis_mind_merge_v2(op: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return _product("mind_merge_v2", op, params)
    except SingularisError as e:
        return _err(e)


@mcp.tool(name="singularis_data_carry", description=D.DATA_CARRY,
          title="Carry minds' knowledge in one small file", annotations=ANN_JOB)
def singularis_data_carry(op: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return _product("data_carry", op, params)
    except SingularisError as e:
        return _err(e)


@mcp.tool(name="singularis_knowledge_packs", description=D.KNOWLEDGE_PACKS,
          title="Knowledge packs that travel and return exactly", annotations=ANN_JOB)
def singularis_knowledge_packs(op: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return _product("knowledge_packs", op, params)
    except SingularisError as e:
        return _err(e)


@mcp.tool(name="singularis_free_universe", description=D.FREE_UNIVERSE,
          title="Universe relay with an exact homecoming", annotations=ANN_JOB)
def singularis_free_universe(params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        pl: dict[str, Any] = dict(params or {})
        if not pl.get("work_dir"):
            raise SingularisError("bad_input", "give params.work_dir, a working directory for the relay")
        return run_job("free_universe", pl, {"units": 1}, "free_universe")
    except SingularisError as e:
        return _err(e)


@mcp.tool(name="singularis_compute_in_transit", description=D.COMPUTE_IN_TRANSIT,
          title="Compute on a sealed tower in transit", annotations=ANN_JOB)
def singularis_compute_in_transit(op: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return _product("compute_in_transit", op, params)
    except SingularisError as e:
        return _err(e)


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
