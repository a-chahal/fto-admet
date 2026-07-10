"""The hERG (cardiac ion-channel liability) endpoint package.

Makes the endpoint importable so core can (later) load its ``aggregate.py``. Like every endpoint
package (CLAUDE.md §2, SETTLED §6) it is a thin marker: aggregators select their models by *endpoint
membership* in the registry (``Endpoint.herg in spec.endpoints``), never by folder layout, so the
per-model adapters live in their own subfolders, each in an isolated pixi env.

Models that feed hERG: ``bayesherg`` (t24), ``cardiotox_net``, ``cardiogenai`` (t25, discriminative
pIC50s for hERG / NaV1.5 / CaV1.2; its generative path is GATED and scaffold-only), plus the
cross-cutting generalists whose registry ``endpoints`` set carries ``Endpoint.herg`` (ADMET-AI's hERG
pre-screen head).

The hERG aggregator (t52) is DEFERRED (CLAUDE.md §4a): the "harmonize-then-weight-toward-sensitivity"
philosophy is settled but the thresholds/weights are not. Crucially, the different upstreams do NOT all
contribute the same TYPE of signal - some emit a P(block) probability directly (ADMET-AI, CardioTox
net, BayeshERG), while ``cardiogenai`` emits a raw pIC50 that must be mapped onto P(block) before it can
join the pool (docs IO_SPEC §2). Each adapter here only emits its raw per-model signal; the policy that
reconciles the different signal types lives downstream in t52, not in any adapter.
"""
