"""
Script de ingestão: lê os docs de kb-test-data/ e indexa no ChromaDB local.

Uso:
    cd ~/Documentos/Projetos/BMG/BMGQAAgent
    pip install chromadb
    python scripts/ingest_kb.py

O ChromaDB persiste em ./chroma_db/ — não precisa re-ingerir toda vez.
"""

import os
import chromadb
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
KB_DATA_DIR = PROJECT_ROOT / "kb-test-data"
CHROMA_DB_PATH = PROJECT_ROOT / "chroma_db"

# Subpastas e seus tipos
FOLDERS = {
    "gmuds": "gmud",
    "rollbacks": "rollback",
    "sistemas": "sistema",
}


def load_documents() -> list[dict]:
    """Lê todos os .txt de kb-test-data/ com metadados."""
    docs = []
    for folder, tipo in FOLDERS.items():
        folder_path = KB_DATA_DIR / folder
        if not folder_path.exists():
            print(f"⚠️  Pasta não encontrada: {folder_path}")
            continue

        for file in sorted(folder_path.glob("*.txt")):
            content = file.read_text(encoding="utf-8")
            doc_id = file.stem  # nome sem extensão

            # Extrair metadados básicos do conteúdo
            metadata = {
                "tipo": tipo,
                "arquivo": file.name,
                "pasta": folder,
            }

            # Tentar extrair sistemas afetados do texto
            for line in content.split("\n"):
                if "Sistemas afetados:" in line:
                    sistemas = line.split(":", 1)[1].strip()
                    metadata["sistemas"] = sistemas
                    break

            docs.append({
                "id": doc_id,
                "content": content,
                "metadata": metadata,
            })

    return docs


def ingest():
    """Ingere documentos no ChromaDB."""
    print(f"📂 Lendo docs de: {KB_DATA_DIR}")
    docs = load_documents()
    print(f"📄 {len(docs)} documentos encontrados")

    if not docs:
        print("❌ Nenhum documento encontrado. Verifique a pasta kb-test-data/")
        return

    # Criar/conectar ao ChromaDB local
    print(f"🗄️  ChromaDB em: {CHROMA_DB_PATH}")
    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))

    # Deletar collection existente pra re-ingerir limpo
    try:
        client.delete_collection("bmg-kb")
        print("🗑️  Collection anterior deletada")
    except Exception:
        pass

    # Criar collection nova
    collection = client.create_collection(
        name="bmg-kb",
        metadata={"description": "Knowledge Base do QA Agent BMG (teste local)"}
    )

    # Adicionar docs
    collection.add(
        ids=[d["id"] for d in docs],
        documents=[d["content"] for d in docs],
        metadatas=[d["metadata"] for d in docs],
    )

    print(f"✅ {len(docs)} documentos ingeridos com sucesso!")
    print(f"   Collection: bmg-kb")
    print(f"   Persistido em: {CHROMA_DB_PATH}")
    print()

    # Resumo
    for tipo, count in _count_by_type(docs).items():
        print(f"   • {tipo}: {count} docs")


def _count_by_type(docs: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for d in docs:
        t = d["metadata"]["tipo"]
        counts[t] = counts.get(t, 0) + 1
    return counts


if __name__ == "__main__":
    ingest()
