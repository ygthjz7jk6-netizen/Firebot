"""
Virtual Lab pro Vědeckého specialistu
Zajišťuje cheminformatické výpočty nad molekulárními strukturami (SMILES).
Využívá knihovnu RDKit.
"""

import json

try:
    from rdkit import Chem
    from rdkit.Chem import Descriptors
    import rdkit.rdBase as rdBase
    # Ztišení interních chybových hlášek RDKit (např. když je SMILES neplatný)
    rdBase.DisableLog('rdApp.error')
except ImportError:
    Chem = None


def test_molecule(smiles: str) -> str:
    """
    Přijme chemickou strukturu ve formátu SMILES.
    Zavolá 'virtuální laboratoř' (RDKit) a vypočítá fyzikálně-chemické vlastnosti
    důležité pro biomateriály a farmakologii (Lipinského pravidla atd.).
    
    Vrací čitelnou textovou zprávu pro LLM.
    """
    if Chem is None:
        return "❌ Chyba Virtuální Laboratoře: Knihovna `rdkit` není nainstalována. Prosím o `pip install rdkit`."

    # Krok 1: Přečti strukturu ze SMILES
    mol = Chem.MolFromSmiles(smiles)
    
    if mol is None:
        return f"❌ Chyba Virtuální Laboratoře: Neschopnost sestavit molekulu ze SMILES '{smiles}'. Struktura je chemicky neplatná."

    # Krok 2: Spočti klíčové parametry (Descriptors)
    try:
        mw = Descriptors.MolWt(mol)
        logp = Descriptors.MolLogP(mol)
        hbd = Descriptors.NumHDonors(mol)
        hba = Descriptors.NumHAcceptors(mol)
        tpsa = Descriptors.TPSA(mol)
        
        # Roathable bonds mohou implikovat flexibilitu biomateriálu
        rot_bonds = Descriptors.NumRotatableBonds(mol)
        
        # Krok 3: Sestav laboratorní protokol
        report = []
        report.append(f"🧪 **Laboratorní Protokol pro '{smiles}'**")
        report.append(f"- **Molekulární hmotnost (MW):** {mw:.2f} g/mol")
        report.append(f"- **Lipofilita (LogP):** {logp:.2f} (nižší = hydrofilnější/rozpustnější ve vodě, vyšší = lipofilnější)")
        report.append(f"- **H-donory / H-akceptory:** {hbd} / {hba} (ovlivňuje vazbu na proteiny a rozpustnost)")
        report.append(f"- **Polární plocha povrchu (TPSA):** {tpsa:.2f} Å² (ovlivňuje buněčnou prostupnost)")
        report.append(f"- **Počet rotovatelných vazeb:** {rot_bonds} (ukazatel flexibility struktury)")
        
        # 4: Zhodnocení na základě Lipinského pravidla pěti (pouze základ)
        violations = 0
        if mw > 500: violations += 1
        if logp > 5: violations += 1
        if hbd > 5: violations += 1
        if hba > 10: violations += 1
        
        if violations == 0:
            report.append("\n✅ **Závěr laboratoře:** Sloučenina vyhovuje Lipinského pravidlům (pravděpodobně dobrá farmakokinetika/biokompatibilita).")
        else:
            report.append(f"\n⚠️ **Slabé místo:** Zjištěno {violations} porušení Lipinského pravidel. Zvaž iteraci struktury (např. snížení velikosti nebo počtu skupin).")
            
        return "\n".join(report)

    except Exception as e:
        return f"❌ Nespecifikovaná chyba během laboratorních výpočtů: {str(e)}"

if __name__ == "__main__":
    # Test - Aspirin
    print(test_molecule("CC(=O)OC1=CC=CC=C1C(=O)O"))
