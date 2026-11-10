"""Axis fatores-de-risco: question 7 (smoking, alcohol, overweight/obesity).

INS counts (ih05-ih08) are turned into shares of the total row of the same table (same date,
region, sex, age). Smoking and BMI exist only for 2025 and alcohol for 2014/2019/2025, so no
trend breaks can be detected (fewer than 8 points); there is no EU comparison in the loaded data
(hlth_ehis was not extracted).
"""
from __future__ import annotations

import pandas as pd

from _lib import export, load, reset_breaks

AXIS = "fatores-de-risco"
reset_breaks(AXIS)
KEYS = ["date", "region", "sex", "age"]


def shares(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Category counts / total count of the table, in percent. Overlapping geographies are kept
    as they are in the source; the charts use Portugal and the NUTS II regions only."""
    df = df[~df["region"].isin(["Total", "Continente"])]
    total = df[df["indicator"] == prefix].rename(columns={"value": "total"})[KEYS + ["total"]]
    cat = df[df["indicator"] != prefix].merge(total, on=KEYS)
    cat = cat[cat["total"] > 0].copy()
    cat["value"] = cat["value"] / cat["total"] * 100
    cat["indicator"] = cat["indicator"].str.split("|").str[1]
    cat["unit"] = "%"
    cat["age"] = cat["age"].replace("", "15+")
    return cat


# ---- smoking (ih05 counts, ih04 direct daily-smoker share) ----
tob = shares(load("ih05"), "tobacco_status_count")
tob = tob[tob.indicator.isin(["Fumadores", "Fumador diário", "Ex-fumadores", "Nunca fumaram"])]
export(tob, "q07_tobacco", AXIS,
       "Condição perante o tabaco, 15+ anos, por região, sexo e idade (INS, 2025; % da população)",
       "Smoking status, 15+, by region, sex and age (INS, 2025; % of population)")
t = tob[(tob.region == "Portugal") & (tob.age == "15+") & (tob.indicator == "Fumadores")].set_index("sex").value.round(1)
print("smokers % PT 2025 HM/H/M:", t.to_dict())
ih04 = load("ih04")
ih04 = ih04[(ih04.indicator == "daily_smokers_share") & (ih04.region != "Continente")].drop_duplicates(["region", "sex", "value"])
export(ih04, "q07_daily_smokers_regions", AXIS,
       "Fumadores diários, 15+ anos, por região NUTS 2024 e sexo (INS, 2025)",
       "Daily smokers, 15+, by NUTS 2024 region and sex (INS, 2025)")
d = ih04[ih04.sex == "HM"].set_index("region").value.sort_values()
print("daily smokers % region min/max:", d.index[0], d.iloc[0], d.index[-1], d.iloc[-1])

# ---- BMI (ih07) ----
bmi = shares(load("ih07"), "bmi_class_count")
bmi["indicator"] = bmi["indicator"].str.extract(r"^(Baixo peso|Peso Normal|Excesso de peso - Grau I{1,2}|Obesidade)")[0]
export(bmi, "q07_bmi", AXIS,
       "Classes de índice de massa corporal, 18+ anos, por região, sexo e idade (INS, 2025; %)",
       "Body mass index classes, 18+, by region, sex and age (INS, 2025; %)")
b = bmi[(bmi.region == "Portugal") & (bmi.age == "15+") & (bmi.sex == "HM")]
ob = b[b.indicator == "Obesidade"].value.iloc[0]
over = b[b.indicator.isin(["Excesso de peso - Grau I", "Excesso de peso - Grau II", "Obesidade"])].value.sum()
print(f"obesity % PT 2025: {ob:.1f}; BMI>=25 %: {over:.1f}")
ob_r = bmi[(bmi.sex == "HM") & (bmi.age == "15+") & (bmi.indicator == "Obesidade")].set_index("region").value.round(1).sort_values()
print("obesity % region min/max:", ob_r.index[0], ob_r.iloc[0], ob_r.index[-1], ob_r.iloc[-1])

# ---- alcohol (ih06; waves 2014, 2019, 2025). Denominator = population who drank in the past 12
# months (total row). The four frequency categories are the frequency of 6+ drinks on one occasion. ----
alc = shares(load("ih06"), "alcohol_12m_count")
alc["indicator"] = alc["indicator"].replace({"Consumiu 6 ou mais bebidas numa única ocasião": "binge_6plus_any"})
export(alc, "q07_alcohol", AXIS,
       "Consumo de álcool nos 12 meses anteriores: ocasiões de 6+ bebidas (INS 2014, 2019, 2025; % dos consumidores)",
       "Alcohol in past 12 months: 6+ drinks per occasion (INS 2014, 2019, 2025; % of drinkers)")
a = alc[(alc.age == "15+") & (alc.sex == "HM") & (alc.indicator == "binge_6plus_any")].set_index("date").value.round(1)
print("binge share of drinkers HM:", {str(k)[:4]: v for k, v in a.items()})
print("breaks: none (fewer than 8 time points in every risk-factor series)")
