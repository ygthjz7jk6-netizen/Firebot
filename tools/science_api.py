import urllib.request
import urllib.parse
import json
import xml.etree.ElementTree as ET

def search_pubmed(query: str, max_results: int = 5) -> str:
    """
    Vyhledá vědecké články v databázi PubMed (NCBI E-utilities) a vrátí jejich abstrakty.
    Používá veřejné a bezplatné API, ideální pro bio-materiály a medicínu.
    """
    try:
        # Krok 1: E-Search - Získání ID článků (PMIDs) odpovídajících dotazu
        encoded_query = urllib.parse.quote(query)
        search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={encoded_query}&retmax={max_results}&retmode=json"
        
        search_req = urllib.request.Request(search_url, headers={'User-Agent': 'Firebot/1.0'})
        with urllib.request.urlopen(search_req) as response:
            search_data = json.loads(response.read().decode('utf-8'))
            
        pmids = search_data.get('esearchresult', {}).get('idlist', [])
        
        if not pmids:
            return f"❌ V databázi PubMed nebyly pro dotaz '{query}' nalezeny žádné výsledky."

        # Krok 2: E-Fetch - Získání detailů (abstrakty a metadata) pro nalezená PMIDs
        pmids_str = ",".join(pmids)
        fetch_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmids_str}&retmode=xml"
        
        fetch_req = urllib.request.Request(fetch_url, headers={'User-Agent': 'Firebot/1.0'})
        with urllib.request.urlopen(fetch_req) as response:
            xml_data = response.read()
            
        # Parsování XML odpovědi
        root = ET.fromstring(xml_data)
        results = []
        
        for article in root.findall('.//PubmedArticle'):
            # Extrakce metadat
            pmid = article.findtext('.//PMID')
            title = article.findtext('.//ArticleTitle')
            
            # Abstrakt může být rozdělen do více částí (<AbstractText>)
            abstract_texts = article.findall('.//AbstractText')
            # Ošetření, aby se spojovaly jen existující stringy (kvůli linteru)
            abstract_chunks = [t.text for t in abstract_texts if isinstance(t.text, str)]
            abstract = " ".join(abstract_chunks)
            
            # Autoři
            authors = []
            for author in article.findall('.//Author'):
                last_name = author.findtext('LastName')
                initials = author.findtext('Initials')
                if last_name and initials:
                    authors.append(f"{last_name} {initials}")
            author_str = ", ".join(authors) if authors else "Neznámý autor"
            
            # Rok publikace
            pub_year = article.findtext('.//PubDate/Year')
            if not pub_year:
                pub_year = article.findtext('.//ArticleDate/Year')
            year_str = pub_year if pub_year else "Neznámý rok"

            # Formátování výsledku
            entry = f"**{title}** ({year_str})\n"
            entry += f"Autoři: {author_str} | PMID: {pmid}\n"
            entry += f"Abstrakt: {abstract if abstract else 'Abstrakt není k dispozici.'}\n"
            entry += f"Odkaz: https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            
            results.append(entry)
            
        final_output = f"🔬 **Nalezené vědecké studie z PubMed pro '{query}':**\n\n" + "\n\n---\n\n".join(results)
        return final_output

    except Exception as e:
        return f"❌ Došlo k chybě při komunikaci s PubMed API: {e}"

if __name__ == "__main__":
    # Testovací spuštění
    print(search_pubmed("chitosan hydrogel wound healing", 2))
