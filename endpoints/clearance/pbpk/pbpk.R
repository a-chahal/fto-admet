# pbpk.R - COMMENTED SCAFFOLD, not a turnkey run.
#
# PBPK (Open Systems Pharmacology / PK-Sim) is an OUT-OF-BAND INTEGRATOR, driven with the `ospsuite` R
# package (R 4.x + .NET 8 + OSP Suite binaries; see README.md for the install recipe). It is NOT a
# SMILES->number predictor: it consumes OTHER endpoints' outputs (clearance, fraction unbound,
# permeability, logP, pKa) as compound parameters, simulates a whole-body concentration-time profile, and
# the modeler extracts exposure metrics (Cmax, AUC, tmax, ...) that are then transcribed to the ledger via
# `run.py`. This file shows the SHAPE of that ospsuite call and the parameterization from upstream outputs.
# It is a starting point for the modeler on the box, deliberately not runnable end to end here (there is no
# committed .pkml model and the OSP runtime is out-of-band).
#
# Flow:  upstream endpoint JSON  ->  set PK-Sim compound parameters  ->  simulate  ->  extract metrics
#        ->  write a metrics JSON  ->  `python run.py --input metrics.json --output record.json` (ledger).

suppressMessages(library(ospsuite))   # load/parameterize/simulate PKML models; evaluate Cmax/AUC
# library(jsonlite)                    # to read the upstream-endpoints JSON and write the metrics JSON

# ---------------------------------------------------------------------------------------------------------
# 0. Inputs: the OTHER endpoints' outputs that parameterize this compound.
#    In practice these come from the pipeline's collected OutputRecords (OPERA LogP / Caco2 / FuB / Clint,
#    OCHEM PPB fu, PKSmart CL, admet_ai clearance heads, a single pKa source - F-13, DEFERRED). Here they
#    are shown as a plain list; on the box, read them from the collected records (e.g. jsonlite::fromJSON).
#    NOTE (F-16, DEFERRED): the FTO di-cation standardization is NOT decided here - feed the single canonical
#    `core` input; PK-Sim does its own internal handling. Flag divergences, do not pick a protonation state.
upstream <- list(
  logP            = 3.42,     # OPERA LogP (log Kow)          -> PK-Sim "Lipophilicity"
  fraction_unbound = 0.12,    # OCHEM PPB fu = 1 - %bound/100 -> PK-Sim "Fraction unbound (plasma)"
  caco2_logPapp   = -4.6,     # OPERA Caco2 (logPapp)         -> PK-Sim "Specific intestinal permeability"
  hepatic_clint   = 15.4,     # OPERA Clint (uL/min/10^6)     -> PK-Sim hepatic CLint metabolic process
  pKa             = 8.1,      # single pKa source (F-13 placeholder: OPERA pKa_pred) -> PK-Sim "pKa"
  mol_weight      = 349.4,    # g/mol
  solubility      = 0.05      # mg/mL (reference solubility at reference pH)
)

# ---------------------------------------------------------------------------------------------------------
# 1. Load a PK-Sim model built in the GUI and exported to PKML (the modeler builds this once; not committed).
sim <- loadSimulation("fto43_pbpk.pkml")

# ---------------------------------------------------------------------------------------------------------
# 2. Parameterize the compound from the upstream outputs. Parameter PATHS are illustrative - resolve the
#    exact paths in the loaded model with `getAllParameterPathsIn(sim)` on the box (they depend on how the
#    compound was named in PK-Sim). setParameterValues writes them into the simulation.
#    UNIT DISCIPLINE (F-3, CLAUDE.md §4): clearance numbers are NEVER combined across models. PK-Sim consumes
#    ONE clearance descriptor for THIS compound in its OWN units; do not pool OPERA Clint (uL/min/10^6 cells)
#    with PKSmart CL (mL/min/kg) or admet_ai CL - pick the one that matches the PK-Sim process and convert
#    explicitly with ospsuite unit tools (toBaseUnit / toUnit).
param_map <- list(
  "Applications|Compound|Lipophilicity"                 = upstream$logP,
  "Applications|Compound|Fraction unbound (plasma)"     = upstream$fraction_unbound,
  "Applications|Compound|Specific intestinal permeability" = upstream$caco2_logPapp,
  "Applications|Compound|Molecular weight"              = upstream$mol_weight,
  "Applications|Compound|Solubility at reference pH"    = upstream$solubility
  # hepatic CLint / pKa are set as metabolic-process + ionization parameters (paths depend on the model)
)
for (path in names(param_map)) {
  p <- getParameter(path, sim, stopIfNotFound = FALSE)
  if (!is.null(p)) setParameterValues(p, param_map[[path]])
}

# ---------------------------------------------------------------------------------------------------------
# 3. Simulate the concentration-time profile.
result  <- runSimulation(sim)
# Pick the plasma (systemic) output path; the CNS indication also motivates a brain/tissue path (Kp,uu).
plasma  <- getOutputValues(result, quantitiesOrPaths = "Organism|PeripheralVenousBlood|Plasma|Concentration")
times   <- plasma$data[["Time"]]
conc    <- plasma$data[["Organism|PeripheralVenousBlood|Plasma|Concentration"]]

# ---------------------------------------------------------------------------------------------------------
# 4. Extract exposure metrics from C(t). There is NO fixed PBPK output schema (IO_SPEC §1 #12): the modeler
#    chooses which metrics matter. Typical set for this program (CNS FTO inhibitor):
Cmax      <- max(conc)
tmax      <- times[which.max(conc)]
AUC_0_t   <- sum(diff(times) * (head(conc, -1) + tail(conc, -1)) / 2)   # trapezoidal AUC over the sim window
# t_half, AUC_0_inf, Vss, MRT, Kp_uu_brain (brain-to-plasma unbound ratio, key for a CNS target) as needed.

# ---------------------------------------------------------------------------------------------------------
# 5. Write the metrics JSON that `run.py` transcribes to the ledger. Keep the units EXPLICIT (they are not
#    fixed) and record the parameterization provenance so the ledger record is reconstructible (CLAUDE.md §4a).
metrics <- list(
  mol_id  = "FTO-43",
  metrics = list(
    Cmax    = list(value = Cmax,    unit = "uM"),
    tmax    = list(value = tmax,    unit = "h"),
    AUC_0_t = list(value = AUC_0_t, unit = "uM*h")
  ),
  parameterization = list(
    lipophilicity_logP      = list(source_model = "opera",     field = "LogP",  value = upstream$logP),
    fraction_unbound        = list(source_model = "ochem_ppb", field = "fu",    value = upstream$fraction_unbound),
    intestinal_permeability = list(source_model = "opera",     field = "Caco2", value = upstream$caco2_logPapp),
    hepatic_clint           = list(source_model = "opera",     field = "Clint", value = upstream$hepatic_clint)
  ),
  simulation = list(model_file = "fto43_pbpk.pkml", species = "human", ospsuite_version = "REPLACE_ME")
)
# jsonlite::write_json(metrics, "metrics.json", auto_unbox = TRUE, pretty = TRUE)
# then, out of R:  python run.py --input metrics.json --output record.json
