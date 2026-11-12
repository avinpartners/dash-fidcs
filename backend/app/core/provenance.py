"""Provenance of displayed numbers (design 4.3).

JSON shape everywhere: {"source", "label", "ref", "ref_kind", "url", "note"}.
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

# Same labels as sources.label_pt seeded in db/migrations/0002_phase1.sql and 0003_ingest_fixes.sql.
SOURCE_LABELS: dict[str, str] = {
    "cvm_inf_mensal": "CVM – Informe Mensal",
    "cvm_inf_trimestral": "CVM – Informe Trimestral",
    "cvm_inf_anual": "CVM – Informe Anual",
    "b3_cotahist": "B3 – Cotações Históricas (COTAHIST)",
    "fnet": "B3 – FundosNET",
    "b3_proventos": "B3 – Proventos (fundos listados)",
    "cvm_inf_mensal_cri": "CVM – Informe Mensal de CRI (securitizadoras)",
    "cvm_inf_mensal_cra": "CVM – Informe Mensal de CRA (securitizadoras)",
    "cvm_inf_mensal_fiagro": "CVM – Informe Mensal de Fiagro",
    "relatorio_gerencial": "Relatório gerencial do fundo",
    "bcb_sgs": "Banco Central – SGS",
    "tesouro_direto": "Tesouro Direto – Preços e Taxas",
    "computed": "Calculado pelo Dash FIDCs",
    "manual": "Inserido manualmente",
    "municipios": "IBGE – Municípios (coordenadas: kelvins/municipios-brasileiros)",
    "nominatim": "OpenStreetMap – Nominatim",
    "receita_cnpj": "Receita Federal – cadastro de CNPJ",
    "cvm_ofertas": "CVM – Ofertas públicas",
    "anbima_snd": "ANBIMA – SND (debêntures registradas)",
    "cvm_cda": "CVM – Composição da carteira dos fundos (CDA)",
    "cvm_inf_diario": "CVM – Informe diário dos fundos",
    "cvm_cad_fi": "CVM – Cadastro de fundos (classes)",
    "cvm_inf_mensal_fidc": "CVM – Informe Mensal FIDC",
    "cvm_cad_fidc": "CVM – Cadastro de fundos e classes",
}

FNET_DOCUMENT_URL = "https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento?id={id}"


def source_label(source_id: str) -> str:
    """pt-BR label for a source id; unknown ids are returned unchanged."""
    return SOURCE_LABELS.get(source_id, source_id)


def _iso(ref: date | datetime | str | None) -> str | None:
    if ref is None:
        return None
    if isinstance(ref, datetime):
        return ref.date().isoformat()
    if isinstance(ref, date):
        return ref.isoformat()
    return str(ref)


@dataclass(frozen=True)
class Prov:
    source: str
    ref: date | datetime | str | None = None
    ref_kind: str = "date"            # 'month' (ref = first day of month) | 'date'
    url: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "label": source_label(self.source),
            "ref": _iso(self.ref),
            "ref_kind": self.ref_kind,
            "url": self.url,
            "note": self.note,
        }


def prov(source: str, ref: date | datetime | str | None = None, *, ref_kind: str = "date",
         url: str | None = None, note: str | None = None) -> dict[str, Any]:
    """Shortcut: prov('cvm_inf_mensal', date(2026, 8, 1), ref_kind='month') -> JSON dict."""
    return Prov(source, ref, ref_kind, url, note).to_dict()


def fnet_document_url(fnet_id: int | str) -> str:
    return FNET_DOCUMENT_URL.format(id=fnet_id)
