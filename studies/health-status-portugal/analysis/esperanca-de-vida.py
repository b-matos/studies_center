"""Axis esperanca-de-vida: questions 1 (life expectancy) and 2 (healthy life years)."""
from __future__ import annotations

import pandas as pd

from _lib import EU, PT, export, find_breaks, load, reset_breaks

AXIS = "esperanca-de-vida"
reset_breaks(AXIS)

# ---- Q1: life expectancy at birth and at 65, Portugal vs EU, by sex (eac11) ----
le = load("eac11")
le = le[le["age"].isin(["Y_LT1", "Y65"]) & le["sex"].isin(["T", "M", "F"])].copy()
le["age"] = le["age"].map({"Y_LT1": "0", "Y65": "65"})
le["indicator"] = "life_expectancy"
export(le, "q01_life_expectancy", AXIS,
       "Esperança de vida à nascença e aos 65 anos, Portugal e UE-27 (1960-2024)",
       "Life expectancy at birth and at 65, Portugal and EU-27 (1960-2024)")

piv = le.pivot_table(index=["year", "sex", "age"], columns="region", values="value").reset_index()
piv["gap"] = piv[PT] - piv[EU]
first = piv.dropna(subset=["gap"]).groupby(["sex", "age"]).head(1)
t_all = piv[(piv.sex == "T")].set_index(["age", "year"])
print("LE birth PT 1960/2024:", round(t_all.loc[("0", 1960), PT], 1), round(t_all.loc[("0", 2024), PT], 1))
print("LE birth gap PT-EU first/last year:",
      first[(first.sex == "T") & (first.age == "0")][["year", "gap"]].round(2).values.tolist(),
      round(t_all.loc[("0", 2024), "gap"], 2))
print("LE 65 PT 2024:", round(t_all.loc[("65", 2024), PT], 1), "EU", round(t_all.loc[("65", 2024), EU], 1))
print("Min gap year (birth,T):", int(t_all.loc["0"]["gap"].idxmin()), round(t_all.loc["0"]["gap"].min(), 2))

# ---- Q2: healthy life years (eac10) ----
hly = load("eac10")
hly["measure"] = hly["indicator"].str.split("=").str[1]
sel = hly[hly["measure"].isin(["HLY_Y0", "HLY_Y65", "LE_Y0", "LE_Y65", "HLY_LE_Y0_PC", "HLY_LE_Y65_PC"])].copy()
export(sel, "q02_healthy_life_years", AXIS,
       "Anos de vida saudável e peso na esperança de vida, Portugal e UE-27 (2004-2024)",
       "Healthy life years and share of life expectancy, Portugal and EU-27 (2004-2024)")
h = sel.pivot_table(index=["year", "sex", "measure"], columns="region", values="value").reset_index()
h["gap"] = h[PT] - h[EU]
for m in ["HLY_Y0", "HLY_Y65"]:
    s = h[(h.sex == "T") & (h.measure == m)].set_index("year")
    print(m, "PT 2004/2024:", round(s.loc[2004, PT], 1), round(s.loc[2024, PT], 1),
          "gap 2004/2024:", round(s.loc[2004, "gap"], 2), round(s.loc[2024, "gap"], 2))

# ---- regional life expectancy at birth, NUTS 2013 (ilm01, triennial, date = first year) ----
nuts2 = ["Norte", "Centro", "Área Metropolitana de Lisboa", "Alentejo", "Algarve",
         "Região Autónoma dos Açores", "Região Autónoma da Madeira", "Portugal"]
reg = load("ilm01")
reg = reg[reg["region"].isin(nuts2)].drop_duplicates(["region", "date", "value"]).copy()  # NUTS 2 = NUTS 3 in the islands
reg["period"] = reg["year"].astype(str) + "-" + (reg["year"] + 2).astype(str)
export(reg, "q01_life_expectancy_regions", AXIS,
       "Esperança de vida à nascença por região NUTS II (triénios, INE)",
       "Life expectancy at birth by NUTS II region (three-year periods, INE)")
r = reg[reg.year == reg.year.max()].sort_values("value")
print("ilm01 latest period", r.period.iloc[0], r[["region", "value"]].round(1).values.tolist())

# ---- breaks (Portugal; gap vs EU) ----
series = {}
for sex in ["T", "M", "F"]:
    for age in ["0", "65"]:
        s = le[(le.region == PT) & (le.sex == sex) & (le.age == age)]
        series[f"LE_age{age}_{sex}_PT"] = s[["date", "value"]]
for age in ["0", "65"]:
    g = piv[(piv.sex == "T") & (piv.age == age)].dropna(subset=["gap"])
    series[f"LE_age{age}_T_gap_PT_minus_EU"] = pd.DataFrame(
        {"date": pd.to_datetime(g["year"].astype(str) + "-01-01"), "value": g["gap"]})
print("breaks kept (LE):", find_breaks(series, AXIS, "eac11", level_pen=8, slope_pen=8, spike_z=4.5))
series = {}
for m in ["HLY_Y0", "HLY_Y65", "HLY_LE_Y0_PC"]:
    s = sel[(sel.region == PT) & (sel.sex == "T") & (sel.measure == m)]
    series[f"{m}_T_PT"] = s[["date", "value"]]
    g = h[(h.sex == "T") & (h.measure == m)].dropna(subset=["gap"])
    series[f"{m}_T_gap_PT_minus_EU"] = pd.DataFrame(
        {"date": pd.to_datetime(g["year"].astype(str) + "-01-01"), "value": g["gap"]})
print("breaks kept (HLY):", find_breaks(series, AXIS, "eac10", level_pen=5, slope_pen=5, spike_z=4.5))
