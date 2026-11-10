"""Axis acesso-e-recursos: question 9 (unmet needs) and question 10 (spending and resources).

Eurostat tables eac04-eac07 mix units in one column, so every use below filters on unit and
indicator explicitly. Unmet-needs total = reasons "too expensive, too far or waiting list"
(TXP_TFAR_WLIST). eac08/eac09 only have Portugal and NUTS 2 (no EU-27 aggregate).
"""
from __future__ import annotations

import pandas as pd

from _lib import EU, PT, export, find_breaks, load, reset_breaks

AXIS = "acesso-e-recursos"
reset_breaks(AXIS)


def to_series(df: pd.DataFrame) -> pd.DataFrame:
    return df[["date", "value"]]


def unmet(source_id: str, label: str) -> pd.DataFrame:
    d = load(source_id)
    d["reason"] = d["indicator"].str.extract(r"reason=([A-Z_]+)")[0]
    d["quint"] = d["indicator"].str.extract(r"quant_inc=([A-Z0-9]+)")[0]
    d = d[d.reason.isin(["TXP_TFAR_WLIST", "TXP", "TFAR", "WLIST"]) & (d.age.isin(["Y_GE16", "Y_GE65", "Y16-64"]))].copy()
    d["indicator"] = label + "|" + d["reason"] + "|" + d["quint"]
    return d


# ---- Q9: unmet medical and dental needs (eac01, eac02, eac03) ----
med, den = unmet("eac01", "medical"), unmet("eac02", "dental")
export(med, "q09_unmet_medical", AXIS,
       "Necessidades de cuidados médicos não satisfeitas por motivo e quintil de rendimento (EU-SILC, 2008-2025)",
       "Unmet medical care needs by reason and income quintile (EU-SILC, 2008-2025)")
export(den, "q09_unmet_dental", AXIS,
       "Necessidades de cuidados dentários não satisfeitas por motivo e quintil de rendimento (EU-SILC, 2008-2025)",
       "Unmet dental care needs by reason and income quintile (EU-SILC, 2008-2025)")
pov = load("eac03")
pov["indicator"] = "unmet_needs|" + pov["indicator"].str.extract(r"rskpovth=([A-Z_0-9]+)")[0]
export(pov, "q09_unmet_poverty", AXIS,
       "Necessidades não satisfeitas por limiar de risco de pobreza (EU-SILC, 2021-2025)",
       "Unmet needs by at-risk-of-poverty status (EU-SILC, 2021-2025)")


def pick(d, region=PT, reason="TXP_TFAR_WLIST", q="TOTAL", sex="T", age="Y_GE16"):
    return d[(d.region == region) & (d.reason == reason) & (d.quint == q) & (d.sex == sex) & (d.age == age)].set_index("year").value


m_pt, m_eu = pick(med), pick(med, EU)
d_pt, d_eu = pick(den), pick(den, EU)
print("unmet medical PT min/max:", m_pt.idxmin(), m_pt.min(), m_pt.idxmax(), m_pt.max(), "| 2025 PT/EU:", m_pt.iloc[-1], m_eu.iloc[-1])
print("unmet dental PT min/max:", d_pt.idxmin(), d_pt.min(), d_pt.idxmax(), d_pt.max(), "| 2025 PT/EU:", d_pt.iloc[-1], d_eu.iloc[-1])
print("dental Q1 vs Q5 PT latest:", pick(den, q="QU1").iloc[-1], pick(den, q="QU5").iloc[-1],
      "| medical:", pick(med, q="QU1").iloc[-1], pick(med, q="QU5").iloc[-1])

# ---- Q10: expenditure (eac04) ----
hf = load("eac04")
hf["hf"] = hf["indicator"].str.extract(r"icha11_hf=(.*)$")[0]
spend = hf[((hf.hf == "TOT_HF") & hf.unit.isin(["PC_GDP", "PPS_HAB", "EUR_HAB"])) |
           (hf.hf.isin(["HF1", "HF2", "HF3"]) & (hf.unit == "PC_CHE"))].copy()
spend["indicator"] = spend["hf"].map({"TOT_HF": "total", "HF1": "government_compulsory", "HF2": "voluntary_schemes",
                                      "HF3": "household_out_of_pocket"})
export(spend, "q10_health_expenditure", AXIS,
       "Despesa corrente em saúde: % do PIB, PPC por habitante e estrutura por regime de financiamento (1992-2025)",
       "Current health expenditure: % of GDP, PPS per capita and financing mix (1992-2025)")
g = spend[(spend.indicator == "total") & (spend.unit == "PC_GDP")].pivot_table(index="year", columns="region", values="value")
oop = spend[(spend.indicator == "household_out_of_pocket")].pivot_table(index="year", columns="region", values="value")
print("health spend % GDP PT first/last:", g[PT].dropna().index[0], g[PT].dropna().iloc[0], g[PT].dropna().index[-1], g[PT].dropna().iloc[-1],
      "| EU last:", g[EU].dropna().iloc[-1], int(g[EU].dropna().index[-1]))
print("OOP share of CHE PT first/last:", oop[PT].dropna().iloc[0], oop[PT].dropna().iloc[-1], "| EU last:", oop[EU].dropna().iloc[-1])
print("OOP PT peak:", oop[PT].idxmax(), oop[PT].max())

# function-of-care mix, latest year (eac05)
hc = load("eac05")
hc["hc"] = hc["indicator"].str.extract(r"icha11_hc=(.*)$")[0]
mix = hc[hc.hc.isin(["HC1", "HC2", "HC3", "HC4", "HC5", "HC6", "HC7", "TOT_HC"]) & (hc.unit == "PC_CHE")].copy()
mix["indicator"] = mix["hc"]
export(mix, "q10_expenditure_by_function", AXIS,
       "Despesa corrente em saúde por função de cuidados, % do total (1992-2025)",
       "Current health expenditure by function of care, % of total (1992-2025)")

# ---- Q10: personnel (eac06) and beds (eac07), unit P_HTHAB (per 100 000) ----
pr = load("eac06")
pr["spec"] = pr["indicator"].str.extract(r"med_spec=([A-Z]+)")[0]
pr["status"] = pr["indicator"].str.extract(r"wstatus=([A-Z]+)")[0]
staff = pr[(pr.unit == "P_HTHAB") & (((pr.status == "LIC") & (pr.spec == "PHYS")) | ((pr.status == "PACT") & (pr.spec == "NRS")) |
                                      ((pr.status == "LIC") & (pr.spec == "DENT")) | ((pr.status == "PACT") & (pr.spec == "PHARM")))].copy()
staff["indicator"] = staff["spec"].map({"PHYS": "physicians_licensed", "NRS": "nurses_active", "DENT": "dentists_licensed", "PHARM": "pharmacists_active"})
export(staff, "q10_health_personnel", AXIS,
       "Médicos, enfermeiros, dentistas e farmacêuticos por 100 000 hab., Portugal (Eurostat)",
       "Physicians, nurses, dentists and pharmacists per 100,000 inhabitants, Portugal (Eurostat)")
sp = staff[staff.region == PT].pivot_table(index="year", columns="indicator", values="value")
print("physicians /100k PT 1960/1990/2024:", sp.physicians_licensed.get(1960), sp.physicians_licensed.get(1990), sp.physicians_licensed.get(2024),
      "| nurses 2004/2024:", sp.nurses_active.get(2004), sp.nurses_active.get(2024))
print("EU personnel rows (non-physio):", len(pr[(pr.region == EU) & (pr.spec != "PHYSIO")]), "-> no EU-27 comparison for doctors/nurses in eac06")

bd = load("eac07")
bd = bd[(bd.unit == "P_HTHAB") & bd.indicator.str.contains("hlthcare=TOTAL") & bd.indicator.str.contains(r"facility=HBEDT\|")].copy()
bd["indicator"] = "hospital_beds_total"
export(bd, "q10_hospital_beds", AXIS,
       "Camas hospitalares por 100 000 hab., Portugal e UE-27 (Eurostat)",
       "Hospital beds per 100,000 inhabitants, Portugal and EU-27 (Eurostat)")
b = bd.pivot_table(index="year", columns="region", values="value")
print("beds /100k PT 1985/2024:", b[PT].dropna().iloc[0], b[PT].dropna().iloc[-1], "| EU 2009/2024:", b[EU].dropna().iloc[0], b[EU].dropna().iloc[-1])

# regional beds and physicians (eac08/eac09), NUTS 2 up to 2020
names = {"PT11": "Norte", "PT15": "Algarve", "PT16": "Centro", "PT17": "Área Metropolitana de Lisboa",
         "PT18": "Alentejo", "PT20": "R. A. Açores", "PT30": "R. A. Madeira", "Portugal": "Portugal"}
rb = load("eac08")
rb = rb[(rb.unit == "P_HTHAB") & rb.indicator.str.endswith("facility=HBEDT") & rb.region.isin(names)].copy()
rb["region"] = rb["region"].map(names)
rb["indicator"] = "hospital_beds_total"
rp = load("eac09")
rp = rp[(rp.unit == "P_HTHAB") & rp.indicator.str.endswith("OC221") & rp.region.isin(names)].copy()
rp["region"] = rp["region"].map(names)
rp["indicator"] = "physicians"
export(pd.concat([rb, rp]), "q10_resources_regions", AXIS,
       "Camas hospitalares e médicos por 100 000 hab., por região NUTS II (Eurostat, até 2020)",
       "Hospital beds and physicians per 100,000, by NUTS II region (Eurostat, to 2020)")
for lab, df in [("beds", rb), ("physicians", rp)]:
    y = int(df.year.max())
    print(f"{lab} /100k by region {y}:", df[df.year == y].set_index("region").value.round(0).to_dict())

# ---- breaks ----
ser = {"unmet_medical_T_16+_PT": to_series(m_pt.rename("value").reset_index().assign(date=lambda x: pd.to_datetime(x.year.astype(str) + "-01-01"))),
       "unmet_dental_T_16+_PT": to_series(d_pt.rename("value").reset_index().assign(date=lambda x: pd.to_datetime(x.year.astype(str) + "-01-01")))}
for lab, s in [("unmet_medical", m_pt - m_eu), ("unmet_dental", d_pt - d_eu)]:
    s = s.dropna().rename("value").reset_index()
    ser[f"{lab}_T_16+_gap_PT_minus_EU"] = pd.DataFrame({"date": pd.to_datetime(s.year.astype(str) + "-01-01"), "value": s.value})
print("breaks kept (eac01/eac02):", find_breaks(ser, AXIS, "eac01", level_pen=6, slope_pen=8, spike_z=4.5))


def yearly(s: pd.Series) -> pd.DataFrame:
    s = s.dropna().rename("value").reset_index()
    return pd.DataFrame({"date": pd.to_datetime(s.iloc[:, 0].astype(int).astype(str) + "-01-01"), "value": s["value"]})


ser = {"health_expenditure_pct_gdp_PT": yearly(g[PT]), "household_out_of_pocket_pct_CHE_PT": yearly(oop[PT]),
       "physicians_licensed_per_100k_PT": yearly(sp.physicians_licensed), "nurses_active_per_100k_PT": yearly(sp.nurses_active),
       "hospital_beds_per_100k_PT": yearly(b[PT])}
print("breaks kept (eac04-eac07):", find_breaks(ser, AXIS, "eac04", level_pen=6, slope_pen=8, spike_z=4.5))
