# swissadme - SwissADME lipophilicity consensus (reconstructed in code)

SwissADME (`swissadme.ch`) is a **web-only** tool with **no API**. Its lipophilicity role is
**reconstructible in code**, so this adapter rebuilds the consensus locally and the pipeline never hits
the website in the bulk loop (CLAUDE.md landmine + task t27). The web tool is used only if the exact
5-way consensus is ever needed on the final shortlist.

## What SwissADME reports, and what we reproduce

SwissADME's lipophilicity block (Daina, Michielin, Zoete, *Sci. Rep.* 2017, 7:42717) is five logP
lenses plus their mean (`Consensus Log Po/w`). All are log units, **up = more lipophilic**.

| Lens          | Reproducible in code? | How we do it                                                   |
| ------------- | --------------------- | -------------------------------------------------------------- |
| **WLOGP**     | yes                   | RDKit Crippen `MolLogP` (the exact same lens as t10 `rdkit_crippen`) |
| **MLOGP**     | yes                   | Moriguchi 1992/1994 13-descriptor regression (implemented here) |
| **XLOGP3**    | yes, *if the binary is present* | external XLOGP3 CLI v3.2.2 (a licensed download)      |
| iLOGP         | **no**                | SwissADME-internal GB/SA solvation - proprietary, omitted       |
| Silicos-IT    | **no**                | defunct FILTER-IT - omitted                                     |

`Consensus_logP` = **mean of the reproduced lenses**. (OPERA `LogD` may be added later as an optional
4th input; not wired here.)

## XLOGP3: 3-lens vs 2-lens (this build is 2-lens)

XLOGP3 v3.2.2 is an external CLI that requires a licensed download from the Yang lab; it is **not
installed on the box** at build time. Per task t27 and the no-fabricate rule (CLAUDE.md §5), we do
**not** invent an XLOGP3 value:

- If an XLOGP3 executable is found (via the `XLOGP3_BIN` env var, else `xlogp3` on `PATH`), the adapter
  runs it and produces a **3-lens** consensus (WLOGP + MLOGP + XLOGP3).
- If it is absent (the current state on the box), the adapter degrades cleanly to a **2-lens**
  consensus (WLOGP + MLOGP) and records the reduction in `raw.lenses_used`, `raw.xlogp3_available`, and
  `uncertainty.extra.n_lenses`.

**This build ships and smoke-tests as 2-lens** (no XLOGP3 binary on the box). The XLOGP3 code path is
present and inert; the exact CLI invocation is finalized against the licensed binary when it lands
(a small, contained follow-up), and no value is fabricated in the meantime.

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array or `.smi` in -> a JSON
array out. A 2-lens record:

```json
{
  "model": "swissadme",
  "endpoint_values": { "WLOGP": 0.09, "MLOGP": -0.36, "Consensus_logP": -0.13 },
  "uncertainty": {
    "extra": {
      "lens_values": { "WLOGP": 0.09, "MLOGP": -0.36 },
      "spread_range": 0.45, "spread_std": 0.32, "n_lenses": 2,
      "xlogp3_available": false,
      "note": "INDIRECT: spread across reproduced logP lenses; calibrated confidence is DEFERRED (AD policy)."
    }
  },
  "raw": { "smiles": "...", "lenses": { "WLOGP": 0.09, "MLOGP": -0.36 }, "lenses_used": ["WLOGP","MLOGP"], "xlogp3_available": false, "consensus_logP": -0.13, "spread_range": 0.45, "spread_std": 0.32 },
  "provenance": { "model": "swissadme", "method": "...", "lenses_reproduced": ["WLOGP","MLOGP"], "rdkit_version": "...", "citation": "...", "license": "..." }
}
```

When XLOGP3 is available `endpoint_values` also carries `"XLOGP3"` and `Consensus_logP` is the 3-lens
mean.

- **Units:** all lenses and the consensus are log10 (dimensionless). **Direction: UP = more lipophilic.**
- **Invalid/empty SMILES** -> a valid record with `endpoint_values` null and the reason in `raw.error`.
  The adapter does not crash, so one bad molecule never sinks a bulk batch.

## Uncertainty = lens spread (INDIRECT)

The uncertainty signal is the **spread across the reproduced lenses**: convergence between the lenses =
a trustworthy logP; scatter = lean on measured logD instead. The raw spread (`spread_range`,
`spread_std`, the per-lens `lens_values`, and `n_lenses`) is recorded in `uncertainty.extra`. Turning
that spread into a **calibrated confidence** is the operational AD / calibration policy, which is
**DEFERRED** (CLAUDE.md §4a), so the first-class `Uncertainty` fields (`confidence`, `ad_index`, ...)
are intentionally left null rather than filled with a guessed threshold.

## logP is NOT logD (flag F-12)

These are **logP** lenses, not logD. For the di-basic FTO series the logP->logD conversion needs a pKa
and is done **downstream** with the single shared pKa source (F-13); it is never silently applied here
(CLAUDE.md §4a). Compare logD-to-logD downstream, not logP-to-logD.

## MLOGP faithfulness (read before trusting the raw MLOGP)

MLOGP is Moriguchi's 13-descriptor topological regression (Chem. Pharm. Bull. 1992, 40:127; 1994,
42:976):

```
logP = -1.014 + 1.244*CX^0.6 - 1.017*NO^0.9 + 0.406*PRX - 0.145*UB^0.8 + 0.511*HB
       + 0.268*POL - 2.215*AMP + 0.912*ALK - 0.392*RNG - 3.684*QN + 0.474*NO2
       + 1.582*NCS + 0.773*BLM
```

The descriptors (CX weighted C+halogen; NO count of N+O; PRX N/O proximity with amide/sulfonamide
correction; UB unsaturated bonds; POL aromatic polar substituents; AMP amphoteric; ALK hydrocarbon
dummy; RNG non-benzene ring dummy; QN quaternary/oxide N; NO2/NCS/BLM group counts) follow that paper.
Two are **documented approximations**:

- **HB** (intramolecular H-bond dummy) was hand-assigned per compound in the original model; it is not
  generally computable, so it is **held at 0**. Rarely nonzero for drug-like inputs.
- **POL** is counted as ring-attached heteroatom substituents; a substituent bonded to the ring through
  a carbon (e.g. an aromatic `-COOH`) is not counted.

SwissADME's own MLOGP implementation is not open, so bit-exact parity is not claimed. This is exactly
why the consensus averages several lenses and surfaces the spread as uncertainty: MLOGP is one lens,
cross-checked against WLOGP (and XLOGP3 when present), never trusted alone.

## Uniform CLI

```
python run.py --input <path> --output <path> [--gpu N]
```

`--gpu` is accepted and **ignored** (`requires_gpu=False`); the reconstruction is pure CPU RDKit.

## Provenance

- **Upstream / method:** SwissADME lipophilicity consensus reconstructed in code. WLOGP = RDKit Crippen
  `MolLogP`; MLOGP = Moriguchi 1992/1994 formula; XLOGP3 = external CLI v3.2.2 (optional). RDKit version
  recorded per run in `provenance.rdkit_version` (read live) and pinned by `pixi.lock`.
- **Citations:** Daina A, Michielin O, Zoete V. "SwissADME." *Sci. Rep.* 2017, 7:42717
  (10.1038/srep42717). Wildman SA, Crippen GM. *J Chem Inf Comput Sci* 1999, 39(5):868 (WLOGP).
  Moriguchi I, et al. *Chem. Pharm. Bull.* 1992, 40(1):127 and 1994, 42(4):976 (MLOGP).
- **Access tag:** WEB-SUBSTITUTABLE (web tool has no API; lipophilicity role reconstructed in code).
- **License:** code BSD-3-Clause (RDKit); methods are published formulae.
- **Quirks:** logP != logD (F-12); MLOGP HB/POL approximations (above); XLOGP3 optional -> 2-lens vs
  3-lens; iLOGP + Silicos-IT proprietary/defunct and omitted; `MolFromSmiles` returns `None` on
  unparseable input (handled as a per-record error, not a raise).

## Environment / lock

`pixi.toml` is intent (conda-forge: `python 3.11.*`, `rdkit`). `pixi.lock` is **solved on the box**
(Linux + conda-forge) and committed; it carries a real `linux-64` section with package hashes. macOS
cannot resolve the per-model env, so `platforms = ["linux-64"]`.

## Smoke

```
pixi run --manifest-path pixi.toml python run.py \
  --input ../../../tests/fixtures/fto43.smi --output /tmp/swissadme.out.json
```

yields the reproduced lenses (WLOGP + MLOGP; + XLOGP3 if a binary is present), a `Consensus_logP`, and
a spread-based `uncertainty` for the FTO-43 fixture. `tests/test_model_swissadme.py`
(`@pytest.mark.model`) drives this on the box and validates the output against `core.schemas`.
