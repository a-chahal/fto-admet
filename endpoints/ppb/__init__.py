"""ppb endpoint package - plasma-protein-binding aggregator (no model of its own).

This endpoint has NO ``ModelName`` mapped to it: its ``aggregate.py`` (core env, no box) harmonizes
fields already emitted by other models (OCHEM PPB, ADMET-AI, OPERA) onto one common quantity,
fraction bound (0-1). See ``aggregate.py`` for the contract.
"""
