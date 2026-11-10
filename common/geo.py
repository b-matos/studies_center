"""Portuguese geography harmonization: NUTS II/III names and codes.

Full canonical lists (NUTS 2024, municípios) should be added to NUTS2_POR as each study
needs them; this starter covers NUTS II, the level the saude-portugal study plans to use.
"""
from __future__ import annotations

NUTS2_POR: dict[str, str] = {
    "PT11": "Norte",
    "PT15": "Algarve",
    "PT16": "Centro",
    "PT17": "Área Metropolitana de Lisboa",
    "PT18": "Alentejo",
    "PT19": "Região Autónoma dos Açores",
    "PT1A": "Região Autónoma da Madeira",
}

NUTS2_EN: dict[str, str] = {
    "PT11": "Norte",
    "PT15": "Algarve",
    "PT16": "Centro",
    "PT17": "Lisbon Metropolitan Area",
    "PT18": "Alentejo",
    "PT19": "Autonomous Region of the Azores",
    "PT1A": "Autonomous Region of Madeira",
}

SEX_CANONICAL = {
    "homens": "M",
    "homem": "M",
    "masculino": "M",
    "male": "M",
    "m": "M",
    "mulheres": "F",
    "mulher": "F",
    "feminino": "F",
    "female": "F",
    "f": "F",
    "total": "T",
    "ambos": "T",
    "t": "T",
}


def canonical_sex(value: str) -> str:
    key = value.strip().lower()
    if key not in SEX_CANONICAL:
        raise ValueError(f"unrecognized sex value: {value!r}")
    return SEX_CANONICAL[key]


def nuts2_name(code: str, lang: str = "pt") -> str:
    table = NUTS2_POR if lang == "pt" else NUTS2_EN
    if code not in table:
        raise ValueError(f"unknown NUTS II code: {code!r}")
    return table[code]
