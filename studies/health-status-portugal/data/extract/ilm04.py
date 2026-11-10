"""INE 0009100 -> canonical long format. Downloads the INE JSON API response into data/raw/."""
import json
import re
from pathlib import Path

import pandas as pd

from common.download import download, read_manifest

CODE = "0009100"
URL = f"https://www.ine.pt/ine/json_indicador/pindica.jsp?op=2&varcd={CODE}&Dim1=T&lang=PT"
FILENAME = f"ilm04_ine_{CODE}.json"
SOURCE_ID = "ilm04"
INDICATOR = "premature_mortality_rate_30_70"
UNIT = "per 100000"
SEX_LABELS = {"HM", "H", "M", "Homens", "Mulheres"}


def _num(text):
    if text is None:
        return None
    try:
        return float(str(text).strip().replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def build(study_dir: Path) -> pd.DataFrame:
    path = study_dir / "data" / "raw" / FILENAME
    if not path.exists() or not any(e.file == FILENAME and e.url == URL for e in read_manifest(study_dir)):
        download(study_dir, URL, FILENAME)
    payload = json.loads(path.read_text(encoding="utf-8"))
    block = payload[0] if isinstance(payload, list) else payload
    rows = []
    for period, records in block["Dados"].items():
        year = re.search(r"(\d{4})", period).group(1)
        for rec in records:
            value = _num(rec.get("valor"))
            if value is None:
                continue
            sex, age, other = "", "", []
            for key in sorted(k for k in rec if re.fullmatch(r"dim_\d+_t", k)):
                label = str(rec[key]).strip()
                if label == "Total":
                    continue
                if label in SEX_LABELS and not sex:
                    sex = label
                elif re.search(r"anos?$|ano$|ou mais|Menos de", label) and not age:
                    age = label
                else:
                    other.append(label)
            rows.append({
                "date": f"{year}-01-01",
                "region": rec.get("geodsg", ""),
                "sex": sex,
                "age": age,
                "indicator": INDICATOR + ("|" + "|".join(other) if other else ""),
                "value": value,
                "unit": UNIT,
                "source_id": SOURCE_ID,
            })
    return pd.DataFrame(rows)
