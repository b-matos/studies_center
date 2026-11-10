"""Axis saude-mental: question 8 (suicide, depressive symptoms).

Antidepressant consumption (OCDE/INFARMED) and hlth_ehis_mh are not in the loaded data, so only
suicide mortality (INE) and depressive symptoms (INS waves 2014, 2019, 2025) are analysed.
Suicide: ih10 (NUTS 2013, 2002-2022) and ih09 (NUTS 2024, 2023-2024) are two INE tables; the
national series is spliced at 2023 and the splice is flagged in the break note.
"""
from __future__ import annotations

import pandas as pd

from _lib import export, find_breaks, load, reset_breaks

AXIS = "saude-mental"
reset_breaks(AXIS)

old, new = load("ih10"), load("ih09")
old = old[old.region.isin(["Portugal", "Norte", "Centro", "Área Metropolitana de Lisboa", "Alentejo", "Algarve",
                           "Região Autónoma dos Açores", "Região Autónoma da Madeira"])]
new = new[new.region.isin(["Portugal", "Norte", "Centro", "Grande Lisboa", "Península de Setúbal", "Oeste e Vale do Tejo",
                           "Alentejo", "Algarve", "Região Autónoma dos Açores", "Região Autónoma da Madeira"])]
sui = pd.concat([old.assign(classification="NUTS2013"), new.assign(classification="NUTS2024")])
sui = sui[sui.indicator.str.startswith("suicide_mortality_rate") & ~sui.indicator.str.contains(r"\|")].copy()
sui["indicator"] = "suicide_rate"
sui["age"] = sui["age"].replace("", "all_ages")
export(sui, "q08_suicide", AXIS,
       "Taxa de mortalidade por suicídio por 100 000 hab., por região, sexo e idade (INE, 2002-2024)",
       "Suicide mortality rate per 100,000, by region, sex and age (INE, 2002-2024)")
pt = sui[(sui.region == "Portugal") & (sui.age == "all_ages")]
hm = pt[pt.sex == "HM"].drop_duplicates("year").set_index("year").value
print("suicide rate PT HM: 2002", hm.get(2002), "2012", hm.get(2012), "2020", hm.get(2020), "2022", hm.get(2022),
      "2023", hm.get(2023), "2024", hm.get(2024), "| min", hm.idxmin(), hm.min(), "max", hm.idxmax(), hm.max())
print("sex 2022 H/M:", [pt[(pt.sex == s) & (pt.year == 2022)].value.iloc[0] for s in ["H", "M"]])

# ---- depressive symptoms (ih08): share of 15+ with mild or severe symptoms ----
dep = load("ih08")
tot = dep[dep.indicator == "depression_symptoms_count"].rename(columns={"value": "total"})[["date", "region", "sex", "age", "total"]]
cat = dep[dep.indicator != "depression_symptoms_count"].merge(tot, on=["date", "region", "sex", "age"])
cat = cat[cat.total > 0].copy()
cat["value"] = cat["value"] / cat["total"] * 100
cat["indicator"] = cat["indicator"].str.split("|").str[1]
cat["unit"] = "%"
cat["age"] = cat["age"].replace("", "15+")
export(cat, "q08_depressive_symptoms", AXIS,
       "Sintomas depressivos, 15+ anos, por sexo e idade (INS 2014, 2019, 2025; % da população)",
       "Depressive symptoms, 15+, by sex and age (INS 2014, 2019, 2025; % of population)")
anyd = cat[(cat.age == "15+") & cat.indicator.isin(["Sintomas ligeiros", "Sintomas graves"])].groupby(["sex", "year"]).value.sum().round(1)
print("any depressive symptoms % (mild+severe), HM/H/M:", {f"{s}-{y}": anyd[(s, y)] for s in ["HM", "H", "M"] for y in [2014, 2019, 2025]})

# ---- breaks: suicide, Portugal ----
series = {f"suicide_{s}_PT_all_ages": pt[pt.sex == s].drop_duplicates("year")[["date", "value"]] for s in ["HM", "H", "M"]}
note = "Série emendada em 2023 (INE ih10 NUTS 2013 até 2022; ih09 NUTS 2024 a partir de 2023): confirmar comparabilidade"
print("breaks kept (suicide):", find_breaks(series, AXIS, "ih10", level_pen=3, slope_pen=5, spike_z=3.5,
      notes={k: note for k in series}))
