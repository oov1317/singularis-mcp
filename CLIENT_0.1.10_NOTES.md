# singularis-mcp 0.1.10 — complex inputs travel in the client's own language

One fix, three small parts, all client-side. The engine has always accepted
complex jobs written as two real companions (the field and its "<field>_im");
0.1.9's client simply had no way to say that: a complex value packed for the
wire crashed the JSON handoff, and the FFT tools turned complex input away.

- client.py: the local-runtime handoff now splits any complex payload value
  (nested lists of Python complex numbers, a complex numpy array, or an .npy
  carrier holding one) into the real field plus its "_im" companion, at the
  single choke point every local job passes through. For the fft jobs the
  imaginary companion is named "im", matching the engine's fft convention.
  A field the caller already split by hand is left untouched, and real-only
  payloads pass through byte-identical — nothing about existing jobs changes.
- server.py: singularis_fft / singularis_fft2 accept a complex signal
  directly (inline or as an .npy file) and split it into x + im themselves.
  Giving the imaginary part both inside x and as the im argument is refused
  with a plain sentence.
- descriptions.py: the dispatch examples named two recipes that do not exist
  ('ridge', 'kron_apply'); they now name real ones ('circulant_solve',
  'kron_solve', 'kron_matvec').

Verified: encoder unit cases 6/6; live against the current engine build —
complex fft and fft2 from .npy files exact against numpy, a complex solve
through dispatch exact, and the real-valued jobs (fft, gemm, solve)
unchanged.
