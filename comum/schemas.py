"""Pydantic schemas for every tracked CSV in the platform.

Each model's field order defines the canonical column order for its CSV. `comum.checks`
and the writer scripts import these models to validate rows before they are persisted.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Ambito = Literal["PT", "UE", "Mundo"]
Grau = Literal["A", "B", "C"]
NaturezaFonte = Literal["primaria", "secundaria", "noticia"]
EstadoFonte = Literal["testada", "excluida"]
TipoAfirmacao = Literal["dado", "facto", "evento", "ligacao"]
TipoQuebra = Literal["nivel", "declive", "pico"]
EstadoLigacao = Literal["ligado", "quebra_sem_evento", "evento_sem_efeito"]

TIPOS_EVENTO = [
    "lei_ou_decreto_lei",
    "orcamento_do_estado",
    "mudanca_de_governo",
    "eleicao",
    "diretiva_ou_regulamento_europeu",
    "programa_ou_plano_nacional",
    "crise_economica_ou_intervencao_externa",
    "pandemia_ou_crise_sanitaria",
    "catastrofe_natural_ou_climatica",
    "greve_ou_conflito_laboral",
    "evento_internacional_relevante",
]


class Evento(BaseModel):
    id: str
    data_inicio: date
    data_fim: date | None = None
    ambito: Ambito
    tipo: str
    titulo_pt: str
    titulo_en: str
    descricao_pt: str
    descricao_en: str
    fonte_primaria_url: str
    fonte_secundaria_url: str | None = None
    data_acesso: date
    temas: str  # semicolon-separated list
    verificado: Literal["sim", "nao"]


class FonteDados(BaseModel):
    id: str
    eixo: str
    nome: str
    organismo: str
    url: str
    formato: str
    licenca: str
    cobertura_temporal: str
    cobertura_geografica: str
    estado: EstadoFonte
    motivo_exclusao: str | None = None
    data_verificacao: date | None = None


class Quebra(BaseModel):
    id: str
    serie: str
    eixo: str
    data: date
    tipo: TipoQuebra
    magnitude: float
    metodo: str
    ic_inf: date | None = None
    ic_sup: date | None = None
    nota: str | None = None


class LigacaoEvento(BaseModel):
    id: str
    quebra_id: str | None = None
    evento_id: str | None = None
    estado: EstadoLigacao
    grau: Grau | None = None
    janela_justificacao: str
    justificacao_pt: str
    justificacao_en: str


class Afirmacao(BaseModel):
    id: str = Field(pattern=r"^c\d+$")
    tipo: TipoAfirmacao
    texto_pt: str
    texto_en: str
    valor: str | None = None
    unidade: str | None = None
    fonte_id: str
    url: str
    data_acesso: date
    excerto: str
    natureza_fonte: NaturezaFonte
    localizacao: str
    ficheiro_clean: str | None = None
    calculo: str | None = None
    grau: Grau | None = None
    estado_verificacao: Literal["pendente", "confirmada", "falhada"] = "pendente"


CSV_SCHEMAS: dict[str, type[BaseModel]] = {
    "eventos.csv": Evento,
    "fontes.csv": FonteDados,
    "quebras.csv": Quebra,
    "ligacoes_eventos.csv": LigacaoEvento,
    "afirmacoes.csv": Afirmacao,
}
