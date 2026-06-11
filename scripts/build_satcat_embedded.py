"""Genera `app/satcat_embedded.py` a partir del satcat público de CelesTrak.

Filtra el catálogo completo (~30k entradas) por los NORADs presentes en los
datasets TLE embebidos (`app/tle_embedded.py` + el fixture de stations en
`app/streamlit_app.py`). Ejecutar cuando se actualicen los datasets.

Uso:
    python scripts/build_satcat_embedded.py
"""

from __future__ import annotations

import csv
import io
import pathlib
import re
import ssl
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app"

SATCAT_URL = "https://celestrak.org/pub/satcat.csv"

# Códigos OWNER de CelesTrak → nombre legible
OWNERS: dict[str, str] = {
    "AB": "Saudi Arabia", "ALG": "Algeria", "ARGN": "Argentina", "ASRA": "Austria",
    "AUS": "Australia", "AZER": "Azerbaijan", "BEL": "Belgium", "BELA": "Belarus",
    "BGD": "Bangladesh", "BHUT": "Bhutan", "BOL": "Bolivia", "BRAZ": "Brazil",
    "BUL": "Bulgaria", "CA": "Canada", "CHLE": "Chile", "CIS": "Russia/CIS",
    "COL": "Colombia", "CRI": "Costa Rica", "CZCH": "Czech Republic", "DEN": "Denmark",
    "DJI": "Djibouti", "DOM": "Dominican Republic", "ECU": "Ecuador", "EGYP": "Egypt",
    "ESA": "European Space Agency", "ESRO": "ESRO", "EST": "Estonia", "EUME": "EUMETSAT",
    "EUTE": "EUTELSAT", "FGER": "France/Germany", "FIN": "Finland", "FR": "France",
    "FRIT": "France/Italy", "GER": "Germany", "GHA": "Ghana", "GLOB": "Globalstar",
    "GREC": "Greece", "GUAT": "Guatemala", "HUN": "Hungary", "IM": "INMARSAT",
    "IND": "India", "INDO": "Indonesia", "IRAN": "Iran", "IRAQ": "Iraq",
    "IRID": "Iridium", "ISRA": "Israel", "ISS": "ISS (multinational)", "IT": "Italy",
    "ITSO": "Intelsat", "JPN": "Japan", "KAZ": "Kazakhstan", "KEN": "Kenya",
    "KWT": "Kuwait", "LAOS": "Laos", "LKA": "Sri Lanka", "LTU": "Lithuania",
    "LUXE": "Luxembourg", "MA": "Morocco", "MALA": "Malaysia", "MEX": "Mexico",
    "MNG": "Mongolia", "MUS": "Mauritius", "NATO": "NATO", "NETH": "Netherlands",
    "NICO": "Nicaragua", "NIG": "Nigeria", "NKOR": "North Korea", "NOR": "Norway",
    "NPL": "Nepal", "NZ": "New Zealand", "O3B": "O3B Networks", "ORB": "ORBCOMM",
    "PAKI": "Pakistan", "PER": "Peru", "PHL": "Philippines", "POL": "Poland",
    "POR": "Portugal", "PRC": "China (PRC)", "PRES": "Puerto Rico", "PRY": "Paraguay",
    "QAT": "Qatar", "RASC": "RASCOM", "ROC": "Taiwan", "ROM": "Romania",
    "RP": "Philippines", "RWA": "Rwanda", "SAFR": "South Africa", "SAUD": "Saudi Arabia",
    "SEAL": "Sea Launch", "SES": "SES", "SGP": "Singapore", "SKOR": "South Korea",
    "SPN": "Spain", "STCT": "Singapore/Taiwan", "SVN": "Slovenia", "SWED": "Sweden",
    "SWTZ": "Switzerland", "THAI": "Thailand", "TMMC": "Turkmenistan", "TUN": "Tunisia",
    "TURK": "Turkey", "UAE": "UAE", "UK": "United Kingdom", "UKR": "Ukraine",
    "UNK": "Unknown", "URY": "Uruguay", "US": "United States", "USBZ": "USA/Brazil",
    "VENZ": "Venezuela", "VTNM": "Vietnam", "ZWE": "Zimbabwe",
}

STATUS: dict[str, str] = {
    "+": "Operacional", "-": "No operacional", "P": "Parcialmente operacional",
    "B": "Backup/Reserva", "S": "En reserva", "X": "Misión extendida",
    "D": "Reentrado / decaído", "?": "Desconocido", "": "Sin datos",
}

TYPES: dict[str, str] = {
    "PAY": "Satélite (payload)", "R/B": "Cuerpo de cohete", "DEB": "Debris",
    "TBA": "Por asignar", "UNK": "Desconocido", "": "Sin clasificar",
}


def collect_norads() -> set[int]:
    """Extrae NORADs únicos de los TLE embebidos y del fixture stations.

    Detecta automáticamente todas las variables `TLE_*` que sean strings,
    así no hay que actualizar el script cuando se añaden grupos nuevos.
    """
    norads: set[int] = set()
    sys.path.insert(0, str(APP))
    import tle_embedded as te  # type: ignore
    tle_vars = [v for v in dir(te)
                if v.startswith("TLE_") and isinstance(getattr(te, v, None), str)]
    for var in tle_vars:
        text = getattr(te, var, "")
        for ln in text.splitlines():
            if ln.startswith("1 "):
                try:
                    norads.add(int(ln.split()[1].rstrip("U")))
                except Exception:
                    pass
    print(f"  ({len(tle_vars)} grupos TLE: {', '.join(v[4:] for v in tle_vars)})")
    # NORADs del fixture de stations embebido en streamlit_app.py
    sa = (APP / "streamlit_app.py").read_text(encoding="utf-8")
    for m in re.finditer(r"1 (\d{5})U", sa):
        norads.add(int(m.group(1)))
    return norads


def fetch_satcat() -> str:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        SATCAT_URL,
        headers={"User-Agent": "orbital-sentinel/0.1 satcat-builder"},
    )
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
        return r.read().decode("utf-8", errors="replace")


def build_records(csv_text: str, wanted: set[int]) -> dict[int, dict[str, str]]:
    records: dict[int, dict[str, str]] = {}
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        try:
            n = int(row["NORAD_CAT_ID"])
        except (KeyError, ValueError):
            continue
        if n not in wanted:
            continue
        records[n] = {
            "name": row["OBJECT_NAME"].strip(),
            "intl_id": row["OBJECT_ID"].strip(),
            "type": TYPES.get(row["OBJECT_TYPE"].strip(), row["OBJECT_TYPE"].strip()),
            "status": STATUS.get(row["OPS_STATUS_CODE"].strip(), row["OPS_STATUS_CODE"].strip()),
            "owner": OWNERS.get(row["OWNER"].strip(), row["OWNER"].strip()),
            "launch_date": row["LAUNCH_DATE"].strip(),
            "launch_site": row["LAUNCH_SITE"].strip(),
            "decay_date": row["DECAY_DATE"].strip(),
        }
    return records


def emit_module(records: dict[int, dict[str, str]]) -> str:
    lines = [
        '"""Catálogo satcat embebido — metadata por NORAD.',
        "",
        "Generado a partir de https://celestrak.org/pub/satcat.csv filtrando por",
        "los NORADs presentes en los datasets TLE embebidos. Regenerar con",
        "`scripts/build_satcat_embedded.py` cuando se actualicen los datasets.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "SATCAT: dict[int, dict[str, str]] = {",
    ]
    for n in sorted(records):
        lines.append(f"    {n}: {{")
        r = records[n]
        for k in ("name", "intl_id", "type", "status", "owner",
                  "launch_date", "launch_site", "decay_date"):
            lines.append(f"        {k!r}: {r.get(k, '')!r},")
        lines.append("    },")
    lines.append("}")
    lines.append("")
    lines.append(f"# {len(records)} entries")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    print("[1/4] Extrayendo NORADs de TLE embebidos…")
    norads = collect_norads()
    print(f"      {len(norads)} NORADs únicos")
    print("[2/4] Descargando satcat.csv de CelesTrak…")
    csv_text = fetch_satcat()
    print(f"      {csv_text.count(chr(10))} líneas")
    print("[3/4] Filtrando registros…")
    records = build_records(csv_text, norads)
    print(f"      {len(records)} matches ({100*len(records)/max(len(norads),1):.1f}%)")
    print("[4/4] Escribiendo app/satcat_embedded.py…")
    output = emit_module(records)
    (APP / "satcat_embedded.py").write_text(output, encoding="utf-8")
    print(f"      {len(output)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
