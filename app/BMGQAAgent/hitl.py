"""
HITL (Human-in-the-Loop) do QA Agent BMG.

Fluxo:
1. Agente gera cenários de teste
2. Apresenta ao QA analyst para revisão
3. QA pode: aprovar / rejeitar / editar / pedir mais cenários
4. Agente ajusta se necessário
5. Cenários finalizados

No MVP: interação via CLI/API (sem portal web).
Em produção: portal Cognito + WebSocket.
"""

import json
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


class ReviewAction(Enum):
    APPROVE = "aprovar"
    REJECT = "rejeitar"
    EDIT = "editar"
    REQUEST_MORE = "mais_cenarios"
    APPROVE_PARTIAL = "aprovar_parcial"


@dataclass
class ReviewComment:
    cenario_id: str
    acao: ReviewAction
    comentario: str
    sugestao: Optional[str] = None


@dataclass
class HITLSession:
    """Sessão de revisão HITL entre agente e QA analyst."""
    
    gmud_id: str
    cenarios: dict  # Output do SubAgent Test Scenarios Gen
    status: str = "pendente_revisao"  # pendente_revisao | em_revisao | aprovado | rejeitado | ajustando
    reviews: list = field(default_factory=list)
    historico: list = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def apresentar_para_revisao(self) -> str:
        """Formata os cenários para apresentação ao QA analyst."""
        output = []
        output.append(f"═══════════════════════════════════════════════════════════")
        output.append(f"  GMUD: {self.gmud_id} — Cenários de Teste para Revisão")
        output.append(f"  Nível de risco: {self.cenarios.get('nivel_risco', 'N/A')}")
        output.append(f"  Total de cenários: {self.cenarios.get('total_cenarios', 'N/A')}")
        output.append(f"═══════════════════════════════════════════════════════════")
        output.append("")
        
        for ct in self.cenarios.get("cenarios", []):
            output.append(f"┌─ {ct.get('id', '?')} [{ct.get('prioridade', '?')}] {ct.get('tipo', '?')}")
            output.append(f"│  {ct.get('titulo', '?')}")
            output.append(f"│")
            output.append(f"│  Pré-condições:")
            for pre in ct.get("pre_condicoes", []):
                output.append(f"│    • {pre}")
            output.append(f"│")
            output.append(f"│  Passos:")
            for passo in ct.get("passos", []):
                output.append(f"│    {passo.get('numero', '?')}. {passo.get('acao', '?')}")
                if passo.get("dados"):
                    output.append(f"│       Dados: {passo['dados']}")
            output.append(f"│")
            output.append(f"│  Resultado esperado: {ct.get('resultado_esperado', '?')}")
            output.append(f"│  Critério de rollback: {ct.get('criterio_rollback', '?')}")
            output.append(f"│  Baseado em: {ct.get('baseado_em', '?')}")
            output.append(f"└──────────────────────────────────────────────────────")
            output.append("")
        
        # Recomendações
        recs = self.cenarios.get("recomendacoes_adicionais", [])
        if recs:
            output.append("📋 Recomendações adicionais:")
            for rec in recs:
                output.append(f"   • {rec}")
            output.append("")
        
        output.append("═══════════════════════════════════════════════════════════")
        output.append("  Ações disponíveis:")
        output.append("    [A] Aprovar todos os cenários")
        output.append("    [R] Rejeitar — pedir regeneração completa")
        output.append("    [E] Editar — marcar cenários específicos para ajuste")
        output.append("    [M] Mais cenários — pedir cenários adicionais")
        output.append("    [P] Aprovar parcial — aprovar alguns, rejeitar outros")
        output.append("═══════════════════════════════════════════════════════════")
        
        return "\n".join(output)
    
    def registrar_review(self, acao: ReviewAction, comentarios: list[ReviewComment] = None, nota_geral: str = ""):
        """Registra a decisão do QA analyst."""
        review = {
            "timestamp": datetime.now().isoformat(),
            "acao": acao.value,
            "nota_geral": nota_geral,
            "comentarios_por_cenario": [
                {
                    "cenario_id": c.cenario_id,
                    "acao": c.acao.value,
                    "comentario": c.comentario,
                    "sugestao": c.sugestao,
                }
                for c in (comentarios or [])
            ]
        }
        self.reviews.append(review)
        self.historico.append(f"[{review['timestamp']}] QA: {acao.value} — {nota_geral}")
        
        # Atualizar status
        if acao == ReviewAction.APPROVE:
            self.status = "aprovado"
        elif acao == ReviewAction.REJECT:
            self.status = "rejeitado"
        elif acao in (ReviewAction.EDIT, ReviewAction.REQUEST_MORE):
            self.status = "ajustando"
        elif acao == ReviewAction.APPROVE_PARTIAL:
            self.status = "aprovado_parcial"
        
        return review
    
    def get_cenarios_para_ajuste(self) -> list[dict]:
        """Retorna cenários que foram marcados para edição na última review."""
        if not self.reviews:
            return []
        
        last_review = self.reviews[-1]
        ajustar = []
        for comment in last_review.get("comentarios_por_cenario", []):
            if comment["acao"] in ("editar", "rejeitar"):
                ajustar.append({
                    "cenario_id": comment["cenario_id"],
                    "comentario": comment["comentario"],
                    "sugestao": comment["sugestao"],
                })
        return ajustar
    
    def gerar_prompt_ajuste(self) -> str:
        """Gera prompt para o agente ajustar cenários baseado no feedback."""
        ajustes = self.get_cenarios_para_ajuste()
        if not ajustes:
            last_review = self.reviews[-1] if self.reviews else {}
            nota = last_review.get("nota_geral", "")
            return f"O QA analyst pediu ajustes gerais: {nota}\nRegere os cenários considerando esse feedback."
        
        prompt_parts = ["O QA analyst revisou os cenários e pediu os seguintes ajustes:\n"]
        for ajuste in ajustes:
            prompt_parts.append(f"- {ajuste['cenario_id']}: {ajuste['comentario']}")
            if ajuste.get("sugestao"):
                prompt_parts.append(f"  Sugestão: {ajuste['sugestao']}")
        
        prompt_parts.append("\nAjuste os cenários indicados mantendo os demais inalterados.")
        return "\n".join(prompt_parts)
    
    def to_dict(self) -> dict:
        """Serializa sessão para persistência."""
        return {
            "gmud_id": self.gmud_id,
            "status": self.status,
            "cenarios": self.cenarios,
            "reviews": self.reviews,
            "historico": self.historico,
            "created_at": self.created_at,
        }
    
    def resumo(self) -> str:
        """Resumo rápido do estado da sessão."""
        return (
            f"GMUD: {self.gmud_id} | Status: {self.status} | "
            f"Cenários: {self.cenarios.get('total_cenarios', '?')} | "
            f"Reviews: {len(self.reviews)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Simulação de interação HITL (pra teste local)
# ─────────────────────────────────────────────────────────────────────────────

def simulate_hitl_flow(gmud_id: str, cenarios: dict) -> HITLSession:
    """Simula um fluxo HITL completo (pra teste sem interação real)."""
    
    session = HITLSession(gmud_id=gmud_id, cenarios=cenarios)
    
    # Simula apresentação
    print(session.apresentar_para_revisao())
    
    # Simula review parcial (aprova maioria, pede ajuste em 1)
    comments = []
    cenarios_list = cenarios.get("cenarios", [])
    
    if len(cenarios_list) > 2:
        # Rejeita o último cenário como exemplo
        comments.append(ReviewComment(
            cenario_id=cenarios_list[-1].get("id", "CT-???"),
            acao=ReviewAction.EDIT,
            comentario="Cenário muito genérico, precisa de passos mais específicos",
            sugestao="Adicionar dados concretos nos passos (payload exato, endpoint, timeout esperado)"
        ))
    
    session.registrar_review(
        acao=ReviewAction.APPROVE_PARTIAL,
        comentarios=comments,
        nota_geral="Maioria dos cenários está boa. Ajustar o último — muito genérico."
    )
    
    print(f"\n📝 Review registrada: {session.resumo()}")
    
    if session.status == "ajustando":
        print(f"\n🔄 Prompt para ajuste:")
        print(f"   {session.gerar_prompt_ajuste()}")
    
    return session
