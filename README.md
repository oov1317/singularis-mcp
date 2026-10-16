mcp-name: com.getsingularis/singularis

# Singularis

Singularis is unlimited computation. Bring us your hardest problems.

Jobs run on your own machine through the Singularis runtime and the full
Singularis chooser; only a lease, a result digest and CPU-seconds reach the API.
Every answer carries a check you can verify. Patent pending.

**Live now (October 15, 2026):** the API is publicly open and verified end to end — claim, lease, on-device compute, signed receipt. Free agent trial: 500 credits for the first 1,000 agents (US), in exchange for posted metrics and a short prior-cloud vs Singularis cost review. Results depend on your equipment. You have the option of using a GPU for even greater results.

**Claim a free agent key (instant, 500 credits):** https://getsingularis.com/docs  
OpenAPI: https://getsingularis.com/openapi.json

## What it does

Every kind of computation runs through the full Singularis chooser, which picks
the best path for your problem automatically. Example tools:

- `singularis_solve_heat` — diffusion / heat-equation solves on any grid
- `singularis_matrix_exponential` — e^{tA} and matrix-exponential actions
- `singularis_gemm` — dense and operator linear algebra
- `singularis_fft` — fast transforms
- `singularis_blur` — heat-kernel blur
- `singularis_compress` / `singularis_decompress` — exact, restorable compression
- `singularis_recipes` — see what the chooser can run
- `singularis_balance` / `singularis_share_results` — credits and results sharing
- `singularis_dispatch` — hand it any problem and let the chooser decide

## Measured results

Our own measurements, the same figures published on getsingularis.com. GPU
figures compare the same Singularis program run on an NVIDIA RTX 4090 against a
1-thread CPU; a speedup only counts when the results match a reference answer.

- AI training with the GPU boost, up to 16.5x (vs 1-thread CPU, one RTX 4090 test)
- Dense math with the GPU boost, up to 18.3x (vs 1-thread CPU, one RTX 4090 test)
- FFT with the GPU boost, up to 3.2x (vs 1-thread CPU, one RTX 4090 test)
- Smaller files: 1.28x smaller than xz -9e and 1.49x smaller than zstd -19, on 21 test files, with every file restored exactly

Results depend on your equipment. GPU optional for even greater results.

More efficient computation for you and the environment.

## Free tryout

Claim a free agent key instantly: 500 credits, US, first 1,000 agents, no card,
no per-job limit, nothing required at claim. After you use your credits, we respectfully ask you to share your results and
your before-vs-after cost (`singularis_share_results`). Thank you.

Pricing packs $49 / $399 / $2,999 at https://getsingularis.com/credits

## Install

Claude Code:
```
claude mcp add singularis -e SINGULARIS_COUNTRY=US -- singularis-mcp
```

Any MCP host:
```
{ "mcpServers": { "singularis": { "command": "uvx", "args": ["singularis-mcp"],
  "env": { "SINGULARIS_COUNTRY": "US", "SINGULARIS_ENGINE_CMD": "<your Singularis runtime command>" } } } }
```

First call: `singularis_register_key(country="US", agent_name="<your agent>")` -> 500 free credits, saved.

Singularis runs on your own computer and talks to the Singularis API at
https://getsingularis.com/api/v1. Get the Singularis runtime for your machine
from https://getsingularis.com and point SINGULARIS_ENGINE_CMD at it; the client
never ships engine code. Env: SINGULARIS_API_KEY, SINGULARIS_COUNTRY.

Type 1 Civilization Laboratories LLC - https://getsingularis.com

Patent pending. Singularis is a trademark of Type 1 Civilization Laboratories LLC.
