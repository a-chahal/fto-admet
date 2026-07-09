"""The hERG (cardiac ion-channel liability) endpoint package.

Makes the endpoint importable so core can (later) load its ``aggregate.py``. Like every endpoint
package (CLAUDE.md §2, SETTLED §6) it is a thin marker: aggregators select their models by *endpoint
membership* in the registry (``Endpoint.herg in spec.endpoints``), never by folder layout, so the
per-model adapters live in their own subfolders, each in an isolated pixi env.

Models that feed hERG: ``ctoxpred2`` (this task, t23 - the automatable multichannel secondary that
replaces the web-only CardioDPi: 0/1 blocker VOTES + confidences for hERG / NaV1.5 / CaV1.2), and later
``bayesherg`` (t24), ``cardiotox_net``, ``cardiogenai`` (t25, discriminative votes; its generative path
is GATED and scaffold-only), plus the cross-cutting generalists whose registry ``endpoints`` set carries
``Endpoint.herg`` (ADMET-AI's hERG pre-screen head).

The hERG aggregator (t52) is DEFERRED (CLAUDE.md §4a): the "harmonize-then-weight-toward-sensitivity"
philosophy is settled but the thresholds/weights are not. Crucially, the different upstreams do NOT all
contribute the same TYPE of signal - some emit a P(block) probability (ADMET-AI, CardioTox
net, BayeshERG), while ``ctoxpred2`` emits a 0/1 VOTE weighted by its confidence, NOT a probability to
average into the pool (docs IO_SPEC §2). Each adapter here only emits its raw per-model signal; the
policy that reconciles vote-vs-probability lives downstream in t52, not in any adapter.
"""
