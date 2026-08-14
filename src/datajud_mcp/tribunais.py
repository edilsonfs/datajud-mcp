"""Catálogo dos 91 tribunais cobertos pela API Pública DataJud.

Cada tribunal reúne três informações que o resto do pacote precisa:

- ``alias``: o índice Elasticsearch usado na URL da API.
- ``segmento`` e ``codigo_tr``: os dígitos ``J`` e ``TR`` do número CNJ
  (``NNNNNNN-DD.AAAA.J.TR.OOOO``), que permitem descobrir o tribunal a
  partir do número do processo.
- ``nome``: nome por extenso, para o usuário final.

Todos os aliases foram validados contra a API real (91/91 respondendo
HTTP 200) e todos os pares ``J.TR`` foram conferidos contra números de
processo devolvidos pela própria API.

Atenção ao ponto que mais gera erro: os aliases da Justiça Eleitoral
usam hífen (``api_publica_tre-pe``), ao contrário de todos os demais
segmentos (``api_publica_tjpe``, ``api_publica_trt6``).
"""

from __future__ import annotations

from typing import NamedTuple


class Tribunal(NamedTuple):
    """Um tribunal coberto pela API DataJud."""

    sigla: str
    alias: str
    nome: str
    justica: str
    segmento: int
    codigo_tr: int


# Ordem oficial do CNJ para o dígito TR da Justiça Estadual e Eleitoral.
# Confirmada empiricamente: TJMG = 8.13, TJPE = 8.17, TJSP = 8.26.
UFS: dict[str, tuple[int, str]] = {
    "AC": (1, "Acre"),
    "AL": (2, "Alagoas"),
    "AP": (3, "Amapá"),
    "AM": (4, "Amazonas"),
    "BA": (5, "Bahia"),
    "CE": (6, "Ceará"),
    "DF": (7, "Distrito Federal"),
    "ES": (8, "Espírito Santo"),
    "GO": (9, "Goiás"),
    "MA": (10, "Maranhão"),
    "MT": (11, "Mato Grosso"),
    "MS": (12, "Mato Grosso do Sul"),
    "MG": (13, "Minas Gerais"),
    "PA": (14, "Pará"),
    "PB": (15, "Paraíba"),
    "PR": (16, "Paraná"),
    "PE": (17, "Pernambuco"),
    "PI": (18, "Piauí"),
    "RJ": (19, "Rio de Janeiro"),
    "RN": (20, "Rio Grande do Norte"),
    "RS": (21, "Rio Grande do Sul"),
    "RO": (22, "Rondônia"),
    "RR": (23, "Roraima"),
    "SC": (24, "Santa Catarina"),
    "SE": (25, "Sergipe"),
    "SP": (26, "São Paulo"),
    "TO": (27, "Tocantins"),
}

# Regiões da Justiça do Trabalho (TRT), por número.
REGIOES_TRT: dict[int, str] = {
    1: "Rio de Janeiro", 2: "São Paulo (capital)", 3: "Minas Gerais",
    4: "Rio Grande do Sul", 5: "Bahia", 6: "Pernambuco", 7: "Ceará",
    8: "Pará e Amapá", 9: "Paraná", 10: "Distrito Federal e Tocantins",
    11: "Amazonas e Roraima", 12: "Santa Catarina",
    13: "Paraíba", 14: "Rondônia e Acre", 15: "Campinas — SP interior",
    16: "Maranhão", 17: "Espírito Santo", 18: "Goiás", 19: "Alagoas",
    20: "Sergipe", 21: "Rio Grande do Norte", 22: "Piauí",
    23: "Mato Grosso", 24: "Mato Grosso do Sul",
}

# Abrangência dos Tribunais Regionais Federais.
REGIOES_TRF: dict[int, str] = {
    1: "DF, AC, AM, AP, BA, GO, MA, MT, PA, PI, RO, RR e TO",
    2: "Rio de Janeiro e Espírito Santo",
    3: "São Paulo e Mato Grosso do Sul",
    4: "Rio Grande do Sul, Santa Catarina e Paraná",
    5: "Pernambuco, Alagoas, Ceará, Paraíba, Rio Grande do Norte e Sergipe",
    6: "Minas Gerais",
}


def _montar() -> dict[str, Tribunal]:
    t: dict[str, Tribunal] = {}

    # Tribunais superiores. O segmento identifica o ramo de Justiça;
    # TR = 00 porque são de âmbito nacional.
    t["STJ"] = Tribunal(
        "STJ", "api_publica_stj", "Superior Tribunal de Justiça",
        "Tribunal Superior", 3, 0,
    )
    t["TST"] = Tribunal(
        "TST", "api_publica_tst", "Tribunal Superior do Trabalho",
        "Tribunal Superior", 5, 0,
    )
    t["TSE"] = Tribunal(
        "TSE", "api_publica_tse", "Tribunal Superior Eleitoral",
        "Tribunal Superior", 6, 0,
    )
    t["STM"] = Tribunal(
        "STM", "api_publica_stm", "Superior Tribunal Militar",
        "Tribunal Superior", 7, 0,
    )

    # Justiça Federal.
    for n, abrangencia in REGIOES_TRF.items():
        t[f"TRF{n}"] = Tribunal(
            f"TRF{n}", f"api_publica_trf{n}",
            f"Tribunal Regional Federal da {n}ª Região ({abrangencia})",
            "Justiça Federal", 4, n,
        )

    # Justiça Estadual. O DF tem sigla própria (TJDFT).
    for uf, (codigo, nome_uf) in UFS.items():
        if uf == "DF":
            t["TJDFT"] = Tribunal(
                "TJDFT", "api_publica_tjdft",
                "Tribunal de Justiça do Distrito Federal e dos Territórios",
                "Justiça Estadual", 8, codigo,
            )
        else:
            t[f"TJ{uf}"] = Tribunal(
                f"TJ{uf}", f"api_publica_tj{uf.lower()}",
                f"Tribunal de Justiça de {nome_uf}",
                "Justiça Estadual", 8, codigo,
            )

    # Justiça do Trabalho.
    for n, abrangencia in REGIOES_TRT.items():
        t[f"TRT{n}"] = Tribunal(
            f"TRT{n}", f"api_publica_trt{n}",
            f"Tribunal Regional do Trabalho da {n}ª Região ({abrangencia})",
            "Justiça do Trabalho", 5, n,
        )

    # Justiça Eleitoral — atenção ao hífen no alias.
    for uf, (codigo, nome_uf) in UFS.items():
        t[f"TRE{uf}"] = Tribunal(
            f"TRE{uf}", f"api_publica_tre-{uf.lower()}",
            f"Tribunal Regional Eleitoral de {nome_uf}",
            "Justiça Eleitoral", 6, codigo,
        )

    # Justiça Militar Estadual.
    for uf in ("MG", "RS", "SP"):
        codigo, nome_uf = UFS[uf]
        t[f"TJM{uf}"] = Tribunal(
            f"TJM{uf}", f"api_publica_tjm{uf.lower()}",
            f"Tribunal de Justiça Militar de {nome_uf}",
            "Justiça Militar Estadual", 9, codigo,
        )

    return t


TRIBUNAIS: dict[str, Tribunal] = _montar()

# Índice reverso (segmento, código TR) -> siglas, para descobrir o
# tribunal a partir do número CNJ. É uma lista porque há colisões
# legítimas: 4.01 devolve TRF1 e TRF6, já que o TRF6 foi desmembrado do
# TRF1 em 2022 e herdou o acervo de Minas Gerais.
_POR_SEGMENTO: dict[tuple[int, int], list[str]] = {}
for _sigla, _trib in TRIBUNAIS.items():
    _POR_SEGMENTO.setdefault((_trib.segmento, _trib.codigo_tr), []).append(_sigla)
_POR_SEGMENTO[(4, 1)].append("TRF6")

# Ramos de Justiça que o número CNJ pode indicar, incluindo os dois que
# a API DataJud não cobre (STF e CNJ).
SEGMENTOS: dict[int, str] = {
    1: "Supremo Tribunal Federal",
    2: "Conselho Nacional de Justiça",
    3: "Superior Tribunal de Justiça",
    4: "Justiça Federal",
    5: "Justiça do Trabalho",
    6: "Justiça Eleitoral",
    7: "Justiça Militar da União",
    8: "Justiça Estadual",
    9: "Justiça Militar Estadual",
}


def normalizar(sigla: str) -> str:
    """Normaliza uma sigla informada pelo usuário.

    Aceita variações comuns: minúsculas, espaços, hífens e as grafias
    ``TJDF``/``TRE-PE``/``TRT 6``.
    """
    s = sigla.upper().strip().replace("-", "").replace(" ", "").replace(".", "")
    if s in ("TJDF", "TJDFTT"):
        return "TJDFT"
    if s == "TREDFT":
        return "TREDF"
    return s


def obter(sigla: str) -> Tribunal | None:
    """Devolve o tribunal pela sigla, ou ``None`` se não existir."""
    return TRIBUNAIS.get(normalizar(sigla))


def alias_de(sigla: str) -> str | None:
    """Devolve o alias Elasticsearch da sigla, ou ``None``."""
    trib = obter(sigla)
    return trib.alias if trib else None


def por_segmento(segmento: int, codigo_tr: int) -> list[str]:
    """Devolve as siglas que correspondem a um par ``J.TR`` do número CNJ."""
    return list(_POR_SEGMENTO.get((segmento, codigo_tr), []))


def buscar(termo: str) -> list[Tribunal]:
    """Busca tribunais por sigla, nome, UF ou ramo de Justiça."""
    t = termo.strip().lower()
    if not t:
        return list(TRIBUNAIS.values())
    return [
        trib for trib in TRIBUNAIS.values()
        if t in trib.sigla.lower()
        or t in trib.nome.lower()
        or t in trib.justica.lower()
    ]
