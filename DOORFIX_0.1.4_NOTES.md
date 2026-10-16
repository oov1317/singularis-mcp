# singularis-mcp 0.1.4 — prepared, NOT shipped

Release gate (unchanged): PyPI upload needs Oscar's "alex" token via the
Secure Vault at upload time; the MCP Registry publish needs the GitHub
OAuth device flow under Oscar's identity. Do not ship GitHub alone
(version skew). This tree = repo HEAD f8d6b4f + the two change sets below.

## Change set A — tool titles + annotations (prepared earlier)
`singularis_mcp/server.py` carries titles and MCP annotations
(readOnlyHint / destructiveHint / openWorldHint) for all 12 tools
(source: launch/mcp_annotations/server_patched.py).

## Change set B — door-fix 2026-10-16 (defect 2 + client half of defect 3)
Root cause: `httpx.InvalidURL` is a plain `Exception`, NOT an
`httpx.HTTPError` subclass. When the host's proxy environment fails to
parse (a `NO_PROXY` value containing IPv6 entries such as `[::1]` is the
known case), `httpx.Client()` construction raises it; `Gateway._call`
caught only `HTTPError`, so the exception escaped the tool and the MCP
host showed a bare "Error executing tool" with zero diagnostics.

- `client.py` `Gateway._call`: catches ALL exceptions from client
  construction/request and raises `SingularisError("gateway_unreachable")`
  carrying the exception type + text + a proxy-env hint. HTTP error
  envelopes now also carry `http_status` and the server's `gateway_code`.
- `client.py` `LocalRuntime.run`: URL mode wraps construction/request the
  same way; subprocess mode reports the runtime's stderr head AND tail
  (the tail holds the real exception line) with any omission stated —
  no more silent `[:500]` truncation (`_full()` helper).
- `server.py`: `singularis_register_key`, `singularis_balance`,
  `singularis_recipes`, `singularis_share_results` gained a catch-all
  that returns a structured `{ok: false, error: "unexpected", message:
  "<Type>: <text>"}` envelope. No tool can surface a bare framework
  error again. (`run_job` already catch-alled.)
- Version bumped 0.1.3 -> 0.1.4 (pyproject.toml, server.json).

## Tests
`tests/test_defect2_client.py <package_parent_dir> <label>` —
orig package: 1/4 (InvalidURL escapes raw; no status/code; stderr tail
lost). This tree: 4/4 (proxy-env envelope, 403 code+detail, success
path unchanged, stderr tail preserved). Run 2026-10-16, logs in
~/workspace/oscar_ops/doorfix_20261016/logs/defect2_summary.txt.
