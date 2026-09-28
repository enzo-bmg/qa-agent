import pandas as pd
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
GMUDS_FILE = PROJECT_ROOT / "kb-report-data" / "gmuds" / "gmuds.csv"
TASKS_FILE = PROJECT_ROOT / "kb-report-data" / "gmuds" / "tasks.csv"
OUTPUT_FILE = PROJECT_ROOT / "kb-report-data" / "gmuds" / "gmuds_final.json"

def limpar_texto(valor):
    if pd.isna(valor):
        return ""

    return str(valor).strip()


def lista_unica(series):
    resultado = []

    for item in series:
        item = limpar_texto(item)

        if item and item not in resultado:
            resultado.append(item)

    return resultado


def obter_primeiro_valor(grupo, coluna):
    valores = grupo[coluna].dropna().astype(str)

    for valor in valores:
        valor = valor.strip()

        if valor:
            return valor

    return ""


def carregar_gmuds():
    df = pd.read_csv(
        GMUDS_FILE,
        sep=";",
        encoding="cp1252",
        dtype=str,
        keep_default_na=False
    )
    total_original = len(df)

    # Remove SOMENTE linhas totalmente duplicadas
    df = df.drop_duplicates()

    print(
        f"GMUDs -> Original: {total_original} | "
        f"Após limpeza: {len(df)}"
    )

    return df


def carregar_tasks():
    return pd.read_csv(
        TASKS_FILE,
        sep=";",
        encoding="cp1252",
        dtype=str,
        keep_default_na=False
    )


def gerar_json(gmuds_df, tasks_df):

    resultado = []

    tasks_df["Mudança associada ID ID"] = (
        tasks_df["Mudança associada ID ID"]
        .astype(str)
        .str.strip()
    )

    for gmud_id, grupo in gmuds_df.groupby("ID"):

        linha = grupo.iloc[0]

        ativos = lista_unica(
            grupo["Ativos Associados Nome do Ativo"]
        )

        tasks_relacionadas = tasks_df[
            tasks_df["Mudança associada ID ID"] == gmud_id
        ]

        rollbacks = lista_unica(
            tasks_relacionadas[
                "Informações de rollback - (Caso não haja informe o motivo - Evite usar 'não se aplica')"
            ]
        )

        gmud_json = {
            "gmud_id": limpar_texto(
                linha["ID"]
            ),

            "titulo": limpar_texto(
                linha["Assunto"]
            ),

            "dt_criacao": limpar_texto(
                linha["Data de criação"]
            ),

            "janela_execucao": {
                "inicio": limpar_texto(
                    linha["Data de Início Planejada"]
                ),
                "fim": limpar_texto(
                    linha["Data de Término Planejada"]
                )
            },

            "status": limpar_texto(
                linha["Execução da Mudança"]
            ),

            "tipo_mudanca": limpar_texto(
                linha["Tipo de Mudança"]
            ),

            "sistemas_afetados": ativos,

            "descricao": limpar_texto(
                linha["Descrição"]
            ),

            # POR ENQUANTO
            "alteracoes_tecnicas": limpar_texto(
                linha["Descrição"]
            ),

            # POR ENQUANTO
            "repositorios": ativos,

            "plano_rollback": rollbacks,

            "riscos_identificados": limpar_texto(
                linha["Risco"]
            )
        }

        resultado.append(gmud_json)

    return resultado


def salvar_json(dados):

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            dados,
            f,
            ensure_ascii=False,
            indent=4
        )

    print(
        f"Arquivo gerado: {OUTPUT_FILE}"
    )


if __name__ == "__main__":

    gmuds_df = carregar_gmuds()

    tasks_df = carregar_tasks()

    gmuds_json = gerar_json(
        gmuds_df,
        tasks_df
    )

    salvar_json(gmuds_json)

    print(
        f"Total de GMUDs processadas: {len(gmuds_json)}"
    )