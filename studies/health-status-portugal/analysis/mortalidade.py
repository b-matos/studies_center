"""Axis mortalidade: questions 3 (causes of death), 4 (avoidable and infant mortality).

Question 5 (excess mortality) is NOT analysed: demo_r_mweek3 and demo_mexrt were excluded in
phase 2, so there is no weekly or monthly death series. It stays as a stated limitation.
"""
from __future__ import annotations

import pandas as pd

from _lib import EU, PT, export, find_breaks, load, reset_breaks

AXIS = "mortalidade"
reset_breaks(AXIS)

CAUSES = {  # Eurostat hlth_cd_asdr2 ICD-10 groups -> short label
    "TOTAL": "all_causes", "I": "circulatory", "C": "cancer_C00_C97", "J": "respiratory",
    "E10-E14": "diabetes", "V01-Y89": "external_causes",
}
NUTS = {"PT11": "Norte", "PT15": "Algarve", "PT16": "Centro", "PT19": "Centro",
        "PT17": "Área Metropolitana de Lisboa", "PT18": "Alentejo",
        "PT20": "R. A. Açores", "PT30": "R. A. Madeira"}

# ---- Q3: age-standardised death rates by cause, PT vs EU (ilm08) ----
d = load("ilm08")
d["icd"] = d["indicator"].str.split("icd10=").str[1]
d = d[d["icd"].isin(CAUSES) & (d["age"] == "TOTAL")].copy()
d["indicator"] = d["icd"].map(CAUSES)
# Data quality: the EU-27 aggregate is on a different basis in 2011-2012 (all-cause 674 vs 1035 in
# 2013), so it is dropped; regional zeros (PT18 2022) are missing values; the all-cause series has
# no values for 2018-2021 in the source extract.
d = d[~((d["region"] == EU) & (d["year"] <= 2012))]
d = d[~((d["value"] == 0) & (d["region"] != PT))]
nat = d[d["region"].isin([PT, EU])]
export(nat, "q03_causes_pt_eu", AXIS,
       "Taxa de mortalidade padronizada por causa, Portugal e UE-27 (2011-2023)",
       "Age-standardised death rate by cause, Portugal and EU-27 (2011-2023)")
reg = d[d["region"].isin(NUTS)].copy()
reg["region"] = reg["region"].map(NUTS)  # PT16 (to 2021) and PT19 (2023, NUTS 2024) both mapped to Centro
export(reg[reg.sex == "T"], "q03_causes_regions", AXIS,
       "Mortalidade padronizada por causa e região NUTS II (Eurostat, 2011-2023; Centro: PT16 até 2021, PT19 em 2023)",
       "Standardised death rate by cause and NUTS II region (Eurostat, 2011-2023; Centro: PT16 to 2021, PT19 in 2023)")
n = nat[(nat.sex == "T")].pivot_table(index=["year", "indicator"], columns="region", values="value")
for c in ["circulatory", "cancer_C00_C97", "respiratory", "diabetes", "external_causes", "all_causes"]:
    s = n.loc[(slice(None), c), :].droplevel("indicator")
    print(f"{c}: PT 2011={s.loc[2011, PT]:.0f} 2023={s.loc[2023, PT]:.0f} | EU 2023={s.loc[2023, EU]:.0f}")
r17 = reg[(reg.sex == "T") & (reg.indicator == "circulatory") & (reg.year == 2021)].groupby("region").value.mean().round(0)
print("circulatory SDR 2021 by region:", r17.to_dict())
print("all-cause years available (PT):", sorted(nat[(nat.region == PT) & (nat.indicator == "all_causes") & (nat.sex == "T")].year.unique()))

# INE 2024 snapshot by cause and NUTS 2024 (ilm02, sex HM)
ine = load("ilm02")
ine["cause"] = ine["indicator"].str.split("|").str[1]
keep = ["Todas as causas de morte", "Doenças do aparelho circulatório", "Tumores malignos",
        "Doenças do aparelho respiratório", "Diabetes mellitus", "Causas de morte externas"]
regs = ["Portugal", "Norte", "Centro", "Grande Lisboa", "Península de Setúbal", "Oeste e Vale do Tejo",
        "Alentejo", "Algarve", "Região Autónoma dos Açores", "Região Autónoma da Madeira"]
snap = ine[ine["cause"].isin(keep) & ine["region"].isin(regs) & (ine.sex == "HM")].drop_duplicates(["region", "cause"])
snap = snap.assign(indicator=snap["cause"])
export(snap, "q03_causes_regions_2024", AXIS,
       "Mortalidade padronizada por causa e região NUTS 2024 (INE, 2024)",
       "Standardised mortality by cause and NUTS 2024 region (INE, 2024)")
print("ilm02 2024 all causes:", snap[snap.cause == "Todas as causas de morte"].set_index("region").value.round(0).to_dict())

# premature mortality (30-70) and under-75 (INE)
prem = pd.concat([load("ilm04"), load("ilm03")])
export(prem, "q03_premature_mortality", AXIS,
       "Mortalidade prematura (30-70 anos) e antes dos 75 anos, Portugal (INE)",
       "Premature (30-70) and under-75 mortality, Portugal (INE)")
p = prem[(prem.indicator == "premature_mortality_rate_30_70") & (prem.sex == "HM")].set_index("year").value
print("premature 30-70 HM:", p.iloc[0], p.iloc[-1], "first/last year", p.index[0], p.index[-1])

# ---- Q4: avoidable mortality (eac12; unit RT = rate per 100 000) ----
av = load("eac12")
av["mortalit"] = av["indicator"].str.extract(r"mortalit=([A-Z]+)")[0]
av["icd"] = av["indicator"].str.extract(r"icd10=(.*)$")[0]
tot = av[(av.icd == "TOTAL") & (av.unit == "RT") & av.mortalit.isin(["PRVT", "TRT"])].copy()
tot["indicator"] = tot["mortalit"].map({"PRVT": "preventable", "TRT": "treatable"})
export(tot, "q04_avoidable_mortality", AXIS,
       "Mortalidade evitável (prevenível e tratável) por 100 000 hab., Portugal e UE-27 (2011-2023)",
       "Avoidable mortality (preventable and treatable) per 100,000, Portugal and EU-27 (2011-2023)")
a = tot[tot.sex == "T"].pivot_table(index=["year", "indicator"], columns="region", values="value")
for k in ["preventable", "treatable"]:
    s = a.loc[(slice(None), k), :].droplevel("indicator")
    print(f"{k}: PT 2011={s.loc[2011, PT]:.0f} 2023={s.loc[2023, PT]:.0f} | EU 2011={s.loc[2011, EU]:.0f} 2023={s.loc[2023, EU]:.0f}")
chk = av[(av.region == PT) & (av.icd == "Y70-Y82") & (av.sex == "T") & (av.year == 2023)][["unit", "value"]]
print("eac12 PT 2023 Y70-Y82 (value 0 check):", chk.values.tolist())
dup = tot[(tot.region == PT) & (tot.sex == "T") & (tot.mortalit == "TRT") & tot.year.isin([2021, 2022])].value.tolist()
print("eac12 PT treatable 2021, 2022 (identical values, check provisional):", dup)

inf = load("ilm07")
inf = inf[inf.indicator.str.contains("INFMORRT|NEOMORRT|PERIMORRT")].copy()
inf["indicator"] = inf["indicator"].str.split("=").str[1].map(
    {"INFMORRT": "infant", "NEOMORRT": "neonatal", "PERIMORRT": "perinatal"})
export(inf, "q04_infant_mortality", AXIS,
       "Mortalidade infantil, neonatal e perinatal por 1000 nados-vivos, Portugal e UE-27 (1960-2024)",
       "Infant, neonatal and perinatal mortality per 1,000 live births, Portugal and EU-27 (1960-2024)")
i = inf[inf.indicator == "infant"].pivot_table(index="year", columns="region", values="value")
print("infant PT 1960/2024:", i.loc[1960, PT], i.loc[2024, PT], "EU 2024:", i.loc[2024, EU],
      "EU first year:", int(i[EU].dropna().index.min()))

reg6 = load("ilm06")
nuts2_ine = ["Portugal", "Norte", "Centro", "Grande Lisboa", "Península de Setúbal", "Oeste e Vale do Tejo",
             "Alentejo", "Algarve", "Região Autónoma dos Açores", "Região Autónoma da Madeira"]
reg6 = reg6[reg6["region"].isin(nuts2_ine)].copy()
reg6["period"] = (reg6["year"] - 4).astype(str) + "-" + reg6["year"].astype(str)  # date = last year of the 5-year window
export(reg6, "q04_infant_mortality_regions", AXIS,
       "Taxa quinquenal de mortalidade infantil por região NUTS 2024 (INE; data = último ano da janela)",
       "Five-year infant mortality rate by NUTS 2024 region (INE; date = last year of the window)")
lat = reg6[reg6.year == reg6.year.max()].set_index("region").value.round(2).to_dict()
print("ilm06 latest 5y window:", lat)

# ---- breaks ----
series = {}
for k, lab in CAUSES.items():
    if lab == "all_causes":  # 2018-2021 missing, detectors would be unreliable
        continue
    s = nat[(nat.region == PT) & (nat.sex == "T") & (nat.indicator == lab)]
    series[f"SDR_{lab}_T_PT"] = s[["date", "value"]]
note21 = "Nível cai em todas as regiões em 2021 (circulatórias): verificar possível alteração de codificação/método antes de interpretar"
print("breaks kept (asdr2):", find_breaks(series, AXIS, "ilm08", level_pen=6, slope_pen=8, spike_z=4.5,
      notes={k: note21 for k in series if "circulatory" in k}))
series = {f"avoidable_{k}_T_PT": tot[(tot.region == PT) & (tot.sex == "T") & (tot.indicator == k)][["date", "value"]]
          for k in ["preventable", "treatable"]}
print("breaks kept (eac12):", find_breaks(series, AXIS, "eac12", level_pen=6, slope_pen=8, spike_z=4.5))
series = {f"{k}_mortality_{r}": inf[(inf.indicator == k) & (inf.region == r)][["date", "value"]]
          for k in ["infant", "neonatal", "perinatal"] for r in ["PT"] for r in [PT]}
series["infant_mortality_EU"] = inf[(inf.indicator == "infant") & (inf.region == EU)][["date", "value"]]
print("breaks kept (demo_minfind):", find_breaks(series, AXIS, "ilm07", level_pen=8, slope_pen=8, spike_z=5))
series = {"premature_30_70_HM": prem[(prem.indicator == "premature_mortality_rate_30_70") & (prem.sex == "HM")][["date", "value"]]}
print("breaks kept (ilm04):", find_breaks(series, AXIS, "ilm04", level_pen=6, slope_pen=8, spike_z=4.5))
