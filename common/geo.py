"""Portuguese geography: NUTS regions with their boundaries, and sex labels.

Region labels in the sources do not agree: INE and Eurostat publish under different NUTS versions, and the same
name can be a different area ("Centro" and "Alentejo" changed their boundaries between NUTS 2021 and NUTS 2024,
and Grande Lisboa, Península de Setúbal and Oeste e Vale do Tejo only exist in 2024). So every map or regional
comparison names a NUTS version and level, and region labels are mapped to codes against that version.

The boundaries are Eurostat GISCO's NUTS 1:3M (c) EuroGeographics, simplified and committed under
`site/assets/geo/pt_nuts<version>_<level>.json` (properties: nuts_id, name, level, version, shifted). Madeira and the
Azores are moved next to the mainland so a map fits one frame; their features carry `shifted: true` and the chart
says so. They are rebuilt, reproducibly, with:

    uv run python -m common.geo build            # all versions and levels (needs network)
    uv run python -m common.geo units 2024 2     # list the units of a version and level
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
GEO_DIR = ROOT / "site" / "assets" / "geo"
GISCO_URL = "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_03M_{version}_4326_LEVL_{level}.geojson"
VERSIONS = ("2021", "2024")
LEVELS = (2, 3)
# Island groups are shifted (degrees east, north) to sit in the Atlantic west of the mainland, over the same
# latitudes, so one compact map shows everything and the mainland is not shrunk by empty sea.
ISLAND_SHIFT = {"PT20": (14.3, 1.5), "PT30": (4.7, 4.3)}  # Azores (PT20*) and Madeira (PT30*)
COORD_DECIMALS = 3
ATTRIBUTION = "Limites administrativos: (c) EuroGeographics, Eurostat GISCO"


def geo_path(version: str, level: int) -> Path:
    return GEO_DIR / f"pt_nuts{version}_{level}.json"


def _shift(coords, dx: float, dy: float):
    if coords and isinstance(coords[0], (int, float)):
        return [round(coords[0] + dx, COORD_DECIMALS), round(coords[1] + dy, COORD_DECIMALS)]
    return [_shift(c, dx, dy) for c in coords]


def prepare_features(raw: dict, version: str, level: int) -> dict:
    """Keep Portugal's features, trim their properties, round the coordinates and shift the island groups."""
    features = []
    for feature in raw["features"]:
        props = feature["properties"]
        if props.get("CNTR_CODE") != "PT":
            continue
        nuts_id = props["NUTS_ID"]
        dx, dy = next((shift for prefix, shift in ISLAND_SHIFT.items() if nuts_id.startswith(prefix)), (0.0, 0.0))
        geometry = {"type": feature["geometry"]["type"], "coordinates": _shift(feature["geometry"]["coordinates"], dx, dy)}
        features.append({
            "type": "Feature",
            "properties": {"nuts_id": nuts_id, "name": props["NAME_LATN"], "level": level, "version": version, "shifted": bool(dx or dy)},
            "geometry": geometry,
        })
    features.sort(key=lambda f: f["properties"]["nuts_id"])
    return {"type": "FeatureCollection", "features": features}


def build_geojson(version: str, level: int, *, timeout: float = 120.0) -> Path:
    import httpx

    url = GISCO_URL.format(version=version, level=level)
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    collection = prepare_features(response.json(), version, level)
    GEO_DIR.mkdir(parents=True, exist_ok=True)
    path = geo_path(version, level)
    path.write_text(json.dumps(collection, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    _record_source(version, level, url, hashlib.sha256(response.content).hexdigest(), len(collection["features"]))
    return path


def _record_source(version: str, level: int, url: str, sha256: str, n_features: int) -> None:
    """Keep GEO_DIR/SOURCES.csv: where each file came from, when, and the hash of the download."""
    path = GEO_DIR / "SOURCES.csv"
    rows = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            file = line.split(",")[0]
            rows[file] = line
    name = geo_path(version, level).name
    rows[name] = f"{name},{url},{datetime.now(UTC).strftime('%Y-%m-%d')},{sha256},{n_features},{ATTRIBUTION}"
    path.write_text("file,url,access_date,source_sha256,features,attribution\n" + "\n".join(rows[k] for k in sorted(rows)) + "\n", encoding="utf-8")


@lru_cache(maxsize=8)
def units(version: str, level: int) -> dict[str, str]:
    """NUTS code -> name for one version and level, from the committed boundaries."""
    path = geo_path(version, level)
    if not path.exists():
        raise ValueError(f"no boundaries for NUTS {version} level {level}: run `uv run python -m common.geo build`")
    features = json.loads(path.read_text(encoding="utf-8"))["features"]
    return {f["properties"]["nuts_id"]: f["properties"]["name"] for f in features}


def _key(label: str) -> str:
    text = unicodedata.normalize("NFKD", str(label)).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"\(pt\)", " ", text)  # GISCO writes "Centro (PT)"; sources write "Centro"
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def region_code(label: str, version: str, level: int) -> str | None:
    """The NUTS code for a region label or code under one version and level (None when it does not belong)."""
    table = units(version, level)
    if str(label) in table:
        return str(label)
    by_name = {_key(name): code for code, name in table.items()}
    return by_name.get(_key(label))


def add_region_codes(df: pd.DataFrame, version: str, level: int, region_col: str = "region") -> pd.DataFrame:
    """Add a `region_code` column ('' where the label is not a unit of that version and level)."""
    cache: dict[str, str] = {}
    labels = df[region_col].astype(str)
    for label in labels.unique():
        cache[label] = region_code(label, version, level) or ""
    return df.assign(region_code=labels.map(cache))


def detect_nuts(labels: list[str]) -> list[tuple[str, int, float]]:
    """Which (version, level) explains most of these region labels, best first. Helps pick `geo` for a chart."""
    labels = [label for label in set(labels) if label]
    scored = []
    for version in VERSIONS:
        for level in LEVELS:
            if not geo_path(version, level).exists():
                continue
            hits = sum(1 for label in labels if region_code(label, version, level))
            scored.append((version, level, hits / len(labels) if labels else 0.0))
    return sorted(scored, key=lambda t: -t[2])


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


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["build"]:
        for version in VERSIONS:
            for level in LEVELS:
                print(f"built {build_geojson(version, level).relative_to(ROOT)}")
        return 0
    if args[:1] == ["units"] and len(args) == 3:
        for code, name in units(args[1], int(args[2])).items():
            print(f"{code}  {name}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
