# singularis-mcp 0.1.5 — shipped 2026-10-16 (triple-check fix pass)

Full report: ~/workspace/oscar_ops/AGENT_FIX_015_20261016.md

- Defect 1 (compress false success): the adapter's compress/decompress now run
  the sealed package's own SING 2 lane (singularis.sing2) — a real .sing stream
  is written, trial-restored and hash-verified before success is reported;
  decompress restores through the same lane (bit-exact or it refuses). Client
  additionally refuses ok:true for a file job whose output file does not exist
  (output_missing). Oscar's preference order was fix-first, remove-only-if-
  impossible; the lane existed in the deployed engine, so it was fixed.
- Defect 2 (PQ fragility + tracebacks): root cause measured — stdlib urllib
  reads through the test machine's egress proxy truncated ~13/15 (10 KB) and
  5/15 (2 KB) responses; httpx and curl read 50/50 clean. sing_shell now
  transports over httpx when available (urllib fallback kept), the PQ call
  retries 5x with backoff and pqchan.opn inside the loop, JSON decode errors
  count as transport failures, NO_PROXY is defused before client construction.
  Client surfaces the runtime's structured one-line error, never a traceback.
  Doubled word "Singularis Singularis" removed (client, descriptions,
  server.json).
- Defect 3 (metering): no code change — proven not a reporting lie. Envelope ==
  balance delta == ledger row == settlement (1 mc, exact, lease
  lease_c87b78ffea01462d8664930fae2e8ed0). The triple-check's ~100x gap is the
  per-lease reservation hold (334 mc, TTL 600 s, auto-refunded by the server
  reaper); the ledger records settlements only.
- Defect 4 (README): runtime quickstart added (deps, bundle URL + key,
  ENGINE_CMD/METERED/SEALED), from the bundle's own INSTALL.txt + llms.txt.
- Bundles redeployed on DFW (both tars; sealed payload byte-identical),
  backups /srv/sing/backups/fix015_20261016_1645 + _1710, deploy_attest
  re-issued and verified (18 files).
- PyPI 0.1.5 live (Repository project URL added). GitHub main at 75ded99
  (14 files) + 6240909 (server.json registry-shape correction).
- MCP Registry: com.getsingularis/singularis updated 0.1.3 -> 0.1.5 with the
  repository field, via mcp-publisher HTTP domain proof (no OAuth needed);
  publisher binary + Ed25519 key in ~/workspace/oscar_ops/registry/ and the
  proof record is live at https://getsingularis.com/.well-known/mcp-registry-auth.
  RELEASE CHECKLIST FROM NOW ON: PyPI -> GitHub -> REGISTRY (same run).
- Test accounts created during verification (flagged for cleanup):
  acct_b7ee1cc99f7b (fix015-accept-20261016), acct_c13b5bfa868c
  (fix015-accept2-20261016). Triple-check's acct_e4ade48b2c6c predates this pass.
- Supersession: tests/test_defect2_client.py case 4 asserted the door-fix
  head+tail stderr rule; 0.1.5 replaces it with structured-message extraction
  (tests/test_fix015_client.py, 6/6). The old file is kept as the 0.1.4 record.
