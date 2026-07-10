# smartcyp - SMARTCyp 2.4.2 site-of-metabolism (legacy Java jar, owner-directed JVM override), metabolism endpoint

**STATUS: built** (adapter complete + verified locally against a real jar run). The box-solved
`pixi.lock` and the on-box `@pytest.mark.model` smoke are the one remaining step: the compute box
(`rosenbluth`) was unreachable during this build (SSH/ICMP time out), and per CLAUDE.md 0.1 a lock is
solved ON THE BOX and never laptop-synthesized, so the lock is deferred to the box. Finishing is
mechanical: `rsync` this folder (with the fetched jar) to `/zfs`, `pixi install` to solve `pixi.lock`
(linux-64 + hashes), run the propranolol/FTO-43 smoke, and copy the box-solved lock back. Everything the
lock depends on (the exact deps) is fixed in `pixi.toml`; the adapter itself is already verified because
the engine is a platform-independent Java jar (identical CSV on any OS) and RDKit behaves the same.

This adapter wraps the **legacy SMARTCyp 2.4.2 Java engine** (`vendor/smartcyp-2.4.2.jar`),
run via `java -jar` as a subprocess. Using the JVM here is an **explicit, authorized owner directive** that
overrides the standing "the metabolism endpoint is JVM-free / only legacy SMARTCyp is Java" landmine in
`CLAUDE.md` 4. The override was taken because the authentic SMARTCyp **3.0** (Python/RDKit) source is
unobtainable (see "Why 2.4.2 and not 3.0" below); the owner chose the working legacy jar over a permanent
BLOCK. This is honestly **SMARTCyp 2.4.2 (the CDK/Java line), NOT the 3.0 Python rewrite** - the SoM
*method* is the same (DFT fragment reactivity energies + SMARTS rules, Rydberg 2010), only the packaging
differs, and `run.py` stamps the engine version onto every record so provenance is never misrepresented.

## Role: per-atom site-of-metabolism ranking (where the CYP soft spot is)

SMARTCyp is a first-principles SoM predictor: DFT-derived fragment activation energies + SMARTS reactivity
rules rank the atom a CYP is most likely to attack. It reports a general (3A4) model plus 2D6 and 2C9
isoform corrections. **Direction is inverted: lower `Score` / `Ranking == 1` => the most likely site of
metabolism** (`Score` is a kJ/mol-scale energy). It complements the generalist "is it metabolically stable"
signals by answering *where* the soft spot is. It is co-ranked ORDINALLY with FAME3R at the metabolism
aggregator, never by averaging SMARTCyp's kJ/mol `Score` with FAME3R's 0-1 probability (F-2, CLAUDE.md 4);
that harmonization is `endpoints/metabolism/aggregate.py`, not this adapter.

## Fetch the engine (a gitignored binary, reproducible in one step)

The 18 MB `smartcyp-2.4.2.jar` is a vendored upstream **binary** and, like every model's weights, is
**gitignored, never committed** (CLAUDE.md 0.5; same convention as
`endpoints/herg/bayesherg/.gitignore`). Fetch it once into `vendor/`:

```sh
git clone --depth 1 https://github.com/MD-Studio/MDStudio_SMARTCyp.git /tmp/MDStudio_SMARTCyp
cp /tmp/MDStudio_SMARTCyp/mdstudio_smartcyp/bin/smartcyp-2.4.2.jar \
   endpoints/metabolism/smartcyp/vendor/smartcyp-2.4.2.jar
```

`run.py` resolves the jar at `vendor/smartcyp-2.4.2.jar` (override with the `SMARTCYP_JAR` env var).

## Adapter design

Uniform model CLI (`python run.py --input <path> --output <path> [--gpu N]`; `--gpu` accepted and ignored,
SMARTCyp is CPU-only), run in this model's isolated pixi env (`rdkit` + `openjdk`), emitting plain JSON
matching `core.schemas.OutputRecord`. Per molecule:

1. RDKit parses the SMILES and writes an atom-**ordered** SDF into a private temp dir.
2. `java -jar vendor/smartcyp-2.4.2.jar -printall ligand.sdf` runs there and writes one results CSV.
3. The CSV is parsed **by header name** (see the verified header below) and each row is mapped to an
   `OutputRecord`.

**Atom-index alignment (the load-bearing correctness point).** The aggregator co-ranks SMARTCyp vs FAME3R
on `raw.atoms[].atom_index`, so both must use the **RDKit atom index**. SMARTCyp numbers heavy atoms
`1..N` in molecule-file order; feeding an RDKit-ordered SDF pins that numbering to the RDKit index, so
`atom_index = (SMARTCyp Atom number) - 1`. Verified on a real run: the element prefix of every SMARTCyp
`Atom` label (`C.1`, `N.4`, `O.7`, ...) matches the RDKit atom symbol at that index; `run.py` re-checks
this per atom and records an `element_mismatch` note rather than silently mis-aligning.

Output mapping:

- **`raw.atoms`**: the per-atom table (the load-bearing SoM output). Each row: `atom_index` (RDKit index),
  `element`, `atom_label` (raw `C.2`, audit), the general-3A4 `Score` (float, lower = SoM) and `Ranking`
  (int; `1` = top; the jar's literal `null` for non-ranked atoms -> `None`), plus the isoform/geometry
  columns the jar emits (`2D6ranking`/`2D6score`, `2Cranking`/`2Cscore` = **2C9**, `Energy`,
  `Relative Span`, `Span2End`, `N+Dist`, `COODist`, `2DSASA`). The per-atom table stays in `raw`, never
  crammed into scalar `endpoint_values` (a SoM table is inherently per-atom).
- **`endpoint_values`**: the top-site SUMMARY only - `top_som_atom_index`, `top_som_score`,
  `top_som_atom_label`, `n_atoms` (direction baked into the doc: lower Score / Ranking==1 = SoM).
- **`uncertainty`**: `null`. SMARTCyp emits no native per-atom uncertainty, so the reserved envelope stays
  empty (the AD/agreement signal is computed indirectly at the aggregator).
- **`raw.csv`**: the verbatim CSV text (raw-output cache, CLAUDE.md 4a - the result is reconstructible if
  the engine output ever changes).
- Invalid/unparseable SMILES => a valid record with null values and the reason in `raw.error` (never
  crashes a bulk batch).

### Verified CSV header (from a real 2.4.2 `-printall` run, NOT hardcoded from the legacy template)

Running the vendored jar on propranolol (`CC(C)NCC(O)COc1cccc2ccccc12`) prints this header, which the
parser maps from by name:

```
Molecule,Atom,Ranking,Score,Energy,Relative Span,2D6ranking,2D6score,Span2End,N+Dist,2Cranking,2Cscore,COODist,2DSASA
```

Smoke result for propranolol: top site = atom index **1** (`C.2`), `Score` **33.42** (`Ranking == 1`), 19
atoms scored. (This 2.4.2 header happens to coincide with the legacy-Java template quoted in
`docs/FTO_ADMET_Model_IO_SPEC.md` 1 #8, but it was re-verified against a live jar run rather than trusted
from the doc.) `Ranking`/`Score` for atoms the engine deems non-sites are `null` / a ~991-999 sentinel;
the parser keeps `Score` as the sentinel float (so ascending-Score ordering pushes non-sites to the
bottom) and maps `Ranking == "null"` to `None`.

### FTO-43 note (N-oxidation penalty)

The empirical N-oxidation correction is left **ON** (engine default, no `-noempcorr`): it folds a +penalty
into the `Score` of tertiary-amine N (e.g. FTO-43's pyrrolidine N), so SMARTCyp down-ranks N-oxidation
there. That is the model's designed behaviour; the aggregator REFLECTS this ordinal ranking as emitted and
does not "correct" the penalty (CLAUDE.md 4).

## Environment (rdkit + openjdk)

`pixi.toml` declares `python` + `rdkit` (builds each molecule, writes the atom-ordered SDF) + `openjdk>=11`
(the JRE that runs the jar). Adding `openjdk` is the **authorized owner-directed override** of the
JVM-free-metabolism landmine, noted in a comment there. `platforms = ["linux-64"]`; the `pixi.lock` is
solved **on the box** and committed (CLAUDE.md 0.1). The env carries no CUDA/GPU deps (CPU-only).

## Why 2.4.2 and not 3.0 (history)

The authentic SMARTCyp **3.0** (Python/RDKit) engine could not be obtained: `smartcyp.sund.ku.dk` (the only
authoritative distributor) returned HTTP 503 on all paths, there is no PyPI package named `smartcyp`, and
the only public GitHub hits are the legacy Java line (`cdk/smartcyp`), the `MD-Studio/MDStudio_SMARTCyp`
Java-jar wrapper used here, and third-party re-implementations whose reactivity energies are hand-invented
(rejected under the no-fabricate rule). Rather than leave the SoM signal permanently BLOCKED, the owner
directed use of the legacy 2.4.2 jar (which ships inside `MD-Studio/MDStudio_SMARTCyp` and embeds the same
authoritative SMARTCyp DFT reactivity library). If an authentic 3.0 Python/RDKit source later becomes
available, the swap is: vendor it under `vendor/`, drop `openjdk` from `pixi.toml`, re-verify the 3.0
header, and point `run.py` at the Python engine - the `raw.atoms` schema the aggregator consumes stays the
same.

## Provenance

- **Upstream engine:** SMARTCyp 2.4.2 (CDK/Java), bundled as `mdstudio_smartcyp/bin/smartcyp-2.4.2.jar`
  inside `MD-Studio/MDStudio_SMARTCyp`. The engine itself is the University of Copenhagen SMARTCyp program
  (`www.farma.ku.dk/smartcyp`, `smartcyp.sund.ku.dk`).
- **Method / citation:** Rydberg P, Gloriam DE, Sharma J, Kaur P, Olsen L. "SMARTCyp: A 2D Method for
  Prediction of Cytochrome P450-Mediated Drug Metabolism." *ACS Med. Chem. Lett.* 1(3):96-100 (2010).
  doi:10.1021/ml100016x. (3.0 server: Olsen L, Montefiori M, Tran KP, Jorgensen FS. *Bioinformatics*
  35(17):3174-3175 (2019), doi:10.1093/bioinformatics/btz037 - the method reference for the 3.0 line the
  program descends from, not the engine wrapped here.)
- **Access tag:** CODE-PKG (per the authoritative registry table). Concretely this is a vendored Java jar
  run via subprocess (NOT the 3.0 Python package); the jar is a gitignored binary fetched per the step above.
- **License:** the SMARTCyp engine is the UCPH SMARTCyp program, free for academic/research use (cite
  Rydberg 2010); confirm terms for any commercial use. The `MD-Studio/MDStudio_SMARTCyp` project the jar is
  distributed in is Apache-2.0.
- **Quirks:** lower `Score` / `Ranking == 1` => most likely SoM (direction INVERTED vs FAME3R); the
  +N-oxidation penalty on tertiary-amine N is folded into `Score` (down-ranks N-oxidation on FTO-43's
  pyrrolidine N); co-rank with FAME3R ordinally, never average `Score` with FAME3R probability (F-2); the
  jar processes ONE molecule per SDF, so the adapter runs it once per molecule in an isolated temp dir; the
  CSV header was re-verified against a live jar run and the parser maps by column name.
