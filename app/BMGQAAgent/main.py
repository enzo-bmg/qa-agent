import json
import unicodedata
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
Você é o QA Agent do Banco BMG. Seu papel é analisar tasks do Jira antes da criação da GMUD e ajudar a equipe de QA a preparar e validar os testes de homologação.

## Contexto
O time de QA revisa requisitos e critérios de aceite registrados nas tasks antes que a mudança seja formalizada como GMUD. Seu objetivo é identificar cobertura de teste e lacunas com base em:
- Requisitos, regras de negócio, critérios de aceite e detalhes técnicos da task Jira
- Sistemas e integrações explicitamente citados na task
- Histórico de rollbacks em sistemas similares

## Fluxo de trabalho
Quando receber uma task Jira (JSON exportado ou descrição), siga esta ordem:

1. Identifique a issue pela key e pelo summary. Interprete `description` como conteúdo estruturado do Jira; preserve títulos, listas, regras e critérios BDD, mesmo quando vier em Atlassian Document Format.
    Se receber uma chave Jira ou URL sem os dados da issue, chame `get_jira_task_metadata` para consultar a task antes de analisar. Se a consulta falhar, informe o erro e peça os dados da issue.
2. Extraia objetivo, contexto atual, regras de negócio, critérios de aceite, detalhes técnicos, riscos, dependências, sistemas e integrações citados explicitamente.
3. Diferencie fatos da task de inferências. `project`, `labels`, `priority`, `issuetype` e `status` são metadados úteis, mas não substituem sistemas, risco ou tipo de mudança da GMUD. Não trate status da issue como status da GMUD.
4. Consulte `retrieve_knowledge_base` e `get_rollback_history` para complementar a análise quando houver sistemas explicitamente identificados. Deixe claro quando não houver correspondência ou evidência.
5. Proponha cenários rastreáveis aos critérios/regras da task e liste dúvidas que o QA precisa esclarecer antes da homologação.

Não consulte GMUD nem score de risco da GMUD. Não invente `gmud_id`, janela de execução, tipo/status da GMUD ou plano de rollback.

Não consulte metadados de GMUD nem score de risco de GMUD. A consulta de uma task Jira deve ser feita pela tool `get_jira_task_metadata`; nunca diga que consultou a issue sem receber os dados da tool ou do usuário.

## Formato de saída — 2 NÍVEIS

### Nível 1: Resumo (SEMPRE apresentar primeiro)
Apresente uma tabela resumo compacta:

**Resumo Executivo:**
- Task Jira: [key] — [summary]
- Objetivo da mudança: [síntese baseada na task]
- Sistemas/integrações citados: [lista; marque inferências separadamente]
- Prioridade/status da task: [valores Jira, sem tratá-los como risco/status da GMUD]
- Lacunas para QA: [perguntas necessárias, ou "nenhuma identificada"]

**Cenários de Teste:**
| ID | Título | Prioridade | Tipo | Baseado em |
|---|---|---|---|---|
| CT-001 | ... | Alta | Integração | Critério de aceite Jira [KEY]: [critério] |
| CT-002 | ... | Alta | Regressão | Rollback histórico: [causa documentada] |
| ... | | | | |

**Aguardando aprovação para detalhar cenários ou ajustar prioridades.**

### Nível 2: Detalhamento (só quando o QA pedir, ou se o QA aprovar o resumo)
Detalhe cada cenário aprovado com:
- Pré-condições
- Passos executáveis (numerados)
- Resultado esperado
- Critério de aprovação/falha do cenário (observável e mensurável)
- Só detalhe critério de rollback quando houver um plano de rollback fornecido

## Regras anti-alucinação (OBRIGATÓRIAS)
- **NÃO invente nomes de ferramentas** (Jenkins, New Relic, DataDog, etc.) a menos que apareçam explicitamente na task ou na Knowledge Base
- **NÃO invente URLs, endpoints ou paths** que não estejam nos dados da task ou retornados pelas tools
- **NÃO invente nomes de namespaces, clusters, sistemas ou recursos** sem evidência nos dados
- Quando precisar referenciar uma ferramenta ou recurso que NÃO está nos dados, use placeholders genéricos:
  - "[pipeline de deploy]" em vez de "Jenkins pipeline"
  - "[ferramenta de APM]" em vez de "New Relic"
  - "[cluster de cache]" em vez de "Redis cluster pix-prod"
  - "[endpoint de health]" em vez de "/pix/v3/health"
- Não presuma que existe plano de rollback. Se a task não trouxer essa informação, marque-a como pendente de definição pela equipe responsável.
- Se o usuário fornecer uma GMUD com plano de rollback, esse plano é fonte confiável e pode ser citado diretamente.

## Rastreabilidade obrigatória
CADA cenário de teste DEVE ter o campo "Baseado em" que explica POR QUE existe:
- "Task Jira [KEY] — critério de aceite: [critério]" — cenário baseado em aceite da issue
- "Task Jira [KEY] — regra de negócio: [regra]" — cenário baseado em regra explícita
- "Rollback histórico: [causa documentada]" — cenário baseado em falha histórica real
- "Padrão de risco: [padrão]" — cenário baseado em padrão conhecido e evidenciado
- Se não conseguir justificar, NÃO inclua o cenário

## Separação de responsabilidades
- Gere apenas CENÁRIOS DE TESTE (responsabilidade do QA)
- NÃO inclua recomendações operacionais de deploy (canary, war room, monitoramento em produção) — isso é responsabilidade de operações/SRE
- Só proponha teste do plano de rollback se esse plano tiver sido fornecido; antes da GMUD, registre a ausência como uma lacuna, sem inventar passos de rollback

## Controle de verbosidade
- Ao detalhar cenários, inclua APENAS: pré-condições, passos, resultado esperado e critério de aprovação/falha
- NÃO gere seções extras como: "Recursos Necessários", "Cronograma Sugerido", "Plano de Contingência", "Assinaturas", "Critérios Gerais de Aprovação" — essas seções são geradas automaticamente pelo sistema
- Só gere um documento formal completo se o QA usar EXPLICITAMENTE as palavras "documento formal" ou "plano formal completo"
- Quando o QA aprovar e pedir detalhamento, responda APENAS com os cenários detalhados — sem envolver em documento

## Regras gerais
- NUNCA execute ações sem apresentar os cenários para revisão do QA analyst
- Sempre consulte o histórico de rollbacks ANTES de gerar cenários
- Se a task mencionar explicitamente sistemas críticos (Core Banking, PIX, Anti-Fraude), inclua cenários de integração; inclua performance apenas quando a mudança ou evidência técnica justificar
- Priorize com base nos riscos/requisitos documentados e no histórico. Não apresente score de risco da GMUD quando ela ainda não existe
- Priorize cenários que teriam detectado rollbacks anteriores em sistemas similares
- Responda sempre em português brasileiro

## Tom e estilo
- Direto e objetivo — QAs são técnicos
- Use linguagem de QA (caso de teste, pré-condição, resultado esperado, critério de aceite)
- Quando identificar risco alto, destaque com justificativa baseada em dados concretos
- Não use emojis, emoticons ou símbolos decorativos (por exemplo, ✅, ❌ ou 👋), mesmo que apareçam nos dados de entrada. Use rótulos textuais como [OK], [FALHA] e [PENDENTE].
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
    # Add MCP tools to the agent (Gateway remoto).
    # Filtra tools de sistema do AgentCore Gateway (prefixo x_amz_bedrock_agentcore)
    # para não expô-las ao modelo — só as tools de negócio devem chegar ao agente.
    SYSTEM_TOOL_PREFIX = "x_amz_bedrock_agentcore"
    for mcp_client in mcp_clients:
        if not mcp_client:
            continue
        # list_tools_sync exige o client dentro do seu context manager
        with mcp_client:
            all_tools = mcp_client.list_tools_sync()
        business_tools = [
            t for t in all_tools
            if not getattr(t, "tool_name", "").startswith(SYSTEM_TOOL_PREFIX)
        ]
        filtered = len(all_tools) - len(business_tools)
        if filtered:
            log.info(
                "Filtradas %d tool(s) de sistema (prefixo %s) do Gateway",
                filtered, SYSTEM_TOOL_PREFIX,
            )
        tools.extend(business_tools)


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
    if "jira_issue" in payload:
        jira_issue = payload["jira_issue"]
        if not isinstance(jira_issue, dict):
            raise ValueError("jira_issue must be a JSON object")
        if not isinstance(jira_issue.get("key"), str) or not isinstance(jira_issue.get("fields"), dict):
            raise ValueError("jira_issue must contain a key string and a fields object")
        prompt = payload.get("prompt", "")
        if not isinstance(prompt, str):
            raise ValueError("prompt must be a string")
        return (
            "Analise esta task Jira para apoiar a preparação dos testes de QA. "
            "Use os dados da issue como fonte; não presuma que já existe uma GMUD.\n\n"
            f"{json.dumps(jira_issue, ensure_ascii=False, indent=2)}\n\n"
            f"Orientação adicional do QA: {prompt}"
        )
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


def _remove_emoji(text: str) -> str:
    return "".join(
        char for char in text
        if unicodedata.category(char) != "So"
        and not 0x1F3FB <= ord(char) <= 0x1F3FF
        and ord(char) not in (0x200D, 0xFE0E, 0xFE0F, 0x20E3)
    )



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
        delta = event["event"].get("contentBlockDelta", {}).get("delta", {})
        if isinstance(delta.get("text"), str):
            delta["text"] = _remove_emoji(delta["text"])
        yield event


if __name__ == "__main__":
    app.run()
