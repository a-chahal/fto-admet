# smartcyp - SMARTCyp 3.0 site-of-metabolism (Python/RDKit, no JVM), metabolism endpoint

**STATUS: BLOCKED** (t25). The authentic SMARTCyp 3.0 (Python/RDKit) source could not be obtained on the
box after honest attempts (see "Why this is BLOCKED" below). No lockfile was solved and no smoke was run:
per the no-fabricate rule (CLAUDE.md §5) a green check obtained by vendoring the legacy Java line or a
third-party re-implementation would be worse than a clean BLOCKED. This README records the exact state, the
intended design (so finishing is a small step once the source is available), and the precise block reason.

## Role: per-atom site-of-metabolism ranking (where the CYP soft spot is)

SMARTCyp 3.0 is a first-principles SoM predictor: DFT-derived fragment activation energies + SMARTS
reactivity rules rank the atom a CYP is most likely to attack. It reports a general (3A4) model plus 2D6 and
2C9 isoform corrections. **Direction is inverted: lower `Score` / `Ranking` = 1 => the most likely site of
metabolism.** It complements the generalist "is it metabolically stable" signals by answering *where* the
soft spot is. Co-ranked ORDINALLY with FAME3R, never by averaging SMARTCyp's kJ/mol-scale `Score` with
FAME3R's 0-1 probability (F-2, CLAUDE.md §4); that harmonization is the metabolism aggregator (t42), not
this adapter.

SMARTCyp 3.0 is Python 3 + RDKit and needs **no `openjdk`** (only legacy SMARTCyp 1.x/2.x were Java + CDK).
The whole metabolism endpoint is JVM-free (FAME 3's Java is replaced by the Python FAME3R).

## Intended adapter design (to finish once the source is vendored)

The adapter is the uniform model CLI (`python run.py --input <path> --output <path> [--gpu N]`, `--gpu`
accepted and ignored: SMARTCyp is CPU-only) running in this model's isolated RDKit-only pixi env, emitting
plain JSON matching `core.schemas.OutputRecord`. The intended mapping:

- **`raw`**: the full per-atom ranking table (atom index/symbol + `Ranking`/`Score` for the 3A4 general model
  and per-isoform `2D6ranking`/`2D6score`, `2C9`/`2Cranking`/`2Cscore`, plus energy/span/SASA columns as the
  3.0 output actually reports them). The per-atom table goes into `raw`, NOT forced into scalar
  `endpoint_values` (a SoM table is inherently per-atom).
- **`endpoint_values`**: at most the ranked top-site summary (e.g. the atom index + `Score` of `Ranking==1`
  per model/isoform) as convenience scalars with the direction baked into the key/doc (lower = SoM). The
  authoritative per-atom detail stays in `raw`.
- **`uncertainty`**: INDIRECT only (agreement with generalist stability, computed at t42). SMARTCyp emits no
  native per-atom uncertainty, so the reserved envelope stays empty here.
- Invalid/unparseable SMILES => a valid record with null values and the reason in `raw.error` (never crash a
  bulk batch).

### HEADER LANDMINE (must re-verify against a real 3.0 run - do NOT hardcode)

The column header quoted in `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #8 -
`Molecule,Atom,Ranking,Score,Energy,Relative Span,2D6ranking,2D6score,Span2End,N+Dist,2Cranking,2Cscore,COODist,2DSASA`
- was read from `WriteResultsAsCSV.java` in the **legacy CDK/Java** `cdk/smartcyp` line (v2.5). It is a
**template only**. The SMARTCyp 3.0 (Python/RDKit) rewrite reports the same core quantities but its exact
header casing / extra columns must be **re-verified against a real 3.0 run** and mapped from *that*. The
adapter must not hardcode the legacy header. This re-verification is exactly what the missing source blocks.

### FTO-43 note (N-oxidation penalty)

The pyrrolidine tertiary amine N of FTO-43 receives the +N-oxidation penalty (folded into `Score`, not a
separate column), so SMARTCyp down-ranks N-oxidation there; interpret accordingly.

## Environment intent (RDKit only, NO openjdk)

`pixi.toml` is present as INTENT only: a plain RDKit + Python env, `platforms = ["linux-64"]`, **no
`openjdk`** (if you find yourself adding a JVM you are reading the legacy repo - stop). SMARTCyp 3.0 has **no
official PyPI package**, so the upstream 3.0 Python source is *vendored* under `vendor/` and imported
directly; the env itself is just RDKit. **No `pixi.lock` is committed**: there is no upstream source to smoke
against yet, so solving an rdkit-only lock would be a partial artifact that cannot satisfy the model DONE
criteria (box-solved lock + passing smoke). The lock is solved on the box only after the 3.0 source is
vendored (CLAUDE.md §0).

## Why this is BLOCKED (exact error / evidence, 2026-07-04)

Three honest attempts to obtain the authentic SMARTCyp 3.0 Python/RDKit source, all dead ends:

1. **MDStudio_SMARTCyp wrapper** (`github.com/MD-Studio/MDStudio_SMARTCyp`, the doc's option (b)): the
   task requires confirming at build time whether this wrapper is pure-Python. It is **NOT**: its tree
   contains `mdstudio_smartcyp/bin/smartcyp-2.4.2.jar` and `smartcyp_run.py` shells out to that **Java 2.4.2
   jar**. That is the **legacy CDK/Java line**, which the SMARTCyp landmine (CLAUDE.md §4; task) explicitly
   forbids ("If you find yourself adding a JVM, you're reading the legacy repo - stop"). Rejected.
2. **KU 3.0 Python source** (`smartcyp.sund.ku.dk`, the doc's option (a) and the only authoritative
   distributor): the host resolves (192.38.114.128) and accepts TCP, but every path returns **HTTP 503
   Service Unavailable** - confirmed from the box AND from an independent network (WebFetch), across `/`,
   `/about`, `/download`, `/static/...`. The legacy host `smartcyp2.sund.ku.dk` is fully unreachable (curl
   000). The Wayback Machine has no archived source/download artifact for the 3.0 site. So the source is
   currently unobtainable, and there is no evidence the 3.0 server ever distributed a downloadable source
   (it is a Flask web/REST service).
3. **PyPI / public GitHub for an authentic 3.0 source**: no PyPI package named `smartcyp` exists (empty
   JSON + empty simple index). GitHub has only: `cdk/smartcyp` (legacy **Java** line, forbidden),
   `MD-Studio/MDStudio_SMARTCyp` (the Java-jar wrapper above), and third-party **re-implementations**
   (`atvijay/smartcyp-application` "SMARTCyp Pro v3.1", `Maxwell1111/Met-ID_SmartCyp_App`
   "SMARTCyp-inspired") whose reactivity energies are **hand-invented in Python** (e.g. a literal
   `("Benzylic_C", 40.0)` table) plus a GNN, NOT the authoritative SMARTCyp DFT reactivity library. Vendoring
   one of those would fabricate the underlying science (no-fabricate rule, CLAUDE.md §5). Rejected.

Blocking error, one line: **SMARTCyp 3.0 Python source unobtainable - `smartcyp.sund.ku.dk` returns HTTP 503
on all paths (server down), no PyPI package, no authoritative public source repo; the only alternatives are
the forbidden legacy Java line (MDStudio_SMARTCyp `smartcyp-2.4.2.jar`, `cdk/smartcyp`) or third-party
re-implementations with fabricated reactivity energies.**

### To finish (when the KU server is back / source is provided)

1. Vendor the SMARTCyp 3.0 Python/RDKit source from `smartcyp.sund.ku.dk` into `vendor/` (code only; never
   commit any bundled weights/data per CLAUDE.md §0).
2. Fill `pixi.toml` deps as the 3.0 source requires (RDKit + its exact pins, read from the source - **no
   `openjdk`**), then `pixi install` **on the box** and commit the box-solved `pixi.lock` (linux-64 section
   with real hashes).
3. Run the 3.0 program once on the FTO-43 fixture, **capture the real 3.0 output header**, document it here
   (noting any diff from the legacy template), and map the adapter from *that* header.
4. Write `run.py` (uniform CLI; per-atom table into `raw`; ordinal SoM summary in `endpoint_values`) and
   `tests/test_model_smartcyp.py` (`@pytest.mark.model`, drives the adapter in its env and validates against
   `core.schemas`), then confirm the smoke passes on the box.

## Provenance

- **Upstream:** SMARTCyp 3.0 (Python 3 + RDKit; Flask web server), `smartcyp.sund.ku.dk` /
  `www.farma.ku.dk/smartcyp`. Only legacy SMARTCyp 1.x/2.x were Java + CDK (`cdk/smartcyp`); do **not** use
  the legacy line for 3.0.
- **Citations:** Olsen L, Montefiori M, Tran KP, Jorgensen FS. "SMARTCyp 3.0: enhanced cytochrome P450
  site-of-metabolism prediction server." *Bioinformatics* 35(17):3174-3175 (2019).
  doi:10.1093/bioinformatics/btz037. Original (1.0): Rydberg P, Gloriam DE, Olsen L. *Bioinformatics*
  26(23):2988 (2010).
- **Access tag:** CODE-PKG (Python/RDKit). *Not* Java (both settled docs' legacy Java tag was corrected in
  `docs/FTO_ADMET_Model_Provenance_VERIFIED.md` §9).
- **License:** upstream SMARTCyp; record the exact license from the 3.0 source when vendored.
- **Quirks:** lower `Score`/`Ranking`=1 => most likely SoM (direction inverted); the +N-oxidation penalty on
  tertiary alkylamine N is folded into `Score` (down-ranks N-oxidation on FTO-43's pyrrolidine N); co-rank
  with FAME3R ordinally, never average `Score` with FAME3R probability (F-2); the legacy-Java CSV header is a
  template only - re-verify against a real 3.0 run.
