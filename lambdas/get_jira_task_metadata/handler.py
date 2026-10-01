"""Lambda mock: get_jira_task_metadata."""

import json
import os
import re
from base64 import b64encode
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

# Mock data baseado nas dez primeiras tasks coletadas do Jira.
MOCK_TASKS = {
    "SCCIC-584": {
        "task_id": "SCCIC-584",
        "titulo": "Autenticação robusta prcc-integra-reparcelamento-consumer",
        "tipo_task": "História",
        "prioridade": "Medium",
        "descricao": (
            "Homologar a implementação de autenticação robusta no consumer "
            "prcc-integra-reparcelamento-consumer e preparar o pacote para "
            "produção antes da atualização do PRCC Ajuste Financeiro."
        ),
        "links_pull_requests": [],
    },
    "SPAD-2487": {
        "task_id": "SPAD-2487",
        "titulo": "Desbloqueio do contrato origem Refinanciamento",
        "tipo_task": "História",
        "prioridade": "Highest",
        "descricao": (
            "Desacoplar o desbloqueio do contrato de origem do fluxo de "
            "desaverbação. Após o cancelamento de uma proposta de refinanciamento, "
            "desbloquear somente o contrato correspondente."
        ),
        "links_pull_requests": [],
    },
    "SPFRAU-6351": {
        "task_id": "SPFRAU-6351",
        "titulo": "[FALCON] - Expurgo Setembro",
        "tipo_task": "História",
        "prioridade": "Highest",
        "descricao": (
            "Expurgar do Falcon as contas indevidas identificadas pela área de "
            "Prevenção a Fraudes e parametrizar o processo para não enviar contas "
            "de investimento."
        ),
        "links_pull_requests": [],
    },
    "SPLDD-87": {
        "task_id": "SPLDD-87",
        "titulo": "Inclusão de campos Origem e DataInserção no MongoDB do Integrador KN1",
        "tipo_task": "História",
        "prioridade": "Medium",
        "descricao": (
            "Adicionar os campos Origem e DataInserção aos documentos do MongoDB "
            "do integrador KN1 para identificar a procedência dos registros, "
            "analisar gargalos e priorizar o processamento."
        ),
        "links_pull_requests": [],
    },
    "SGCH-2584": {
        "task_id": "SGCH-2584",
        "titulo": "CLONE - [CASHBACK PT-02] teste integrado PROE de credito em conta corrente",
        "tipo_task": "História",
        "prioridade": "Medium",
        "descricao": (
            "Implementar o resgate de cashback por crédito em conta corrente "
            "usando o processamento síncrono do PROE, com validação de elegibilidade "
            "e separação do fluxo de crédito em fatura."
        ),
        "links_pull_requests": [],
    },
    "SCER-1654": {
        "task_id": "SCER-1654",
        "titulo": "Ações Cíveis (Congela Contrato) - Set/26",
        "tipo_task": "História",
        "prioridade": "Medium",
        "descricao": (
            "Congelar no sistema EM os contratos em ação cível para interromper "
            "juros gerenciais conforme a Resolução 4966 do BACEN, com validação "
            "da base e registro de evidências da execução."
        ),
        "links_pull_requests": [],
    },
    "SPELDC-2461": {
        "task_id": "SPELDC-2461",
        "titulo": "Dados CRS na ficha cadastral PF e PJ - Ambiente UAT",
        "tipo_task": "História",
        "prioridade": "Medium",
        "descricao": (
            "Adicionar dados de CRS às fichas cadastrais de pessoa física e "
            "jurídica no Portal Empresas. Quando CRS for Sim, habilitar e exigir "
            "TIN/NIF e país de residência fiscal."
        ),
        "links_pull_requests": [],
    },
    "SVWHAT-1092": {
        "task_id": "SVWHAT-1092",
        "titulo": "[UX Research] Analisar jornadas de clientes reais para identificação de causas de quebra de fluxo e recusa de ofertas",
        "tipo_task": "História",
        "prioridade": "Medium",
        "descricao": (
            "Analisar jornadas reais concluídas, abandonadas ou com ofertas "
            "recusadas para identificar pontos de atrito e oportunidades de "
            "melhoria, respeitando as diretrizes de privacidade."
        ),
        "links_pull_requests": [],
    },
    "SVWHAT-1091": {
        "task_id": "SVWHAT-1091",
        "titulo": "[UAT] Executar testes integrados da Jornada de Vendas no ambiente UAT para validação das APIs de parceiros BMG",
        "tipo_task": "História",
        "prioridade": "Medium",
        "descricao": (
            "Executar testes integrados UAT nas rotas da Jornada de Vendas e "
            "validar retornos HTTP, payloads, regras de negócio, integrações e "
            "tratamento de erros antes da disponibilização em produção."
        ),
        "links_pull_requests": [],
    },
    "SLTU-2379": {
        "task_id": "SLTU-2379",
        "titulo": "Atualizar a inve-agendamento-resgate-clc-scheduler para o .net 10 e ajustar a autenticação para robusta ",
        "tipo_task": "História",
        "prioridade": "Medium",
        "descricao": (
            "Atualizar a aplicação inve-agendamento-resgate-clc-scheduler para "
            ".NET 10, adequar a autenticação ao padrão robusto e validar o "
            "agendamento de resgate CLC."
        ),
        "links_pull_requests": [],
    },
}


class JiraConfigurationError(Exception):
    """Raised when Jira API configuration is missing or invalid."""


class JiraIssueNotFound(Exception):
    """Raised when Jira does not contain the requested issue."""


class JiraApiError(Exception):
    """Raised when the Jira API cannot return a valid issue."""


def _extract_task_id(value):
    if not isinstance(value, str):
        return None

    value = value.strip()
    if "/" in value or "://" in value:
        path = urlsplit(value).path.rstrip("/")
        match = re.search(r"/browse/([A-Z][A-Z0-9_]*-\d+)$", path, re.IGNORECASE)
        return match.group(1).upper() if match else None

    return value if re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", value, re.IGNORECASE) else None


def _description_to_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (_description_to_text(item) for item in value)))
    if not isinstance(value, dict):
        return ""

    node_type = value.get("type")
    if node_type == "text":
        text = value.get("text", "")
        link = next(
            (
                mark.get("attrs", {}).get("href")
                for mark in value.get("marks", [])
                if mark.get("type") == "link"
            ),
            None,
        )
        if link and link not in text:
            return f"{text} ({link})" if text else link
        return text
    if node_type == "hardBreak":
        return "\n"

    children = _description_to_text(value.get("content", []))
    if node_type in {"paragraph", "heading", "blockquote", "codeBlock", "listItem"}:
        return children.strip()
    return children


def _extract_pull_request_links(description):
    repository_pattern = re.compile(
        r"(?:/pull(?:request)?/|/pulls?/|/merge_requests?/|/_git/|/repository/|/repos?/)",
        re.IGNORECASE,
    )
    urls = re.findall(r"https?://[^\s<>\]\[)]+", description, re.IGNORECASE)
    return list(dict.fromkeys(
        url.rstrip(".,;:")
        for url in urls
        if repository_pattern.search(url)
    ))


def _collect_pull_request_urls(value):
    if isinstance(value, str):
        return _extract_pull_request_links(value)
    if isinstance(value, dict):
        return [
            url
            for child in value.values()
            for url in _collect_pull_request_urls(child)
        ]
    if isinstance(value, list):
        return [
            url
            for child in value
            for url in _collect_pull_request_urls(child)
        ]
    return []


def _fetch_optional_json(url, headers, timeout, task_id, source):
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        print(f"Jira {source} indisponível para {task_id}: HTTP {exc.code}")
    except (URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"Jira {source} indisponível para {task_id}: {type(exc).__name__}")
    return None


def _fetch_issue_pull_request_links(issue, base_url, headers, timeout):
    task_id = issue.get("key", "")
    links = []

    remote_links_url = (
        f"{base_url}/rest/api/3/issue/{quote(task_id, safe='')}/remotelink"
    )
    remote_links = _fetch_optional_json(
        remote_links_url, headers, timeout, task_id, "remote links"
    )
    if isinstance(remote_links, list):
        links.extend(_collect_pull_request_urls(remote_links))

    fetch_dev_status = os.getenv("JIRA_FETCH_DEV_STATUS", "true").strip().lower() not in {
        "0", "false", "no", "off"
    }
    issue_id = issue.get("id")
    if fetch_dev_status and issue_id:
        query = urlencode({
            "issueId": issue_id,
            "applicationType": "azureDevOps",
            "dataType": "pullrequest",
        })
        dev_status_url = f"{base_url}/rest/dev-status/1.0/issue/detail?{query}"
        dev_status = _fetch_optional_json(
            dev_status_url, headers, timeout, task_id, "Dev Status"
        )
        links.extend(_collect_pull_request_urls(dev_status))

    return list(dict.fromkeys(links))


def _normalize_jira_issue(issue, requested_task_id):
    fields = issue.get("fields") or {}
    description = _description_to_text(fields.get("description"))
    return {
        "task_id": issue.get("key") or requested_task_id,
        "titulo": fields.get("summary") or "",
        "tipo_task": (fields.get("issuetype") or {}).get("name") or "",
        "prioridade": (fields.get("priority") or {}).get("name") or "",
        "descricao": description,
        "links_pull_requests": _extract_pull_request_links(description),
    }


def fetch_jira_task(task_id):
    """Fetch one Jira issue and normalize it to the collected task schema."""
    base_url = os.getenv("JIRA_BASE_URL", "").rstrip("/")
    api_token = os.getenv("JIRA_API_TOKEN", "")
    configured_auth_type = os.getenv("JIRA_AUTH_TYPE", "").strip().lower()
    auth_type = configured_auth_type or (
        "basic" if os.getenv("JIRA_EMAIL") or os.getenv("JIRA_USERNAME") else "bearer"
    )
    api_version = os.getenv("JIRA_API_VERSION", "2").strip()

    if not base_url:
        raise JiraConfigurationError("JIRA_BASE_URL não foi configurada")
    if not api_token:
        raise JiraConfigurationError("JIRA_API_TOKEN não foi configurada")
    if api_version not in {"2", "3"}:
        raise JiraConfigurationError("JIRA_API_VERSION deve ser 2 ou 3")

    headers = {"Accept": "application/json"}
    if auth_type == "bearer":
        headers["Authorization"] = f"Bearer {api_token}"
    elif auth_type == "basic":
        username = os.getenv("JIRA_USERNAME") or os.getenv("JIRA_EMAIL")
        if not username:
            raise JiraConfigurationError(
                "JIRA_USERNAME (ou JIRA_EMAIL) é obrigatório para autenticação Basic"
            )
        credentials = b64encode(f"{username}:{api_token}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {credentials}"
    else:
        raise JiraConfigurationError("JIRA_AUTH_TYPE deve ser bearer ou basic")

    timeout_value = os.getenv("JIRA_TIMEOUT_SECONDS", "10")
    try:
        timeout = float(timeout_value)
    except ValueError as exc:
        raise JiraConfigurationError("JIRA_TIMEOUT_SECONDS deve ser numérico") from exc
    if timeout <= 0:
        raise JiraConfigurationError("JIRA_TIMEOUT_SECONDS deve ser maior que zero")

    fields = "*all"
    query = urlencode({"fields": fields})
    url = (
        f"{base_url}/rest/api/{api_version}/issue/"
        f"{quote(task_id, safe='')}?{query}"
    )
    request = Request(url, headers=headers)

    try:
        with urlopen(request, timeout=timeout) as response:
            issue = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            raise JiraIssueNotFound(task_id) from exc
        if exc.code == 403:
            raise JiraApiError(
                "Jira respondeu HTTP 403 (acesso negado). Verifique se o usuário "
                "tem permissão para visualizar a issue e se a autenticação está "
                "correta: Atlassian Cloud usa JIRA_AUTH_TYPE=basic com "
                "JIRA_EMAIL + JIRA_API_TOKEN."
            ) from exc
        raise JiraApiError(f"Jira respondeu com HTTP {exc.code}") from exc
    except URLError as exc:
        raise JiraApiError("Não foi possível conectar à API do Jira") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JiraApiError("A API do Jira retornou uma resposta inválida") from exc

    if not isinstance(issue, dict):
        raise JiraApiError("A API do Jira retornou uma issue inválida")
    task = _normalize_jira_issue(issue, task_id)
    task["links_pull_requests"] = list(dict.fromkeys(
        task["links_pull_requests"]
        + _collect_pull_request_urls(issue.get("fields") or {})
        + _fetch_issue_pull_request_links(issue, base_url, headers, timeout)
    ))
    return task


def lambda_handler(event, context):
    """Handler principal da Lambda."""

    # Extrair input — pode vir do API Gateway ou do AgentCore
    if isinstance(event, str):
        event = json.loads(event)

    # Suporte a diferentes formatos de input
    body = event.get("body", event)
    if isinstance(body, str):
        body = json.loads(body)

    task_id = _extract_task_id(
        body.get("task_id") or body.get("key") or body.get("url") or body.get("link")
    )

    if not task_id:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": "Informe task_id como chave Jira ou URL /browse/<chave>"
            }, ensure_ascii=False)
        }

    mode = os.getenv("JIRA_MODE", "api").strip().lower()
    try:
        if mode == "mock":
            task = MOCK_TASKS.get(task_id)
            if task is None:
                raise JiraIssueNotFound(task_id)
        elif mode == "api":
            task = fetch_jira_task(task_id)
        else:
            raise JiraConfigurationError("JIRA_MODE deve ser mock ou api")
    except JiraIssueNotFound:
        return {
            "statusCode": 404,
            "body": json.dumps({
                "error": f"Task {task_id} não encontrada",
                **({"tasks_disponiveis": list(MOCK_TASKS.keys())} if mode == "mock" else {}),
            }, ensure_ascii=False),
        }
    except JiraConfigurationError as exc:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(exc)}, ensure_ascii=False),
        }
    except JiraApiError as exc:
        return {
            "statusCode": 502,
            "body": json.dumps({"error": str(exc)}, ensure_ascii=False),
        }

    return {
        "statusCode": 200,
        "body": json.dumps(task, ensure_ascii=False)
    }


# Para teste local
if __name__ == "__main__":
    # Simula chamada
    test_event = {"task_id": "https://bancobmg.atlassian.net/browse/SCCIC-584"}
    result = lambda_handler(test_event, None)
    print(json.dumps(json.loads(result["body"]), indent=2, ensure_ascii=False))
