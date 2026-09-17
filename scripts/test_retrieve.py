"""
Script de teste: faz queries no ChromaDB e mostra os resultados.

Uso:
    cd ~/Documentos/Projetos/BMG/BMGQAAgent
    python scripts/test_retrieve.py

Pré-requisito: rodar ingest_kb.py antes.
"""

import chromadb
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
CHROMA_DB_PATH = PROJECT_ROOT / "chroma_db"

# Queries de teste — simulam o que o agente perguntaria
TEST_QUERIES = [
    "Quais GMUDs tiveram rollback no módulo PIX?",
    "Problemas de timeout com integração de sistemas legados",
    "Rollbacks causados por mudança de configuração",
    "Migração de banco de dados Oracle com DDL",
    "Quais sistemas se integram com o Core Banking?",
    "Mudanças no modelo de anti-fraude e impacto em falsos positivos",
    "Problemas de performance com Redis e serialização",
]


def test_retrieve():
    """Executa queries de teste e mostra resultados."""
    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))

    try:
        collection = client.get_collection("bmg-kb")
    except ValueError:
        print("❌ Collection 'bmg-kb' não encontrada. Rode ingest_kb.py primeiro.")
        return

    print(f"🗄️  Collection: bmg-kb ({collection.count()} docs)")
    print("=" * 80)

    for query in TEST_QUERIES:
        print(f"\n🔍 Query: \"{query}\"")
        print("-" * 60)

        results = collection.query(
            query_texts=[query],
            n_results=3,
            include=["documents", "metadatas", "distances"],
        )

        for i, (doc_id, metadata, distance) in enumerate(zip(
            results["ids"][0],
            results["metadatas"][0],
            results["distances"][0],
        )):
            # ChromaDB retorna distância (menor = mais similar)
            similarity = 1 - distance  # converte pra similaridade aproximada
            tipo = metadata.get("tipo", "?")
            sistemas = metadata.get("sistemas", "N/A")

            print(f"\n   [{i+1}] {doc_id} (tipo: {tipo}, sim: {similarity:.3f})")
            print(f"       Sistemas: {sistemas}")

            # Mostra primeiras 2 linhas do doc pra contexto
            doc_text = results["documents"][0][i]
            lines = [l for l in doc_text.split("\n") if l.strip()][:3]
            for line in lines:
                print(f"       {line[:100]}")

        print()


def test_filtered_retrieve():
    """Teste com filtro por metadado (tipo de documento)."""
    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    collection = client.get_collection("bmg-kb")

    print("\n" + "=" * 80)
    print("🔍 Queries com filtro por tipo de documento")
    print("=" * 80)

    # Só rollbacks
    print("\n📌 Filtro: tipo=rollback | Query: 'PIX timeout integração'")
    results = collection.query(
        query_texts=["PIX timeout integração"],
        n_results=3,
        where={"tipo": "rollback"},
        include=["metadatas", "distances"],
    )
    for doc_id, metadata, dist in zip(
        results["ids"][0], results["metadatas"][0], results["distances"][0]
    ):
        print(f"   • {doc_id} (sim: {1-dist:.3f}) — {metadata.get('sistemas', 'N/A')}")

    # Só GMUDs
    print("\n📌 Filtro: tipo=gmud | Query: 'mudança em banco de dados'")
    results = collection.query(
        query_texts=["mudança em banco de dados"],
        n_results=3,
        where={"tipo": "gmud"},
        include=["metadatas", "distances"],
    )
    for doc_id, metadata, dist in zip(
        results["ids"][0], results["metadatas"][0], results["distances"][0]
    ):
        print(f"   • {doc_id} (sim: {1-dist:.3f}) — {metadata.get('sistemas', 'N/A')}")

    # Só sistemas
    print("\n📌 Filtro: tipo=sistema | Query: 'integrações do módulo PIX'")
    results = collection.query(
        query_texts=["integrações do módulo PIX"],
        n_results=2,
        where={"tipo": "sistema"},
        include=["metadatas", "distances"],
    )
    for doc_id, metadata, dist in zip(
        results["ids"][0], results["metadatas"][0], results["distances"][0]
    ):
        print(f"   • {doc_id} (sim: {1-dist:.3f}) — {metadata.get('sistemas', 'N/A')}")


if __name__ == "__main__":
    test_retrieve()
    test_filtered_retrieve()
