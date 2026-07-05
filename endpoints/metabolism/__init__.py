"""The metabolism endpoint package.

Makes the endpoint importable so core can (later) load its ``aggregate.py`` (t42). The aggregator selects
its models by *endpoint membership* in the registry (``Endpoint.metabolism in spec.endpoints``), never by
folder layout (CLAUDE.md §2, SETTLED §6), so this package intentionally stays a thin marker: the per-model
adapters live in their own subfolders, each in an isolated pixi env.

The metabolism endpoint answers *where the soft spot is* (per-atom site-of-metabolism ranking), complementing
the generalist "is it metabolically stable" signals. Two models feed it:

- ``smartcyp`` (SMARTCyp 3.0, this folder): first-principles per-atom SoM ranking (3A4 general model + 2D6/2C9
  isoform corrections). **Lower Score / Ranking = 1 => most likely SoM.** Python 3 + RDKit, JVM-free.
- ``fame3r`` (FAME3R): a Python random-forest per-atom SoM probability (replaces the legacy Java FAME 3).

The two are co-ranked ORDINALLY, never by averaging SMARTCyp's kJ/mol-scale ``Score`` with FAME3R's 0-1
probability (F-2, CLAUDE.md §4); that harmonization is the metabolism aggregator's job (t42), not the adapters'.
The whole metabolism endpoint is deliberately JVM-free: SMARTCyp 3.0 is Python/RDKit (only legacy 1.x/2.x were
Java/CDK) and FAME3R replaces the Java FAME 3.
"""
