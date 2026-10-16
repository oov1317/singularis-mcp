"""Singularis gateway client + local runtime connector.

This is the agent-facing SHELL. It contains nothing of the engine. It talks to:

  * the public Singularis gateway (metering, keys, balance, recipes, hosted jobs), and
  * optionally a Singularis runtime that the operator installs on this machine
    (set SINGULARIS_ENGINE_CMD or SINGULARIS_ENGINE_URL). In that mode the
    numbers never leave this machine: the gateway only sees job kind and size.

Environment variables
---------------------
SINGULARIS_GATEWAY      base URL of the gateway (default https://getsingularis.com/api/v1)
SINGULARIS_API_KEY      API key (optional; the register tool can obtain one and save it)
SINGULARIS_ENGINE_CMD   command that runs the Singularis runtime (JSON in on stdin, JSON out on stdout)
SINGULARIS_ENGINE_URL   OR a local HTTP endpoint of the Singularis runtime (POST {kind, payload})
SINGULARIS_RESULT_DIR   where large results are written as files (default ~/.singularis/results)
SINGULARIS_INLINE_MAX   max number of elements returned inline in JSON (default 4096)
SINGULARIS_COUNTRY      ISO country code used by the register tool (default: ask / US)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import resource
import json
import os
import stat
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import numpy as np

DEFAULT_GATEWAY = "https://getsingularis.com/api/v1"
TOPUP_URL = "https://getsingularis.com/credits"
CRED_PATH = Path(os.environ.get("SINGULARIS_HOME", Path.home() / ".singularis")) / "credentials.json"


# ----------------------------------------------------------------------------- config

def gateway_url() -> str:
    return os.environ.get("SINGULARIS_GATEWAY", DEFAULT_GATEWAY).rstrip("/")


def result_dir() -> Path:
    p = Path(os.environ.get("SINGULARIS_RESULT_DIR", Path.home() / ".singularis" / "results"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def inline_max() -> int:
    return int(os.environ.get("SINGULARIS_INLINE_MAX", "4096"))


def load_api_key() -> str | None:
    key = os.environ.get("SINGULARIS_API_KEY")
    if key:
        return key
    try:
        return json.loads(CRED_PATH.read_text())["api_key"]
    except Exception:
        return None


def save_api_key(key: str, meta: dict[str, Any] | None = None) -> str:
    CRED_PATH.parent.mkdir(parents=True, exist_ok=True)
    CRED_PATH.write_text(json.dumps({"api_key": key, **(meta or {})}, indent=2))
    try:
        CRED_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass
    return str(CRED_PATH)


def local_runtime_configured() -> bool:
    return bool(os.environ.get("SINGULARIS_ENGINE_CMD") or os.environ.get("SINGULARIS_ENGINE_URL"))


# ----------------------------------------------------------------------------- errors

class SingularisError(Exception):
    """An error the agent should read, not a crash."""

    def __init__(self, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra

    def envelope(self) -> dict[str, Any]:
        return {"ok": False, "error": self.code, "message": self.message, **self.extra}


def _full(text: str, limit: int = 8000) -> str:
    """Error text without silent truncation (door-fix defect 3): short
    text passes through whole; long text keeps its head AND its tail --
    the tail is where the actual exception line lives -- with the
    omission stated, never hidden."""
    if len(text) <= limit:
        return text
    return text[:2000] + f"\n... [{len(text) - 6000} characters omitted] ...\n" + text[-4000:]


def _runtime_error_line(stderr_text: str) -> str:
    """The local runtime's own one-line account of a failure (fix 0.1.5,
    triple-check defect 2). The adapter ends its stderr with a structured
    {"error", "message"} JSON line -- quote that message. Failing that,
    use the last non-empty line, which is where any Python traceback
    keeps its actual exception. A whole traceback is internals; the
    caller gets a sentence, never a stack dump."""
    lines = [l.strip() for l in stderr_text.splitlines() if l.strip()]
    for l in reversed(lines):
        try:
            d = json.loads(l)
        except Exception:
            continue
        if isinstance(d, dict) and d.get("message"):
            return _full(str(d["message"]), 2000)
    return _full(lines[-1], 2000) if lines else "no error output"


# ----------------------------------------------------------------------------- gateway

class Gateway:
    def __init__(self, base: str | None = None, api_key: str | None = None, timeout: float = 600.0):
        self.base = (base or gateway_url()).rstrip("/")
        self.api_key = api_key if api_key is not None else load_api_key()
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        h = {"User-Agent": "singularis-mcp/0.1"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None, auth: bool = True) -> dict[str, Any]:
        if auth and not self.api_key:
            raise SingularisError(
                "no_api_key",
                "No Singularis API key is configured. Call singularis_register_key once "
                "(free credits) or set SINGULARIS_API_KEY.",
            )
        url = f"{self.base}{path}"
        try:
            with httpx.Client(timeout=self.timeout) as c:
                r = c.request(method, url, json=body, headers=self._headers())
        except Exception as e:
            # NOT just httpx.HTTPError: httpx.InvalidURL is a plain
            # Exception subclass, and Client CONSTRUCTION raises it when
            # the environment's proxy variables (a NO_PROXY value with
            # IPv6 entries is the known case) fail to parse. Letting it
            # escape is what produced the bare "Error executing tool"
            # with zero diagnostics (door-fix 2026-10-16, defect 2).
            # Surface the real exception type + text to the caller.
            raise SingularisError(
                "gateway_unreachable",
                f"Could not reach the Singularis gateway at {self.base}: "
                f"{type(e).__name__}: {e}. If this mentions a proxy or a "
                "URL, check the HTTP_PROXY / HTTPS_PROXY / NO_PROXY "
                "environment variables.",
            )
        try:
            data = r.json()
        except Exception:
            data = {"detail": r.text}
        code = data.get("code") if isinstance(data, dict) else None
        if r.status_code == 402:
            raise SingularisError(
                "credits_exhausted",
                data.get("detail") or f"Credits exhausted. Top up at {TOPUP_URL} and keep going.",
                credits_remaining=data.get("credits_remaining", 0),
                topup_url=TOPUP_URL,
                http_status=402, gateway_code=code,
            )
        if r.status_code == 401:
            raise SingularisError("bad_api_key", "The Singularis API key was rejected. Register a new key or check SINGULARIS_API_KEY.",
                                  http_status=401, gateway_code=code)
        if r.status_code == 403:
            raise SingularisError("not_available", data.get("detail") or "Not available for this key or country.",
                                  http_status=403, gateway_code=code)
        if r.status_code == 429:
            raise SingularisError("limit_reached", data.get("detail") or "A limit was reached; try again later.",
                                  http_status=429, gateway_code=code)
        if r.status_code >= 400:
            raise SingularisError("gateway_error", f"Gateway returned {r.status_code} ({code}): {data.get('detail', data)}",
                                  http_status=r.status_code, gateway_code=code)
        return data

    # keys / balance / catalog (live Singularis API, /api/v1 -> /v3)
    def register_key(self, country: str, agent_name: str, operator_contact: str = "", kind: str = "agent") -> dict[str, Any]:
        r = self._call("POST", "/agent/claim", {"country": country, "agent_name": agent_name,
                                                  "operator_contact": operator_contact}, auth=False)
        r.setdefault("credits_remaining", r.get("credits"))
        return r

    def balance(self) -> dict[str, Any]:
        u = self._call("GET", "/usage")
        u.setdefault("credits_remaining", u.get("credits"))
        return u

    def recipes(self) -> dict[str, Any]:
        return {"kinds": sorted(set(KIND_MAP.values())), "tools": KIND_MAP,
                "recipes": RECIPE_CATALOG, "services": DISPATCH_SERVICES,
                "note": "Every job goes through the full Singularis chooser on your machine. Bring us your hardest problems."}

    # lease / receipt / fail: the job always runs on this machine through the Singularis runtime
    def lease(self, kind: str, input_sha256: str, max_cpu_seconds: float = 60.0) -> dict[str, Any]:
        return self._call("POST", "/lease", {"kind": kind, "input_sha256": input_sha256, "max_cpu_seconds": max_cpu_seconds})

    def receipt(self, lease: dict[str, Any], sig: str, result: Any, cpu_seconds: str, shell_secret: str) -> dict[str, Any]:
        dg = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        rs = hmac.new(shell_secret.encode(), (lease["id"] + dg + cpu_seconds).encode(), hashlib.sha256).hexdigest()
        return self._call("POST", "/receipt", {"lease": lease, "sig": sig, "result": result, "result_digest": dg,
                                                 "cpu_seconds": cpu_seconds, "receipt_sig": rs})

    def fail(self, lease: dict[str, Any], sig: str, cpu_seconds: str) -> dict[str, Any]:
        return self._call("POST", "/fail", {"lease": lease, "sig": sig, "cpu_seconds": cpu_seconds})

    def share_results(self, **fields: Any) -> dict[str, Any]:
        return self._call("POST", "/agent/results", fields)


# tool kind -> live API job kind ("dispatch" hands the job to the full chooser)
KIND_MAP = {"heat": "heat_eq", "expm": "matexp", "gemm": "dispatch", "fft": "dispatch", "blur": "blur_chain",
            "compress": "compress", "decompress": "dispatch", "recipe": "recipe_lib",
            "fft2": "fft2", "mind_merge": "mind_merge", "mind_merge_v2": "mind_merge_v2",
            "data_carry": "data_carry", "knowledge_packs": "knowledge_packs",
            "free_universe": "free_universe", "compute_in_transit": "compute_in_transit"}

# The full catalog singularis_dispatch can run by name (0.1.7): every named
# job kind of the sealed package, with the payload each one takes. File paths
# are given as strings and read on your machine; arrays are nested lists.
RECIPE_CATALOG = {
    "circulant_solve": {"payload": {"c": "first column of the circulant matrix", "y": "right-hand side"}, "does": "Solve C x = y for a circulant C."},
    "circulant_power": {"payload": {"c": "first column", "k": "power", "x": "vector (optional)"}, "does": "Raise a circulant matrix to a power, optionally applied to a vector."},
    "toeplitz_matvec": {"payload": {"c": "first column", "r": "first row", "x": "vector"}, "does": "Multiply a Toeplitz matrix by a vector."},
    "kron_solve": {"payload": {"A": "left factor", "B": "right factor", "Y": "right-hand side"}, "does": "Solve a Kronecker-structured system."},
    "kron_matvec": {"payload": {"A": "left factor", "B": "right factor", "X": "matrix"}, "does": "Apply a Kronecker product to a matrix."},
    "banded_solve": {"payload": {"n": "size", "diags": "diagonals by offset", "y": "right-hand side"}, "does": "Solve a banded system."},
    "heat_eq": {"payload": {"u": "initial field", "r": "diffusion number", "k": "steps", "bc": "periodic (default)"}, "does": "Diffusion / heat evolution."},
    "matexp": {"payload": {"A": "matrix", "t": "time (default 1)", "x": "vector (optional)"}, "does": "Matrix exponential e^{tA}, or its action on a vector."},
    "blur_chain": {"payload": {"image": "2D image", "sigma": "blur width"}, "does": "Gaussian blur."},
    "fft": {"payload": {"x": "1D signal", "inverse": "true for the inverse transform"}, "does": "Discrete Fourier transform of a signal, any length."},
    "fft2": {"payload": {"x": "2D field", "inverse": "true for the inverse transform"}, "does": "2D discrete Fourier transform, any shape."},
    "compress": {"payload": {"data": "text or byte list"}, "does": "Compress data into a restorable stream."},
    "recipe_lib": {"payload": {"op": "list | get", "name": "recipe name"}, "does": "The built-in recipe library."},
    "mind_merge": {"payload": {"op": "merge | add | remove", "inputs": "mind files", "out": "output file"}, "does": "Merge trained minds by addition -- exact, no retraining."},
    "mind_merge_v2": {"payload": {"op": "merge | add | remove | merge_quarantine | export_shard | import_shard | merge_shards", "inputs": "mind files", "out": "output file"}, "does": "Mind merging with quarantine of poisoned inputs and signed portable shards."},
    "data_carry": {"payload": {"op": "pack | verify | merge"}, "does": "Carry many minds' knowledge in one small signed file."},
    "knowledge_packs": {"payload": {"op": "create | drop | wake | work | return"}, "does": "Send a working knowledge pack to a machine, wake it there, and bring the results home exactly."},
    "free_universe": {"payload": {"work_dir": "working directory"}, "does": "Run a self-contained universe relay and verify its homecoming."},
    "compute_in_transit": {"payload": {"op": "fuse_in_transit | twist_in_transit | energy_audit", "tower_in": "sealed tower file"}, "does": "Compute on a sealed tower while it travels, seals verified."},
    "auto": {"payload": {"op": "apply | solve | power", "operator": "a typed operator spec", "M": "or a dense matrix", "x": "vector"}, "does": "One structured operation through the full chooser."},
}

# The services singularis_dispatch can call with {"service": <name>, ...}:
DISPATCH_SERVICES = ["operator", "alloy", "compress", "solve", "function", "stream", "lens",
                     "provenance", "learn", "predict", "fuse",
                     "chain", "forge", "signal", "kernel", "brain", "flow"]


def load_shell_secret() -> str | None:
    s = os.environ.get("SINGULARIS_SHELL_SECRET")
    if s:
        return s
    try:
        return json.loads(CRED_PATH.read_text()).get("shell_secret")
    except Exception:
        return None


# ----------------------------------------------------------------------------- local runtime

# ----------------------------------------------------------------------------- complex on the wire
# The runtime reads a complex field as two real companions: the field itself
# (real part) and "<field>_im" (imaginary part) -- except the fft jobs, whose
# imaginary companion is named "im". A payload value that carries complex data
# (Python complex values in nested lists, a complex numpy array, or an .npy
# carrier holding one) is split here, at the one choke point every local job
# passes through, so no tool has to know the convention. Real-only payloads
# pass through untouched.

def _complex_array_of(value: Any) -> "np.ndarray | None":
    """Return value as a complex ndarray if it carries complex data, else None."""
    if isinstance(value, np.ndarray):
        return value.astype(complex) if np.iscomplexobj(value) else None
    if isinstance(value, dict) and ("npy_path" in value or "npy_b64" in value):
        try:
            arr = unpack(value)
        except Exception:
            return None
        return arr.astype(complex) if isinstance(arr, np.ndarray) and np.iscomplexobj(arr) else None
    if isinstance(value, complex):
        return np.asarray(value, dtype=complex)
    if isinstance(value, (list, tuple)):
        def _has_complex(v: Any) -> bool:
            if isinstance(v, complex):
                return True
            if isinstance(v, (list, tuple)):
                return any(_has_complex(u) for u in v)
            return False
        if _has_complex(value):
            try:
                return np.asarray(value, dtype=complex)
            except Exception:
                return None
    return None


def _encode_complex_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind == "dispatch" and isinstance(payload.get("payload"), dict):
        # A dispatch job wraps the recipe's own payload one level down; the
        # split belongs to that inner payload, under the recipe's conventions.
        out = dict(payload)
        out["payload"] = _encode_complex_payload(str(payload.get("recipe", "")), payload["payload"])
        return out
    out: dict[str, Any] = {}
    for field, value in payload.items():
        arr = _complex_array_of(value)
        if arr is None:
            out[field] = value
            continue
        companion = "im" if (kind in ("fft", "fft2") and field == "x") else f"{field}_im"
        if companion in payload or companion in out:
            out[field] = value  # caller already split this field by hand; theirs wins
            continue
        out[field] = pack(np.asarray(arr.real, dtype=float))
        out[companion] = pack(np.asarray(arr.imag, dtype=float))
    return out


class LocalRuntime:
    """Connector to the Singularis runtime installed on this machine.

    Protocol (either transport):
      input : {"kind": <job kind>, "payload": {...}}   (arrays as nested lists or {"npy_path": "..."})
      output: {"result": <array or {"npy_path"}> or any JSON, "check": {kind, metric, value, tolerance, passed}}

    SINGULARIS_ENGINE_CMD  -> subprocess, JSON on stdin, JSON on stdout
    SINGULARIS_ENGINE_URL  -> POST JSON to that URL
    Your coding agent plugs the Singularis runtime into this class; nothing else in the shell changes.
    """

    def run(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        job = {"kind": kind, "payload": _encode_complex_payload(kind, payload)}
        url = os.environ.get("SINGULARIS_ENGINE_URL")
        cmd = os.environ.get("SINGULARIS_ENGINE_CMD")
        if url:
            try:
                with httpx.Client(timeout=None) as c:
                    r = c.post(url, json=job)
            except httpx.TimeoutException:
                # grokfix F8: a timeout is its own human sentence, never a
                # raw exception name.
                raise SingularisError("engine_timeout", "The local engine exceeded its time limit; nothing was charged.")
            except Exception as e:
                # Same trap as Gateway._call: httpx.InvalidURL (proxy
                # env) is not an HTTPError and must not escape raw.
                raise SingularisError("engine_error", f"Local runtime request failed: {type(e).__name__}: {e}")
            if r.status_code >= 400:
                raise SingularisError("engine_error", f"Local runtime returned {r.status_code}: {_full(r.text)}")
            out = r.json()
            if isinstance(out, dict) and out.get("error") and "result" not in out:
                # The daemon answers HTTP 200 with the adapter's own
                # {"error","message"} dict on a refusal/failure; surface it
                # as the error it is, never as a successful empty result.
                raise SingularisError(str(out["error"]), str(out.get("message") or out["error"]))
            return out
        if cmd:
            proc = subprocess.run(cmd, shell=True, input=json.dumps(job).encode(), capture_output=True)
            if proc.returncode != 0:
                # grokfix F8 (customer test): exit 124 is a timeout kill
                # (GNU timeout / host limit). It used to surface as
                # "Local runtime failed (exit 124): " with an empty tail --
                # a blank error. It now has its own code and sentence.
                if proc.returncode == 124:
                    raise SingularisError("engine_timeout", "The local engine exceeded its time limit; nothing was charged.")
                err_text = proc.stderr.decode(errors='replace')
                if not err_text.strip():
                    # No stderr at all: fall back to the stdout tail so the
                    # caller never gets an empty message.
                    tail = _full(proc.stdout.decode(errors='replace')).strip()
                    raise SingularisError("engine_error", f"Local runtime failed (exit {proc.returncode}) with no error message."
                                          + (f" Last output: {tail}" if tail else ""))
                # The runtime's own one-line account of the failure
                # (fix 0.1.5): the adapter's structured message, or the
                # exception line at the end of its stderr. Never the
                # whole stderr -- a stack trace is not an error message.
                raise SingularisError("engine_error", f"Local runtime failed (exit {proc.returncode}): {_runtime_error_line(err_text)}")
            try:
                return json.loads(proc.stdout.decode())
            except Exception:
                raise SingularisError("engine_error", "Local runtime returned non-JSON output.")
        raise SingularisError("no_local_runtime", "No local runtime configured (SINGULARIS_ENGINE_CMD / SINGULARIS_ENGINE_URL).")


# ----------------------------------------------------------------------------- arrays in / out

def load_array(value: Any, path: str | None, name: str, allow_complex: bool = False) -> np.ndarray:
    """Accept a nested list OR a local file path (.npy, .npz[first array], .csv, .txt)."""
    if path:
        p = Path(path).expanduser()
        if not p.exists():
            raise SingularisError("file_not_found", f"{name}: file not found: {p}")
        if p.suffix == ".npy":
            return np.load(p)
        if p.suffix == ".npz":
            z = np.load(p)
            return z[z.files[0]]
        if p.suffix in (".csv", ".txt"):
            return np.loadtxt(p, delimiter="," if p.suffix == ".csv" else None)
        raise SingularisError("bad_file", f"{name}: unsupported file type {p.suffix} (use .npy, .npz, .csv or .txt)")
    if value is None:
        raise SingularisError("missing_input", f"{name}: give the data inline (nested list) or a local file path.")
    try:
        return np.asarray(value, dtype=float)
    except Exception as e:
        if allow_complex:
            try:
                return np.asarray(value, dtype=complex)
            except Exception:
                pass
        raise SingularisError("bad_input", f"{name}: could not read as a numeric array: {e}")


def pack(arr: np.ndarray) -> Any:
    """Arrays go to the runtime as nested lists (small), an .npy path (large, local runtime)
    or base64 .npy bytes (large, hosted)."""
    if arr.size <= inline_max():
        return arr.tolist()
    if local_runtime_configured():
        p = result_dir() / f"in_{uuid.uuid4().hex}.npy"
        np.save(p, arr)
        return {"npy_path": str(p), "shape": list(arr.shape)}
    import io
    buf = io.BytesIO()
    np.save(buf, arr)
    return {"npy_b64": base64.b64encode(buf.getvalue()).decode(), "shape": list(arr.shape)}


def unpack(value: Any) -> Any:
    if isinstance(value, dict):
        if "npy_path" in value:
            return np.load(value["npy_path"])
        if "npy_b64" in value:
            import io
            return np.load(io.BytesIO(base64.b64decode(value["npy_b64"])))
    return value


def deliver(value: Any, label: str) -> dict[str, Any]:
    """Return small results inline, large ones as a file path the agent can open."""
    if isinstance(value, dict) and ("npy_path" in value or "npy_b64" in value):
        value = unpack(value)
    if isinstance(value, (list, tuple)):
        try:
            arr = np.asarray(value)
            if arr.dtype.kind in "fcbiu":
                value = arr
        except Exception:
            pass
    if isinstance(value, np.ndarray):
        if value.size <= inline_max():
            return {"result": value.tolist(), "shape": list(value.shape)}
        p = result_dir() / f"{label}_{uuid.uuid4().hex}.npy"
        np.save(p, value)
        return {"result_path": str(p), "shape": list(value.shape), "note": "Result is large; it was saved as a .npy file on this machine."}
    return {"result": value}


# ----------------------------------------------------------------------------- the one call every tool makes

def run_job(kind: str, payload: dict[str, Any], size: dict[str, Any], label: str) -> dict[str, Any]:
    """Lease from the live API, run on this machine through the Singularis runtime, then settle with a signed receipt."""
    gw = Gateway()
    t0 = time.time()
    try:
        if not local_runtime_configured():
            raise SingularisError("no_local_runtime",
                "Singularis runs on your own machine. Install the Singularis runtime from https://getsingularis.com "
                "and set SINGULARIS_ENGINE_CMD (or SINGULARIS_ENGINE_URL). Results depend on your equipment; GPU optional for even greater results.")
        if os.environ.get("SINGULARIS_ENGINE_METERED") == "1":
            # the Singularis runtime leases, locks and settles each job itself; do not lease twice
            out = LocalRuntime().run(kind, payload)
            m = out.pop("metered", {}) or {}
            cost = {"credits_used": m.get("microcredits", 0) / 1e6, "cpu_seconds": m.get("cpu_seconds"),
                    "cloud_equivalent_usd": m.get("cloud_equiv_usd"), "charge_usd": m.get("charge_usd"),
                    "leases": m.get("leases"), "receipts": m.get("receipts")}
            return _envelope(kind, out, cost, t0, label)
        ss = load_shell_secret()
        if not ss:
            raise SingularisError("no_shell_secret", "No shell_secret saved. Call singularis_register_key once, or set SINGULARIS_SHELL_SECRET.")
        api_kind = KIND_MAP.get(kind, "dispatch")
        inp = hashlib.sha256(json.dumps({"kind": kind, "payload": payload, "size": size}, sort_keys=True, default=str).encode()).hexdigest()
        L = gw.lease(api_kind, inp)
        if L.get("reuse"):
            out = {"result": L.get("result"), "check": {"kind": "reuse", "passed": True, "digest": L.get("digest")}}
            cost = {"credits_used": 0, "reuse": True}
        else:
            r0 = resource.getrusage(resource.RUSAGE_CHILDREN)
            try:
                out = LocalRuntime().run(kind, payload)
            except SingularisError:
                r1 = resource.getrusage(resource.RUSAGE_CHILDREN)
                gw.fail(L["lease"], L["sig"], repr((r1.ru_utime + r1.ru_stime) - (r0.ru_utime + r0.ru_stime)))
                raise
            r1 = resource.getrusage(resource.RUSAGE_CHILDREN)
            cpu = repr(max(0.0, (r1.ru_utime + r1.ru_stime) - (r0.ru_utime + r0.ru_stime)))
            # only a digest of the result and its check leave this machine; the numbers stay local
            full = hashlib.sha256(json.dumps(out.get("result"), sort_keys=True, default=str).encode()).hexdigest()
            R = gw.receipt(L["lease"], L["sig"], {"result_sha256": full, "check": out.get("check")}, cpu, ss)
            rc = R.get("receipt") or {}
            cost = {"credits_used": (R.get("microcredits") or 0) / 1e6, "cpu_seconds": R.get("cpu_seconds"), "charge_usd": R.get("charge_usd"),
                    "cloud_equivalent_usd": (rc.get("cloud_equiv_uusd") or 0) / 1e6,
                    "receipts": [{"lease": rc.get("lease"), "signature_ed25519": R.get("signature_ed25519")}]}
        return _envelope(kind, out, cost, t0, label)
    except SingularisError as e:
        return e.envelope()
    except Exception as e:  # never crash the agent
        return {"ok": False, "error": "unexpected", "message": f"{type(e).__name__}: {e}"}


def _envelope(kind: str, out: dict[str, Any], cost: dict[str, Any], t0: float, label: str) -> dict[str, Any]:
    if True:
        elapsed = time.time() - t0
        env = {"ok": True, "job": kind, "where": "local", "elapsed_s": round(elapsed, 4)}
        env.update(deliver(out.get("result"), label))
        for k in ("extra", "ratio", "out_path", "bytes_in", "bytes_out", "note"):
            if k in out:
                env[k] = out[k]
        env["check"] = out.get("check") or {"kind": "none", "passed": None}
        env["cost"] = cost
        env["please_share"] = ("Free tryout. If this helped, please share your results and before-vs-after cost "
                               "with singularis_share_results. Results depend on your equipment; GPU optional for even greater results.")
        return env
