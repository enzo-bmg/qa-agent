"""Normalize Jira task exports into a compact, Portuguese JSON format."""

import argparse
import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_FILE = PROJECT_ROOT / "kb-report-data" / "tasks" / "jira_issues.json"
OUTPUT_FILE = PROJECT_ROOT / "kb-report-data" / "tasks" / "jira_tasks_final.json"

# Jira -> normalized task mapping:
# issue.key -> task_id; summary -> titulo; created -> dt_criacao;
# status.name -> status; issuetype.name -> tipo_task; priority.name -> prioridade;
# description -> descricao and explicitly labeled task details only.
# Jira execution-window/due-date fields are not requested by the current exporter.
SECTION_NAMES = {
    "alteracoes_tecnicas": {
        "alteracao tecnica", "alteracoes tecnicas", "detalhamento tecnico",
        "solucao tecnica", "solucao", "implementacao", "mudancas tecnicas",
    },
    "sistemas_relacionados": {
        "sistema", "sistemas", "sistemas relacionados", "sistemas afetados",
        "servicos afetados", "aplicacoes afetadas",
    },
    "repositorios": {"repositorio", "repositorios", "pull requests", "prs", "links de repositorio"},
    "plano_rollback": {"rollback", "plano de rollback", "plano de reversao", "reversao"},
    "riscos_identificados": {"risco", "riscos", "riscos identificados", "riscos e impactos"},
    "dependencias": {"dependencia", "dependencias", "riscos e dependencias"},
}
ALL_SECTION_NAMES = set().union(*SECTION_NAMES.values())
URL_PATTERN = re.compile(r"https?://[^\s<>\]\[)]+", re.IGNORECASE)
REPOSITORY_URL_PATTERN = re.compile(
    r"(?:/pull-?requests?/|/pulls?/|/merge[_-]?requests?/|/_git/|/repositories?/|/repos?/)",
    re.IGNORECASE,
)


def normalizar_texto(valor):
    if valor is None:
        return ""
    return str(valor).strip()


def converter_adf_para_texto(node):
    """Convert Jira Atlassian Document Format nodes to readable plain text."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(filter(None, (converter_adf_para_texto(item) for item in node)))
    if not isinstance(node, dict):
        return ""

    node_type = node.get("type")
    if node_type == "text":
        text = normalizar_texto(node.get("text"))
        link = next(
            (
                mark.get("attrs", {}).get("href")
                for mark in node.get("marks", [])
                if mark.get("type") == "link"
            ),
            None,
        )
        if link and link not in text:
            return f"{text} ({link})" if text else link
        return text
    if node_type == "hardBreak":
        return "\n"

    children = node.get("content", [])
    if node_type in {"bulletList", "orderedList"}:
        lines = []
        for index, item in enumerate(children, start=1):
            text = converter_adf_para_texto(item).strip()
            if text:
                prefix = "- " if node_type == "bulletList" else f"{index}. "
                lines.append(prefix + text.replace("\n", "\n  "))
        return "\n".join(lines)

    text = converter_adf_para_texto(children)
    if node_type in {"paragraph", "heading", "listItem", "blockquote", "codeBlock"}:
        return text.strip()
    return text


def extrair_descricao(issue):
    description = issue.get("fields", {}).get("description")
    return converter_adf_para_texto(description).strip()


def normalizar_nome_secao(line):
    value = line.strip().lstrip("#*- ").rstrip(": ").strip().lower()
    value = re.sub(r"\*\*|__|`", "", value)
    value = re.sub(r"\s+", " ", value)
    return value


def extrair_secoes(text):
    """Extract bodies under headings that explicitly name known task fields."""
    sections = {key: [] for key in SECTION_NAMES}
    current_section = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        heading = normalizar_nome_secao(stripped)
        heading_key = next(
            (key for key, names in SECTION_NAMES.items() if heading in names),
            None,
        )
        inline_match = re.match(r"^([^:]{2,80}):\s*(.*)$", stripped)
        if heading_key:
            current_section = heading_key
            continue
        if inline_match:
            inline_heading = normalizar_nome_secao(inline_match.group(1))
            inline_key = next(
                (key for key, names in SECTION_NAMES.items() if inline_heading in names),
                None,
            )
            if inline_key:
                current_section = inline_key
                if inline_match.group(2).strip():
                    sections[current_section].append(inline_match.group(2).strip())
                continue
            if inline_heading in ALL_SECTION_NAMES:
                current_section = None
                continue
            if stripped.endswith(":"):
                current_section = None
                continue
        if current_section:
            sections[current_section].append(stripped)

    return {
        key: "\n".join(lines).strip()
        for key, lines in sections.items()
        if lines
    }


def lista_unica_texto(value):
    if not value:
        return []
    parts = re.split(r"\n+|\s+[;•]\s*", value)
    return list(dict.fromkeys(part.strip(" -*\t") for part in parts if part.strip(" -*\t")))


def extrair_urls_repositorio(value):
    if isinstance(value, str):
        candidates = URL_PATTERN.findall(value)
    elif isinstance(value, dict):
        candidates = [
            url
            for child in value.values()
            for url in extrair_urls_repositorio(child)
        ]
    elif isinstance(value, list):
        candidates = [
            url
            for child in value
            for url in extrair_urls_repositorio(child)
        ]
    else:
        return []

    urls = []
    for candidate in candidates:
        url = candidate.rstrip(".,;:")
        if REPOSITORY_URL_PATTERN.search(url) and url not in urls:
            urls.append(url)
    return urls


def nomes_componentes(issue):
    components = issue.get("fields", {}).get("components") or []
    return list(dict.fromkeys(
        normalizar_texto(component.get("name"))
        for component in components
        if isinstance(component, dict) and normalizar_texto(component.get("name"))
    ))


def formatar_data_jira(value):
    value = normalizar_texto(value)
    return re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value)


def gerar_task(issue):
    fields = issue.get("fields") or {}
    description = extrair_descricao(issue)
    pull_request_links = extrair_urls_repositorio([
        fields,
        issue.get("links_pull_requests", []),
    ])

    return {
        "task_id": normalizar_texto(issue.get("key")),
        "titulo": normalizar_texto(fields.get("summary")),
        "tipo_task": normalizar_texto((fields.get("issuetype") or {}).get("name")),
        "prioridade": normalizar_texto((fields.get("priority") or {}).get("name")),
        "descricao": description,
        "links_pull_requests": pull_request_links,
    }


def carregar_tasks(path):
    with path.open("r", encoding="utf-8") as input_file:
        issues = json.load(input_file)
    if not isinstance(issues, list):
        raise ValueError("O JSON de entrada deve conter uma lista de issues Jira.")

    tasks = []
    seen_ids = set()
    skipped = 0
    for issue in issues:
        if not isinstance(issue, dict) or not normalizar_texto(issue.get("key")):
            skipped += 1
            continue
        task = gerar_task(issue)
        if task["task_id"] in seen_ids:
            continue
        seen_ids.add(task["task_id"])
        tasks.append(task)
    return tasks, skipped


def salvar_json(tasks, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output_file:
        json.dump(tasks, output_file, ensure_ascii=False, indent=4)
        output_file.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Limpa e estrutura o export JSON de tasks do Jira.")
    parser.add_argument("-i", "--input", type=Path, default=INPUT_FILE, help="JSON bruto exportado do Jira")
    parser.add_argument("-o", "--output", type=Path, default=OUTPUT_FILE, help="JSON normalizado de saída")
    args = parser.parse_args()

    tasks, skipped = carregar_tasks(args.input)
    salvar_json(tasks, args.output)
    print(f"Tasks processadas: {len(tasks)}")
    print(f"Issues ignoradas sem chave válida: {skipped}")
    print(f"Arquivo gerado: {args.output}")


if __name__ == "__main__":
    main()