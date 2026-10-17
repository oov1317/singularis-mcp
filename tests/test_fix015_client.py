"""Fix 0.1.5 client tests (triple-check defects 1 + 2, client half):

  1. A failing local runtime yields the adapter's structured one-line
     message -- never a traceback dump (supersedes door-fix test 4's
     head+tail rule for the structured case; the fallback case is 2).
  2. A runtime whose stderr is garbage + an exception line surfaces the
     exception line only.
  3. The no-runtime message has no doubled word.
  4. _finish_file_job: ok:true with a missing output file becomes an
     output_missing error; ok:true with a real file passes and hashes it.
  5. _envelope passes the adapter's "note" through.

Run: python test_fix015_client.py <package_parent_dir> <label>
"""
import hashlib, json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
label = sys.argv[2]

os.environ["SINGULARIS_HOME"] = tempfile.mkdtemp(prefix="sing_home_")
from singularis_mcp import client as C
from singularis_mcp import server as S

results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

def run_with_engine_cmd(cmd):
    os.environ["SINGULARIS_ENGINE_CMD"] = cmd
    os.environ.pop("SINGULARIS_ENGINE_URL", None)
    try:
        C.LocalRuntime().run("heat", {})
        return None
    except C.SingularisError as e:
        return e
    finally:
        os.environ.pop("SINGULARIS_ENGINE_CMD", None)

# ---- 1. structured adapter error line wins; no traceback text ----
_td = tempfile.mkdtemp(prefix="fake_rt_")
fake1 = Path(_td) / "fake1.py"
fake1.write_text(
    "import sys, json\n"
    "sys.stderr.write('Traceback (most recent call last):\\n')\n"
    "sys.stderr.write('  File \"sing_shell.py\", line 89, in call\\n' + 'x' * 4000 + '\\n')\n"
    "sys.stderr.write('RuntimeError: boom internals\\n')\n"
    "sys.stderr.write(json.dumps({'error': 'adapter_error', 'message': 'RuntimeError: Singularis transport: /v3/pq failed after 5 attempts'}) + '\\n')\n"
    "sys.exit(2)\n")
e = run_with_engine_cmd(f"python3 {fake1}")
check("structured stderr -> adapter message only",
      e is not None and "failed after 5 attempts" in e.message and "Traceback" not in e.message
      and "sing_shell.py" not in e.message and "exit 2" in e.message,
      (e.message[:160] if e else "no error"))

# ---- 2. un-structured stderr: last line (the exception) only ----
fake2 = Path(_td) / "fake2.py"
fake2.write_text(
    "import sys\n"
    "sys.stderr.write('x' * 9000 + '\\nValueError: THE_REAL_CAUSE')\n"
    "sys.exit(3)\n")
e = run_with_engine_cmd(f"python3 {fake2}")
check("garbage stderr -> exception line only",
      e is not None and "THE_REAL_CAUSE" in e.message and "xxx" not in e.message and "exit 3" in e.message,
      (e.message[:160] if e else "no error"))

# ---- 3. doubled word gone from the no-runtime message ----
os.environ.pop("SINGULARIS_ENGINE_CMD", None)
os.environ.pop("SINGULARIS_ENGINE_URL", None)
env = C.run_job("heat_eq", {}, None, "heat")
check("no-runtime message clean",
      env.get("error") == "no_local_runtime" and "Singularis Singularis" not in env.get("message", ""),
      env.get("message", "")[:120])

# ---- 4. phantom-path guard ----
with tempfile.TemporaryDirectory() as td:
    missing = str(Path(td) / "never_written.sing")
    env = S._finish_file_job({"ok": True, "out_path": missing}, missing)
    check("phantom path -> output_missing error",
          env.get("ok") is False and env.get("error") == "output_missing", json.dumps(env)[:150])
    real = Path(td) / "real.bin"; real.write_bytes(b"abc")
    env = S._finish_file_job({"ok": True, "out_path": str(real)}, str(real))
    check("real file -> ok + sha256",
          env.get("ok") is True and env.get("sha256_out") == hashlib.sha256(b"abc").hexdigest(),
          json.dumps(env)[:150])

# ---- 5. note passthrough in _envelope ----
env = C._envelope("compress", {"result": {"v": 1}, "note": "plain words from the runtime",
                               "metered": {"microcredits": 3, "cpu_seconds": 0.5, "receipts": []}},
                  None, 0.0, "compress")
check("envelope carries note", env.get("note") == "plain words from the runtime", json.dumps(env)[:170])

bad = [n for n, ok in results if not ok]
print(f"== {label}: {len(results) - len(bad)}/{len(results)} passed" + (f" FAILING: {bad}" if bad else ""))
sys.exit(1 if bad else 0)
