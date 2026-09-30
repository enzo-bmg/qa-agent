"""Export Jira issues from filter 33221."""

import argparse
import base64
import csv
import json
import os
import re
import sys
from pathlib import Path

import urllib.error
import urllib.parse
import urllib.request


JIRA_BASE_URL = "https://bancobmg.atlassian.net"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FILTER_ID = "33221"
MAX_PAGES = 5
ISSUE_FIELDS = ("*all",)
TASK_FIELDS = (
    "task_id",
    "titulo",
    "tipo_task",
    "prioridade",
    "descricao",
    "links_pull_requests",
)
PULL_REQUEST_URL_PATTERN = re.compile(
    r"https?://[^\s<>\]\[)]+(?:/pull-?requests?/|/pull/|/pulls/|/merge[_-]?requests?/)[^\s<>\]\[)]*",
    re.IGNORECASE,
)


def adf_to_text(node):
    """Convert Jira Atlassian Document Format to readable text."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(filter(None, (adf_to_text(item) for item in node)))
    if not isinstance(node, dict):
        return ""

    node_type = node.get("type")
    if node_type == "text":
        text = node.get("text", "")
        for mark in node.get("marks", []):
            if mark.get("type") == "link":
                url = mark.get("attrs", {}).get("href", "")
                if url and url not in text:
                    return f"{text} ({url})" if text else url
        return text
    if node_type == "hardBreak":
        return "\n"

    children = node.get("content", [])
    if node_type in {"bulletList", "orderedList"}:
        lines = []
        for index, item in enumerate(children, start=1):
            text = adf_to_text(item).strip()
            if text:
                prefix = "- " if node_type == "bulletList" else f"{index}. "
                lines.append(prefix + text.replace("\n", "\n  "))
        return "\n".join(lines)
    return adf_to_text(children).strip()


def request_json(url, headers):
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def find_pull_requests(data):
    """Read PR records from Jira's development-status response."""
    pull_requests = []

    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower() == "pullrequests" and isinstance(child, list):
                    pull_requests.extend(item for item in child if isinstance(item, dict))
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(data)
    return pull_requests


def named_value(value):
    if isinstance(value, dict):
        return value.get("name") or value.get("displayName") or value.get("id") or ""
    return value or ""


def collect_urls(value):
    """Collect PR URLs recursively from Jira fields and development-status data."""
    urls = []
    if isinstance(value, str):
        urls.extend(
            match.group(0).rstrip(".,;:")
            for match in PULL_REQUEST_URL_PATTERN.finditer(value)
        )
    elif isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in {"url", "html_url", "remoteurl", "weburl"} and isinstance(child, str):
                if child.startswith(("https://", "http://")) and PULL_REQUEST_URL_PATTERN.search(child):
                    urls.append(child.rstrip(".,;:"))
            else:
                urls.extend(collect_urls(child))
    elif isinstance(value, list):
        for child in value:
            urls.extend(collect_urls(child))
    return urls


def get_pr_metadata(issue, jira_headers, debug=False):
    query = urllib.parse.urlencode({
        "issueId": issue.get("id", ""),
        "applicationType": "azureDevOps",
        "dataType": "pullrequest",
    })
    url = f"{JIRA_BASE_URL}/rest/dev-status/1.0/issue/detail?{query}"
    try:
        data = request_json(url, jira_headers)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        if debug:
            print(f"Aviso: nao foi possivel consultar PRs de {issue.get('key')}: {exc}", file=sys.stderr)
        return []
    return data


def get_issue_remote_links(issue, jira_headers, debug=False):
    issue_key = urllib.parse.quote(str(issue.get("key", "")), safe="")
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/remotelink"
    try:
        data = request_json(url, jira_headers)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        if debug:
            print(f"Aviso: nao foi possivel consultar links anexados a {issue.get('key')}: {exc}", file=sys.stderr)
        return []
    return data if isinstance(data, list) else []


def get_pull_request_links(issue, jira_headers, debug=False):
    links = []
    fetch_dev_status = os.getenv("JIRA_FETCH_DEV_STATUS", "").strip().lower() in {
        "1", "true", "yes", "on"
    }
    if fetch_dev_status:
        dev_status = get_pr_metadata(issue, jira_headers, debug=debug)
        for pull_request in find_pull_requests(dev_status):
            links.extend(collect_urls(pull_request))
    elif debug:
        print(
            "Consulta Jira Dev Status desabilitada; defina "
            "JIRA_FETCH_DEV_STATUS=true para habilitá-la.",
            file=sys.stderr,
        )

    for remote_link in get_issue_remote_links(issue, jira_headers, debug=debug):
        link_object = remote_link.get("object") or {}
        link_url = link_object.get("url", "")
        if isinstance(link_url, str) and PULL_REQUEST_URL_PATTERN.search(link_url):
            links.append(link_url.rstrip(".,;:"))

            links.extend(collect_urls((issue.get("fields") or {})))
    description = adf_to_text((issue.get("fields") or {}).get("description"))
    links.extend(match.group(0).rstrip(".,;:") for match in PULL_REQUEST_URL_PATTERN.finditer(description))
    return list(dict.fromkeys(links))


def normalize_issue(issue, jira_headers, debug=False):
    fields = issue.get("fields", {})
    return {
        "task_id": issue.get("key", ""),
        "titulo": fields.get("summary", "") or "",
        "tipo_task": (fields.get("issuetype") or {}).get("name", ""),
        "prioridade": (fields.get("priority") or {}).get("name", ""),
        "descricao": adf_to_text(fields.get("description")).strip(),
        "links_pull_requests": get_pull_request_links(issue, jira_headers, debug=debug),
    }


def load_authorization():
    """Build Jira Cloud Basic authentication from the email and API token."""
    # Load a local .env file without requiring the optional python-dotenv package.
    env_path = PROJECT_ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip().strip('"').strip("'")
            if name and name not in os.environ:
                os.environ[name] = value
    token = os.getenv("JIRA_API_TOKEN")
    if not token:
        raise RuntimeError("JIRA_API_TOKEN não encontrado no ambiente ou arquivo .env")
    email = os.getenv("JIRA_EMAIL")
    if not email:
        raise RuntimeError("JIRA_EMAIL não encontrado no ambiente ou arquivo .env")
    credentials = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
    return f"Basic {credentials}"


def fetch_issues(authorization, jql, debug=False):
    # Jira Cloud retired /search; /search/jql uses token-based pagination.
    headers = {"Authorization": authorization, "Accept": "application/json"}
    if debug:
        print(f"Consultando Jira com JQL: {jql}", file=sys.stderr)

    endpoint = f"{JIRA_BASE_URL}/rest/api/3/search/jql"
    issues = []
    page_number = 0
    response_total = None
    page_size = 100
    next_page_token = None

    while page_number < MAX_PAGES:
        query = {
            "jql": jql,
            "maxResults": page_size,
            "fields": ",".join(ISSUE_FIELDS),
        }
        if next_page_token:
            query["nextPageToken"] = next_page_token
        params = urllib.parse.urlencode(query)
        request = urllib.request.Request(
            f"{endpoint}?{params}",
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
        page = data.get("issues", [])
        page_number += 1
        response_total = data.get("total", response_total)
        if debug:
            sample_keys = [issue.get("key", "?") for issue in page[:10]]
            print(
                f"Jira page {page_number}: HTTP {response.status}; "
                f"issues={len(page)}; total={data.get('total', 'n/a')}; "
                f"has_next_page_token={bool(data.get('nextPageToken'))}; "
                f"keys={sample_keys}",
                file=sys.stderr,
            )
        issues.extend(page)
        next_page_token = data.get("nextPageToken")
        if not page or not next_page_token:
            break
    if page_number == MAX_PAGES and next_page_token and debug:
        print(f"Limite de {MAX_PAGES} páginas atingido; páginas seguintes ignoradas.", file=sys.stderr)
    issues = [issue for issue in issues if issue.get("key", "").startswith("S")]
    if not issues:
        print(
            f"Aviso: nenhuma issue retornada tem key começando com 'S' "
            f"para a consulta do filtro {FILTER_ID} "
            f"(páginas consultadas: {page_number}; total informado: {response_total}).",
            file=sys.stderr,
        )
    return issues


def save_issues(tasks, json_path, csv_path):
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(tasks, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8-sig", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=TASK_FIELDS)
        writer.writeheader()
        for task in tasks:
            row = {
                field: json.dumps(task[field], ensure_ascii=False)
                if isinstance(task[field], (dict, list))
                else task[field]
                for field in TASK_FIELDS
            }
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description="Exporta issues do filtro Jira 33221")
    parser.add_argument(
        "-o",
        "--output",
        "--json-output",
        dest="json_output",
        type=Path,
        default=PROJECT_ROOT / "kb-report-data" / "tasks" / "jira_tasks.json",
        help="Arquivo JSON normalizado de saída",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=PROJECT_ROOT / "kb-report-data" / "tasks" / "jira_tasks.csv",
        help="Arquivo CSV normalizado de saída",
    )
    parser.add_argument("--debug", action="store_true", help="Mostra status, paginação e chaves recebidas do Jira")
    parser.add_argument(
        "--jql",
        help="JQL da consulta; também pode ser definida pela variável JIRA_JQL",
    )
    args = parser.parse_args()

    try:
        authorization = load_authorization()
        jql = args.jql or os.getenv("JIRA_JQL") or f"filter = {FILTER_ID}"
        issues = fetch_issues(authorization, jql, debug=args.debug)
        jira_headers = {"Authorization": authorization, "Accept": "application/json"}
        tasks = [
            normalize_issue(
                issue,
                jira_headers,
                debug=args.debug,
            )
            for issue in issues
        ]
        save_issues(tasks, args.json_output, args.csv_output)
        print(f"{len(tasks)} tasks salvas em {args.json_output} e {args.csv_output}", file=sys.stderr)
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        try:
            error_data = json.loads(details)
            details = "; ".join(error_data.get("errorMessages", [])) or details
        except (json.JSONDecodeError, AttributeError):
            pass
        if exc.code == 404 and "filtro" in details.lower():
            details += (
                " Verifique se JIRA_EMAIL pertence à conta com acesso ao filtro, "
                "compartilhe o filtro com essa conta ou informe a JQL diretamente com --jql/JIRA_JQL."
            )
        parser.error(f"Jira respondeu HTTP {exc.code}: {details[:1000]}")
    except (urllib.error.URLError, RuntimeError) as exc:
        parser.error(str(exc))
    except OSError as exc:
        parser.error(f"Não foi possível salvar os arquivos: {exc}")


if __name__ == "__main__":
    main()