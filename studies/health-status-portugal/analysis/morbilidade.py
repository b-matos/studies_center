"""Axis morbilidade: question 6 (self-rated health, chronic conditions, by sex, age, region).

Limitation: none of the loaded sources cross health with education level (only labour status in
Eurostat hlth_silc_01), so the education breakdown is not analysed.
"""
from __future__ import annotations

import pandas as pd

from _lib import EU, PT, export, find_breaks, load, reset_breaks

AXIS = "morbilidade"
reset_breaks(AXIS)

# ---- self-perceived health, Eurostat EU-SILC (eac16): whole population, PT vs EU ----
s = load("eac16")
s["levels"] = s["indicator"].str.extract(r"levels=([A-Z_]+)")[0]
s["wstatus"] = s["indicator"].str.extract(r"wstatus=([A-Z_]+)")[0]
print("eac16 levels:", sorted(s.levels.unique()))
pop = s[(s.wstatus == "POP") & s.age.isin(["Y_GE16", "Y_GE65", "Y16-64"])].copy()
pop["indicator"] = pop["levels"]
export(pop, "q06_self_perceived_health_eu", AXIS,
       "Saúde autoavaliada (EU-SILC), Portugal e UE-27, por sexo e idade (2008-2025)",
       "Self-perceived health (EU-SILC), Portugal and EU-27, by sex and age (2008-2025)")
bad = pop[(pop.levels == "B_VB") & (pop.sex == "T") & (pop.age == "Y_GE16")].pivot_table(index="year", columns="region", values="value")
print("bad/very bad 16+ PT 2008/latest:", bad[PT].dropna().iloc[0], bad[PT].dropna().iloc[-1],
      "| EU latest:", bad[EU].dropna().iloc[-1], "year", int(bad[EU].dropna().index[-1]))
gap = (bad[PT] - bad[EU]).dropna()
print("gap PT-EU bad health (pp): first", round(gap.iloc[0], 1), "last", round(gap.iloc[-1], 1))

# ---- INE ICOR: chronic condition and self-rated health, by sex and age (ih01, ih03) ----
c = load("ih01")
c["age"] = c["age"].replace("", "16+")
export(c, "q06_chronic_condition", AXIS,
       "Doença crónica ou problema de saúde prolongado, 16+ anos, por sexo e idade (INE, 2004-2025)",
       "Chronic condition or long-standing health problem, 16+, by sex and age (INE, 2004-2025)")
t = c[(c.sex == "HM") & (c.age == "16+")].set_index("year").value
print("chronic share 16+ HM 2004/2025:", t.loc[2004], t.loc[2025], "| 65+ 2025:",
      c[(c.sex == "HM") & (c.age == "65 e mais anos") & (c.year == 2025)].value.iloc[0],
      "| H vs M 2025:", c[(c.sex == "H") & (c.age == "16+") & (c.year == 2025)].value.iloc[0],
      c[(c.sex == "M") & (c.age == "16+") & (c.year == 2025)].value.iloc[0])

h = load("ih03")
h["age"] = h["age"].replace("", "16+")
export(h, "q06_self_rated_health_ine", AXIS,
       "Autoapreciação do estado de saúde, 16+ anos, por sexo e idade (INE, 2004-2025)",
       "Self-rated health, 16+, by sex and age (INE, 2004-2025)")
g = h[(h.sex == "HM") & (h.age == "16+") & (h.indicator.str.endswith("Muito bom ou bom"))].set_index("year").value
print("good/very good HM 16+ 2004/2025:", g.loc[2004], g.loc[2025])

# ---- regional chronic condition share (ih02, NUTS 2024; 2024 and 2025) ----
r = load("ih02")
export(r, "q06_chronic_condition_regions", AXIS,
       "Doença crónica, 16+ anos, por região NUTS 2024 (INE, 2024-2025)",
       "Chronic condition, 16+, by NUTS 2024 region (INE, 2024-2025)")
r25 = r[r.year == 2025].set_index("region").value.sort_values()
print("chronic share 2025 min/max region:", r25.index[0], r25.iloc[0], r25.index[-1], r25.iloc[-1])

# ---- breaks ----
series = {}
for sex in ["HM", "H", "M"]:
    for age in ["16+", "65 e mais anos", "16 - 64 anos"]:
        if sex != "HM" and age != "16+":
            continue
        series[f"chronic_{sex}_{age}"] = c[(c.sex == sex) & (c.age == age)][["date", "value"]]
print("breaks kept (ih01):", find_breaks(series, AXIS, "ih01", level_pen=6, slope_pen=8, spike_z=4.5))
series = {"good_health_HM_16+": h[(h.sex == "HM") & (h.age == "16+") & h.indicator.str.endswith("Muito bom ou bom")][["date", "value"]],
          "bad_health_HM_16+": h[(h.sex == "HM") & (h.age == "16+") & h.indicator.str.endswith("Mau ou muito mau")][["date", "value"]]}
print("breaks kept (ih03):", find_breaks(series, AXIS, "ih03", level_pen=6, slope_pen=8, spike_z=4.5))
series = {"bad_health_T_16+_PT": bad[PT].dropna().rename("value").reset_index().assign(
    date=lambda x: pd.to_datetime(x["year"].astype(int).astype(str) + "-01-01"))[["date", "value"]],
    "bad_health_T_16+_gap_PT_minus_EU": gap.rename("value").reset_index().assign(
    date=lambda x: pd.to_datetime(x["year"].astype(int).astype(str) + "-01-01"))[["date", "value"]]}
print("breaks kept (eac16):", find_breaks(series, AXIS, "eac16", level_pen=6, slope_pen=8, spike_z=4.5))
