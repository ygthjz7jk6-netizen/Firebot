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
        report.append(f"- **Molekulární hmotnost (MW):** {mw:.2f} g/mol (Ukazatel mechanické odolnosti polymeru)")
        report.append(f"- **Hydrofobita (LogP):** {logp:.2f} (Klíčové pro voděodolnost outdoorového oblečení: LogP > 3 = silně hydrofobní/voděodpudivé, LogP < 0 = hydrofilní/saje vodu)")
        report.append(f"- **Polární plocha povrchu (TPSA):** {tpsa:.2f} Å² (Nižší TPSA znamená lepší bariérové vlastnosti proti vodě)")
        report.append(f"- **Počet rotovatelných vazeb:** {rot_bonds} (Více = ohebnější textilní vlákno, méně = tužší materiál)")
        
        # 4: Zhodnocení vlastností pro outdoorové vybavení
        strengths = []
        weaknesses = []
        
        if logp > 2.5:
            strengths.append("Dobrý potenciál pro DWR (Durable Water Repellent) úpravu nebo voděodolné membrány.")
        elif logp < 0:
            weaknesses.append("Materiál bude náchylný k nasákavosti vodou (hydrofilní) - nevhodné jako vnější outdoorová vrstva, leda pro odvod potu (base layer).")
            
        if tpsa > 80:
            weaknesses.append("Příliš vysoká polarita může narušit bariérové vlastnosti proti vlhkosti.")
            
        if mw < 100:
            weaknesses.append("Příliš malá molekula (monomer), pro reálné mechanické vlastnosti bude nutná polymerizace.")
            
        if strengths:
            report.append(f"\n✅ **Silné stránky materiálu:** {' '.join(strengths)}")
        if weaknesses:
            report.append(f"\n⚠️ **Slabá místa materiálu:** {' '.join(weaknesses)}")
            
        return "\n".join(report)

    except Exception as e:
        return f"❌ Nespecifikovaná chyba během laboratorních výpočtů: {str(e)}"

if __name__ == "__main__":
    # Test - Aspirin
    print(test_molecule("CC(=O)OC1=CC=CC=C1C(=O)O"))
