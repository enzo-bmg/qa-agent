from typing import Any
from collections import OrderedDict
from strands import Agent, tool
import asyncio
import os
from strands.agent.conversation_manager.null_conversation_manager import NullConversationManager
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from model.load import load_model
from mcp_client.client import get_streamable_http_mcp_client

app = BedrockAgentCoreApp()
log = app.logger

# Modo local: usa tools locais (ChromaDB + mocks) em vez de MCP Gateway
USE_LOCAL_TOOLS = os.getenv("USE_LOCAL_TOOLS", "true").lower() == "true"

# Define a Streamable HTTP MCP Client (usado quando NÃO é local)
mcp_clients = [get_streamable_http_mcp_client()] if not USE_LOCAL_TOOLS else []

DEFAULT_SYSTEM_PROMPT = """
Você é o QA Agent do Banco BMG. Seu papel é analisar GMUDs (Gestões de Mudança) e gerar cenários de teste para a equipe de homologação.

## Contexto
O time de QA do BMG processa ~60 GMUDs por semana. Aproximadamente 10% resultam em rollback, causando retrabalho significativo. Seu objetivo é reduzir essa taxa sugerindo cenários de teste mais eficazes, baseados em:
- Análise da GMUD (sistemas afetados, tipo de mudança, complexidade)
- Histórico de rollbacks em sistemas similares
- Score de risco calculado

## Fluxo de trabalho
Quando receber uma GMUD para análise, siga esta ordem:

1. **Obter metadados da GMUD** — use `get_gmud_metadata` para buscar informações detalhadas
2. **Consultar Knowledge Base** — use `retrieve_knowledge_base` para buscar rollbacks e docs de sistemas relacionados
3. **Consultar histórico de rollbacks** — use `get_rollback_history` passando TODOS os sistemas afetados da GMUD (a lista completa)
4. **Calcular score de risco** — use `get_score_info` passando o gmud_id E a lista completa de sistemas_afetados
5. **Gerar cenários de teste** — com base nas informações coletadas, gere o plano de testes

## REGRA CRÍTICA: Ao chamar get_score_info
SEMPRE passe os sistemas_afetados que vieram do get_gmud_metadata. Exemplo:
- Se get_gmud_metadata retornou sistemas_afetados: ["API Gateway", "Core Banking", "Módulo PIX", "Anti-Fraude"]
- Chame: get_score_info(gmud_id="CHG...", sistemas_afetados=["API Gateway", "Core Banking", "Módulo PIX", "Anti-Fraude"])
- NUNCA chame get_score_info sem passar os sistemas. Isso causa cálculo incorreto do score.

## Formato de saída — 2 NÍVEIS

### Nível 1: Resumo (SEMPRE apresentar primeiro)
Apresente uma tabela resumo compacta:

**Resumo Executivo:**
- GMUD: [id] — [título]
- Sistemas: [lista]
- Score de Risco: [valor]/100 — [nível]
- Janela: [data e horário]

**Cenários de Teste:**
| ID | Título | Prioridade | Tipo | Baseado em |
|---|---|---|---|---|
| CT-001 | ... | Alta | Integração | Rollback CHG0071234 (timeout) |
| CT-002 | ... | Alta | Regressão | Requisito: retrocompatibilidade |
| ... | | | | |

**Aguardando aprovação para detalhar cenários ou ajustar prioridades.**

### Nível 2: Detalhamento (só quando o QA pedir, ou se o QA aprovar o resumo)
Detalhe cada cenário aprovado com:
- Pré-condições
- Passos executáveis (numerados)
- Resultado esperado
- Critério de rollback (específico, mensurável)

## Regras anti-alucinação (OBRIGATÓRIAS)
- **NÃO invente nomes de ferramentas** (Jenkins, New Relic, DataDog, etc.) a menos que apareçam explicitamente nos dados da GMUD ou da Knowledge Base
- **NÃO invente URLs, endpoints ou paths** que não estejam nos dados retornados pelas tools
- **NÃO invente nomes de namespaces, clusters ou recursos** (ex: "pix-prod", "namespace pix-*") sem evidência nos dados
- Quando precisar referenciar uma ferramenta ou recurso que NÃO está nos dados, use placeholders genéricos:
  - "[pipeline de deploy]" em vez de "Jenkins pipeline"
  - "[ferramenta de APM]" em vez de "New Relic"
  - "[cluster de cache]" em vez de "Redis cluster pix-prod"
  - "[endpoint de health]" em vez de "/pix/v3/health"
- Se a GMUD menciona "reverter via pipeline", use "[pipeline de deploy conforme plano de rollback]" — não invente o nome da ferramenta
- O plano de rollback descrito na GMUD É dado confiável — pode citá-lo diretamente

## Rastreabilidade obrigatória
CADA cenário de teste DEVE ter o campo "Baseado em" que explica POR QUE existe:
- "Rollback CHG00XXXXX: [causa resumida]" — cenário baseado em falha histórica real
- "Requisito GMUD: [aspecto da mudança]" — cenário baseado na descrição da GMUD
- "Padrão de risco: [padrão]" — cenário baseado em padrão conhecido (ex: DDL em tabela grande)
- Se não conseguir justificar, NÃO inclua o cenário

## Separação de responsabilidades
- Gere apenas CENÁRIOS DE TESTE (responsabilidade do QA)
- NÃO inclua recomendações operacionais de deploy (canary, war room, monitoramento em produção) — isso é responsabilidade de operações/SRE
- A exceção é "testar o plano de rollback" (CT de rollback) — porque o QA valida que o rollback funciona ANTES do deploy

## Controle de verbosidade
- Ao detalhar cenários, inclua APENAS: pré-condições, passos, resultado esperado e critério de rollback
- NÃO gere seções extras como: "Recursos Necessários", "Cronograma Sugerido", "Plano de Contingência", "Assinaturas", "Critérios Gerais de Aprovação" — essas seções são geradas automaticamente pelo sistema
- Só gere um documento formal completo se o QA usar EXPLICITAMENTE as palavras "documento formal" ou "plano formal completo"
- Quando o QA aprovar e pedir detalhamento, responda APENAS com os cenários detalhados — sem envolver em documento

## Regras gerais
- NUNCA execute ações sem apresentar os cenários para revisão do QA analyst
- Sempre consulte o histórico de rollbacks ANTES de gerar cenários
- Se a GMUD envolve sistemas críticos (Core Banking, PIX, Anti-Fraude), SEMPRE inclua cenários de integração e performance
- Se o score de risco for "alto" ou "critico", inclua cenário de rollback explícito
- Priorize cenários que teriam detectado rollbacks anteriores em sistemas similares
- Responda sempre em português brasileiro

## Tom e estilo
- Direto e objetivo — QAs são técnicos
- Use linguagem de QA (caso de teste, pré-condição, resultado esperado, critério de aceite)
- Quando identificar risco alto, destaque com justificativa baseada em dados concretos
"""


# Define a collection of tools used by the model
tools = []

_INLINE_FUNCTION_NAMES = set()

# Carregar tools locais (ChromaDB + mocks) ou MCP tools (Gateway remoto)
if USE_LOCAL_TOOLS:
    from local_tools import LOCAL_TOOLS
    tools.extend(LOCAL_TOOLS)
    _INLINE_FUNCTION_NAMES = {t.tool_name for t in LOCAL_TOOLS if hasattr(t, 'tool_name')}
    log.info(f"Usando {len(LOCAL_TOOLS)} tools locais (ChromaDB + mocks)")
else:
    # Add MCP client to tools if available
    for mcp_client in mcp_clients:
        if mcp_client:
            tools.append(mcp_client)


def _make_conversation_manager():
    return NullConversationManager()

# Reuses one Agent per session_id so each session keeps its own in-process
# conversation history (best-effort; resets on cold start). The cache is bounded
# to 128 sessions with LRU eviction (least-recently-used is dropped and its
# history reset) so a single process serving many sessions cannot leak history
# between them or grow without limit. For durable history, attach a session manager.
def agent_factory():
    cache = OrderedDict()
    def get_or_create_agent(session_id):
        if session_id in cache:
            cache.move_to_end(session_id)
            return cache[session_id]
        if len(cache) >= 128:
            cache.popitem(last=False)
        cache[session_id] = Agent(
            model=load_model(),
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            tools=tools,
            conversation_manager=_make_conversation_manager(),
            hooks=[
            ],
        )
        return cache[session_id]
    return get_or_create_agent
get_or_create_agent = agent_factory()


def strip_trailing_tool_use(messages: Any) -> list[dict]:
    """Strip toolUse blocks from the tail until the last message has none."""
    if not isinstance(messages, list):
        raise ValueError("messages must be a list")

    messages = list(messages)
    while messages:
        last = messages[-1]
        if not isinstance(last, dict):
            raise ValueError("each message must be an object")
        original_content = last.get("content", [])
        if not isinstance(original_content, list) or not all(isinstance(block, dict) for block in original_content):
            raise ValueError("each message content value must be a list of content blocks")

        content = [block for block in original_content if "toolUse" not in block]
        if len(content) == len(original_content):
            break
        if content:
            messages[-1] = {**last, "content": content}
            break
        messages.pop()

    return messages


def _extract_prompt(payload: dict):
    """Accept validated harness messages, tool results, or a plain prompt string."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    if "messages" in payload:
        return strip_trailing_tool_use(payload["messages"])
    if "tool_results" in payload:
        tool_results = payload["tool_results"]
        if not isinstance(tool_results, list) or not all(
            isinstance(tool_result, dict) and isinstance(tool_result.get("toolUseId"), str)
            for tool_result in tool_results
        ):
            raise ValueError("tool_results must contain objects with a toolUseId string")
        return [{"role": "user", "content": [{"toolResult": {
            "toolUseId": tr["toolUseId"],
            "status": tr.get("status", "success"),
            "content": tr.get("content", []),
        }} for tr in tool_results]}]
    prompt = payload.get("prompt", "")
    if not isinstance(prompt, str):
        raise ValueError("prompt must be a string")
    return prompt


def _has_inline_function_call(messages) -> bool:
    """Return True if messages contains an assistant toolUse for an inline function tool."""
    if not _INLINE_FUNCTION_NAMES or not isinstance(messages, list):
        return False
    for msg in messages:
        if msg.get("role") == "assistant":
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("toolUse", {}).get("name") in _INLINE_FUNCTION_NAMES:
                    return True
    return False


def _is_inline_function_call(event: dict) -> bool:
    """Check if a contentBlockStart event is for an inline function tool."""
    if not _INLINE_FUNCTION_NAMES:
        return False
    cbs = event.get("contentBlockStart", {})
    start = cbs.get("start", {})
    tool_use = start.get("toolUse") if isinstance(start, dict) else None
    return tool_use is not None and tool_use.get("name") in _INLINE_FUNCTION_NAMES



@app.entrypoint
async def invoke(payload, context):
    log.info("Invoking Agent.....")


    session_id = getattr(context, 'session_id', 'default-session')
    agent = get_or_create_agent(session_id)

    prompt = _extract_prompt(payload)


    async for event in agent.stream_async(
        prompt,
    ):
        if not isinstance(event, dict) or "event" not in event:
            continue
        cbs = event["event"].get("contentBlockStart")
        if cbs is not None and not cbs.get("start"):
            continue
        yield event


if __name__ == "__main__":
    app.run()
