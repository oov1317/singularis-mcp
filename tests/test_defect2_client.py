"""Defect-2 tests: register_key must surface the REAL error, never a bare
'Error executing tool'. Run against a package root (orig or release):

  python test_defect2_client.py <package_parent_dir> <label>

Cases:
  1. Proxy-env trap (this shell's real NO_PROXY makes httpx.Client()
     construction raise httpx.InvalidURL -- a plain Exception, NOT an
     HTTPError): the tool must return a structured envelope naming it.
  2. Forced HTTP 403 with server {code, detail}: both must surface.
  3. Success path unchanged (fake 201 claim -> ok True, key saved).
  4. Local-runtime stderr keeps its TAIL (the real exception line).
"""
import io, json, os, sys, tempfile
sys.path.insert(0, sys.argv[1])
label = sys.argv[2]

os.environ.pop("SINGULARIS_API_KEY", None)
os.environ["SINGULARIS_HOME"] = tempfile.mkdtemp(prefix="sing_home_")

import httpx
from singularis_mcp import client as C
from singularis_mcp import server as S

results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

# ---- 1. the proxy-env trap, live in this very process env ----
try:
    out = S.singularis_register_key("US", "defect2-probe")
    msg = out.get("message", "") if isinstance(out, dict) else ""
    check("register_key returns envelope, never raises",
          isinstance(out, dict) and out.get("ok") is False and "InvalidURL" in msg, msg[:150])
except Exception as e:
    check("register_key returns envelope, never raises", False, f"ESCAPED: {type(e).__name__}: {e}")

# ---- 2. forced HTTP error: status + server code + detail all surface ----
class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status; self._p = payload; self.text = json.dumps(payload)
    def json(self): return self._p
class FakeClient:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def request(self, method, url, json=None, headers=None):
        return FakeResp(403, {"code": "us_only", "detail": "Singularis agent access is US-only right now."})
real_client_cls = httpx.Client
httpx.Client = FakeClient
try:
    try:
        C.Gateway(api_key="k")._call("POST", "/agent/claim", {"x": 1}, auth=False)
        check("HTTP 403 surfaces code+detail", False, "no exception raised")
    except C.SingularisError as e:
        env = e.envelope()
        check("HTTP 403 surfaces code+detail",
              e.code == "not_available" and "US-only" in e.message
              and env.get("gateway_code") == "us_only" and env.get("http_status") == 403,
              json.dumps(env)[:170])
finally:
    httpx.Client = real_client_cls

# ---- 3. success path unchanged ----
class OkClient(FakeClient):
    def request(self, method, url, json=None, headers=None):
        return FakeResp(201, {"api_key": "sk_test_123", "shell_secret": "ss", "credits": 500,
                              "kind": "agent", "account": "acct_test", "please_share": ""})
httpx.Client = OkClient
try:
    out = S.singularis_register_key("US", "defect2-ok")
    check("register success unchanged", out.get("ok") is True and out.get("credits") == 500, json.dumps(out)[:130])
finally:
    httpx.Client = real_client_cls

# ---- 4. local runtime stderr: tail (real error) survives ----
os.environ["SINGULARIS_ENGINE_CMD"] = (
    "python3 -c \"import sys; sys.stderr.write('x'*9000 + '\\nValueError: THE_REAL_CAUSE'); sys.exit(3)\"")
os.environ.pop("SINGULARIS_ENGINE_URL", None)
try:
    C.LocalRuntime().run("heat", {})
    check("runtime stderr tail preserved", False, "no exception")
except C.SingularisError as e:
    check("runtime stderr tail preserved",
          "THE_REAL_CAUSE" in e.message and "omitted" in e.message and "exit 3" in e.message,
          f"len={len(e.message)}")
finally:
    os.environ.pop("SINGULARIS_ENGINE_CMD", None)

bad = [n for n, ok in results if not ok]
print(f"== {label}: {len(results) - len(bad)}/{len(results)} passed" + (f" FAILING: {bad}" if bad else ""))
sys.exit(1 if bad else 0)
