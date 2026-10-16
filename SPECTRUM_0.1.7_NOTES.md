# singularis-mcp 0.1.7 — the full spectrum, through every door (2026-10-16)

What was wrong, in plain words: the sealed engine a customer downloads was
complete, but several of its doors were never wired. An FFT larger than
4096 points, a 2D FFT, a matrix exponential of a large or non-symmetric
matrix, a large non-periodic heat solve, and a color blur all came back
"not available" even though the engine itself handles them; and
singularis_dispatch could not reach most of what the engine runs, failing
inside the sealed shell with its reason swallowed.

0.1.7, with the rebuilt sealed bundle it pairs with:

- FFT of any size, 1D and 2D (new singularis_fft2 tool), through the
  engine's own spectral machinery — the same transform its circulant and
  lattice operators are built on — checked against a reference transform
  on every call.
- Matrix exponential at any size: with a vector, a Krylov action lane;
  symmetric, the engine's spectral lane; non-symmetric full matrices are
  computed in full and residual-checked. No refusal, no size cap.
- Heat: non-periodic 2D at any size, in operator form (the step operator
  factored, never formed densely), checked against a step-by-step
  reference.
- Blur: one call for grayscale and color images of any size; the channel
  loop is inside the job.
- singularis_dispatch reaches everything: all named job kinds, all
  dispatch services, and typed-operator specs. Refusals now arrive in
  plain words with the real reason (never a bare failure, never a
  swallowed message). singularis_recipes returns the full catalog with
  the payload each job takes.
- New named tools: singularis_mind_merge_v2, singularis_data_carry,
  singularis_knowledge_packs, singularis_free_universe,
  singularis_compute_in_transit.
- ENGINE_URL (daemon) mode: an adapter refusal returned with HTTP 200 is
  now surfaced as the error it is instead of a successful empty result.
- The router's seat is unchanged: the engine's chooser still decides how
  each job runs; 0.1.7 only opens every door to it.

Guarantee unchanged: if it doesn't work, you don't pay — a refused or
failed job settles as a failure and charges nothing.
