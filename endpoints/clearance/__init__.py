"""The clearance endpoint package.

Makes the endpoint importable so core can (later) load its ``aggregate.py`` (t43). The aggregator selects
its models by *endpoint membership* in the registry (``Endpoint.clearance in spec.endpoints``), never by
folder layout (CLAUDE.md §2, SETTLED §6), so this package intentionally stays a thin marker: the per-model
adapters live in their own subfolders, each in an isolated pixi env.

Clearance is deliberately kept DECOMPOSED (renal / hepatic / aggregate), never a single number: the four
clearance predictions across the pipeline are in different units and matrices and must NEVER be combined
numerically (F-3, CLAUDE.md §4). Models feeding clearance: ``pksmart`` (aggregate CL + fold-error,
ranking-only, t11), plus the cross-cutting ``admet_ai`` (Clearance_Hepatocyte_AZ / Clearance_Microsome_AZ),
``opera`` (Clint), and the DruMAP / Watanabe renal web SOPs, which carry ``Endpoint.clearance`` in their
registry ``endpoints`` set. The renal-vs-hepatic fork is resolved by experiment, not by these models.
"""
