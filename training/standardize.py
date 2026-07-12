"""Molecule standardization - IDENTICAL to the exclusion-index builder so InChIKeys line up for subtraction.

LargestFragmentChooser (strip salts) -> Uncharger (neutralize) -> canonical tautomer -> InChIKey (full +
first-14). A SMILES RDKit cannot process yields ``None`` (logged by the caller), never a silent drop.
"""

from __future__ import annotations

from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors
from rdkit.Chem.MolStandardize import rdMolStandardize

RDLogger.DisableLog("rdApp.*")

_LFC = rdMolStandardize.LargestFragmentChooser()
_UNCHARGER = rdMolStandardize.Uncharger()
_TAUT = rdMolStandardize.TautomerEnumerator()


def standardize(smiles: str) -> tuple[str, str, str, float] | None:
    """``smiles -> (canonical_smiles, inchikey, inchikey14, mol_weight)`` or ``None`` if unparseable."""
    mol = Chem.MolFromSmiles(smiles or "")
    if mol is None:
        return None
    try:
        mol = _LFC.choose(mol)
        mol = _UNCHARGER.uncharge(mol)
        mol = _TAUT.Canonicalize(mol)
    except Exception:
        return None
    ik = Chem.MolToInchiKey(mol)
    if not ik:
        return None
    return Chem.MolToSmiles(mol), ik, ik[:14], float(Descriptors.MolWt(mol))
