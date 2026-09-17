"""
Tools locais do QA Agent BMG.

Integra:
- ChromaDB (Knowledge Base local) para retrieve/RAG
- Lambdas mock (get_gmud_metadata, get_rollback_history, get_score_info)

Em produção, essas tools serão substituídas por:
- Bedrock Knowledge Base (retrieve via bedrock-agent-runtime)
- MCP tools via AgentCore Gateway (Lambdas reais)
"""

import json
import sys
from pathlib import Path
from strands import tool

# Adicionar pasta de lambdas ao path pra importar os handlers
PROJECT_ROOT = Path(__file__).parent.parent.parent
LAMBDAS_DIR = PROJECT_ROOT / "lambdas"
sys.path.insert(0, str(LAMBDAS_DIR))

# ─────────────────────────────────────────────────────────────────────────────
# Configuração: KB real (Bedrock) vs local (ChromaDB)
# ─────────────────────────────────────────────────────────────────────────────

import os
import boto3

# Se tiver KB_ID configurado, usa Bedrock KB real. Senão, fallback pro ChromaDB.
BEDROCK_KB_ID = os.getenv("BEDROCK_KB_ID", "X8RYNPZISY")
USE_BEDROCK_KB = os.getenv("USE_BEDROCK_KB", "true").lower() == "true"
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_PROFILE = os.getenv("AWS_PROFILE", "ciandt_teste")

# ChromaDB path (fallback)
CHROMA_DB_PATH = PROJECT_ROOT / "chroma_db"


# ─────────────────────────────────────────────────────────────────────────────
# Tool 1: Knowledge Base retrieve (Bedrock KB real OU ChromaDB local)
# ─────────────────────────────────────────────────────────────────────────────

def _get_bedrock_kb_client():
    """Cria client do bedrock-agent-runtime."""
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    return session.client("bedrock-agent-runtime")


def _retrieve_from_bedrock_kb(query: str, n_results: int = 3) -> str:
    """Retrieve via Bedrock Knowledge Base real."""
    client = _get_bedrock_kb_client()
    response = client.retrieve(
        knowledgeBaseId=BEDROCK_KB_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "managedSearchConfiguration": {
                "numberOfResults": n_results,
            }
        },
    )

    results = response.get("retrievalResults", [])
    if not results:
        return "Nenhum documento relevante encontrado na Knowledge Base."

    output_parts = []
    for i, result in enumerate(results):
        content = result.get("content", {}).get("text", "")
        score = result.get("score", 0)
        location = result.get("location", {}).get("s3Location", {}).get("uri", "?")
        output_parts.append(
            f"--- Resultado {i+1} (score: {score:.3f}, source: {location}) ---\n{content}\n"
        )

    return "\n".join(output_parts)


def _retrieve_from_chromadb(query: str, tipo: str = "", n_results: int = 3) -> str:
    """Retrieve via ChromaDB local (fallback)."""
    import chromadb
    try:
        client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
        collection = client.get_collection("bmg-kb")
    except Exception as e:
        return f"Erro ao conectar à Knowledge Base local: {e}. Rode 'python scripts/ingest_kb.py' primeiro."

    kwargs = {
        "query_texts": [query],
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }

    if tipo and tipo in ("gmud", "rollback", "sistema"):
        kwargs["where"] = {"tipo": tipo}

    results = collection.query(**kwargs)

    if not results["ids"][0]:
        return "Nenhum documento relevante encontrado na Knowledge Base."

    output_parts = []
    for i, (doc_id, doc_text, metadata, distance) in enumerate(zip(
        results["ids"][0],
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    )):
        similarity = 1 - distance
        output_parts.append(
            f"--- Resultado {i+1} (id: {doc_id}, tipo: {metadata.get('tipo', '?')}, "
            f"similaridade: {similarity:.3f}) ---\n{doc_text}\n"
        )

    return "\n".join(output_parts)


@tool
def retrieve_knowledge_base(query: str, tipo: str = "", n_results: int = 3) -> str:
    """Busca informações relevantes na Knowledge Base (GMUDs históricas, rollbacks, documentação de sistemas).

    Args:
        query: Texto da busca semântica (ex: "rollbacks no módulo PIX")
        tipo: Filtro opcional por tipo de documento: "gmud", "rollback" ou "sistema". Vazio = todos.
        n_results: Número máximo de resultados (default: 3)

    Returns:
        Documentos relevantes encontrados na Knowledge Base com score de similaridade.
    """
    if USE_BEDROCK_KB:
        try:
            return _retrieve_from_bedrock_kb(query, n_results)
        except Exception as e:
            # Fallback pro ChromaDB se Bedrock falhar
            return f"Erro na KB Bedrock ({e}). Tentando fallback local...\n" + _retrieve_from_chromadb(query, tipo, n_results)
    else:
        return _retrieve_from_chromadb(query, tipo, n_results)


# ─────────────────────────────────────────────────────────────────────────────
# Tool 2: get_gmud_metadata (mock local)
# ─────────────────────────────────────────────────────────────────────────────

@tool
def get_gmud_metadata(gmud_id: str) -> str:
    """Obtém metadados de uma GMUD do ServiceNow.

    Args:
        gmud_id: Identificador da GMUD (ex: CHG0074521)

    Returns:
        Metadados da GMUD: título, descrição, sistemas afetados, janela, plano de rollback.
    """
    from get_gmud_metadata.handler import lambda_handler
    result = lambda_handler({"gmud_id": gmud_id}, None)
    return result["body"]


# ─────────────────────────────────────────────────────────────────────────────
# Tool 3: get_rollback_history (mock local)
# ─────────────────────────────────────────────────────────────────────────────

@tool
def get_rollback_history(sistemas: list[str], periodo_meses: int = 12, limit: int = 10) -> str:
    """Consulta histórico de rollbacks em GMUDs anteriores que envolvem sistemas similares.

    Args:
        sistemas: Lista de sistemas afetados para buscar rollbacks (ex: ["Módulo PIX", "API Gateway"])
        periodo_meses: Meses para trás na busca (default: 12)
        limit: Número máximo de resultados (default: 10)

    Returns:
        Rollbacks encontrados com causa raiz, impacto e lições aprendidas.
    """
    from get_rollback_history.handler import lambda_handler
    result = lambda_handler({
        "sistemas": sistemas,
        "periodo_meses": periodo_meses,
        "limit": limit,
    }, None)
    return result["body"]


# ─────────────────────────────────────────────────────────────────────────────
# Tool 4: get_score_info (mock local)
# ─────────────────────────────────────────────────────────────────────────────

@tool
def get_score_info(gmud_id: str, sistemas_afetados: list[str] = None) -> str:
    """Calcula score de risco de uma GMUD baseado em fatores ponderados.

    IMPORTANTE: Sempre passe sistemas_afetados. Sem essa lista, o score será incorretamente baixo.

    Args:
        gmud_id: Identificador da GMUD
        sistemas_afetados: Lista de sistemas envolvidos na GMUD. OBRIGATÓRIO para cálculo correto. Obtenha de get_gmud_metadata.

    Returns:
        Score de risco (0-100), nível, fatores e recomendação.
    """
    from get_score_info.handler import lambda_handler

    # Fallback: se o agente não passou sistemas, tenta buscar da GMUD
    if not sistemas_afetados:
        try:
            from get_gmud_metadata.handler import MOCK_GMUDS
            gmud_data = MOCK_GMUDS.get(gmud_id)
            if gmud_data:
                sistemas_afetados = gmud_data.get("sistemas_afetados", [])
        except Exception:
            pass

    result = lambda_handler({
        "gmud_id": gmud_id,
        "sistemas_afetados": sistemas_afetados or [],
    }, None)
    return result["body"]


# ─────────────────────────────────────────────────────────────────────────────
# Lista de todas as tools locais
# ─────────────────────────────────────────────────────────────────────────────

LOCAL_TOOLS = [
    retrieve_knowledge_base,
    get_gmud_metadata,
    get_rollback_history,
    get_score_info,
]
