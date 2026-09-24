"""
Lambda mock: get_code_diff
Retorna o diff/arquivos alterados de uma mudança, dado o nome do repositório.

A ponte GMUD -> código é feita pelo nome do repo (campo "Ativos Associados"
da GMUD, ex: "bmg.consig.mais.front"), não por link direto de PR.

MODO LOCAL (atual): lê diffs de uma pasta local (code-diffs-test/<repo>/),
para exercitar o Nível 2 (análise de código real) sem depender de acesso à
API do Azure DevOps.

MODO API (futuro): quando o acesso aos repos sair, troca a leitura local por
chamadas à REST API do Azure DevOps. O gancho está comentado no fim do arquivo.
"""

import json
import os
from pathlib import Path

# Pasta onde ficam os diffs locais (organizados por nome de repo).
# Estrutura esperada:
#   code-diffs-test/
#     bmg.consig.mais.front/
#       CHN-11710.diff        (ou .txt com o diff)
#       CHN-11710.meta.json   (opcional: título, branches, autor)
PROJECT_ROOT = Path(__file__).parent.parent.parent
CODE_DIFFS_DIR = Path(
    os.getenv("CODE_DIFFS_DIR", str(PROJECT_ROOT / "code-diffs-test"))
)

# Limite de tamanho do diff retornado (evita estourar contexto do LLM).
MAX_DIFF_CHARS = int(os.getenv("MAX_DIFF_CHARS", "20000"))


def _find_diff_file(repo_dir: Path, change_id: str | None):
    """Localiza o arquivo de diff dentro da pasta do repo.

    Se change_id for informado, procura por ele. Senão, pega o primeiro
    arquivo .diff/.txt encontrado.
    """
    if not repo_dir.is_dir():
        return None

    candidates = sorted(
        [p for p in repo_dir.iterdir() if p.suffix in (".diff", ".txt")]
    )
    if not candidates:
        return None

    if change_id:
        for p in candidates:
            if change_id.lower() in p.stem.lower():
                return p
        return None  # pediu um change_id específico e não achou

    return candidates[0]


def _load_meta(diff_path: Path) -> dict:
    """Carrega metadados opcionais (<stem>.meta.json) ao lado do diff."""
    meta_path = diff_path.with_suffix(".meta.json")
    if meta_path.is_file():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _get_diff_local(repo: str, change_id: str | None) -> dict:
    """Lê o diff da pasta local."""
    repo_dir = CODE_DIFFS_DIR / repo
    diff_path = _find_diff_file(repo_dir, change_id)

    if diff_path is None:
        repos_disponiveis = (
            [p.name for p in CODE_DIFFS_DIR.iterdir() if p.is_dir()]
            if CODE_DIFFS_DIR.is_dir() else []
        )
        return {
            "encontrado": False,
            "repo": repo,
            "change_id": change_id,
            "mensagem": (
                f"Nenhum diff local encontrado para o repo '{repo}'"
                + (f" e mudança '{change_id}'" if change_id else "")
                + ". Coloque o diff em "
                f"{CODE_DIFFS_DIR}/<repo>/<change_id>.diff"
            ),
            "repos_disponiveis": repos_disponiveis,
        }

    diff_text = diff_path.read_text(encoding="utf-8", errors="replace")
    truncated = len(diff_text) > MAX_DIFF_CHARS
    if truncated:
        diff_text = diff_text[:MAX_DIFF_CHARS] + "\n... [diff truncado]"

    meta = _load_meta(diff_path)

    return {
        "encontrado": True,
        "repo": repo,
        "change_id": change_id or diff_path.stem,
        "fonte": "local",
        "arquivo": diff_path.name,
        "truncado": truncated,
        "metadata": meta,
        "diff": diff_text,
    }


def lambda_handler(event, context):
    """Handler principal da Lambda."""

    if isinstance(event, str):
        event = json.loads(event)

    body = event.get("body", event)
    if isinstance(body, str):
        body = json.loads(body)

    # "repo" vem do campo Ativos Associados da GMUD (ex: bmg.consig.mais.front)
    repo = body.get("repo") or body.get("ativo")
    # change_id opcional: ID da GMUD/PR para localizar o diff certo
    change_id = body.get("change_id") or body.get("gmud_id") or body.get("pr_id")

    if not repo:
        return {
            "statusCode": 400,
            "body": json.dumps(
                {"error": "repo é obrigatório (nome do repositório / Ativo Associado)"}
            ),
        }

    result = _get_diff_local(repo, change_id)
    status = 200 if result.get("encontrado") else 404

    return {
        "statusCode": status,
        "body": json.dumps(result, ensure_ascii=False),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GANCHO — modo API Azure DevOps (habilitar quando o acesso aos repos sair)
# ─────────────────────────────────────────────────────────────────────────────
# Docs:
#   https://learn.microsoft.com/en-us/rest/api/azure/devops/git/pull-requests/get-pull-request?view=azure-devops-rest-7.1
#   https://learn.microsoft.com/en-us/rest/api/azure/devops/git/diffs/get?view=azure-devops-rest-7.1
#
# import base64, requests
#
# def _get_diff_azure(repo: str, pr_id: str) -> dict:
#     org = os.environ["AZDO_ORG"]
#     project = os.environ["AZDO_PROJECT"]
#     pat = os.environ["AZDO_PAT"]            # escopo Code: Read
#     token = base64.b64encode(f":{pat}".encode()).decode()
#     headers = {"Authorization": f"Basic {token}"}
#     base = f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}"
#     # 1) metadados do PR
#     pr = requests.get(f"{base}/pullrequests/{pr_id}?api-version=7.1", headers=headers).json()
#     # 2) commits/iterations -> base e target
#     # 3) diff entre commits (.../diffs/commits?baseVersion=...&targetVersion=...)
#     # 4) montar o mesmo shape do _get_diff_local (encontrado/repo/change_id/diff/...)
#     ...


# Para teste local
if __name__ == "__main__":
    test_event = {"repo": "bmg.consig.mais.front", "change_id": "CHN-11710"}
    result = lambda_handler(test_event, None)
    print(json.dumps(json.loads(result["body"]), indent=2, ensure_ascii=False))
