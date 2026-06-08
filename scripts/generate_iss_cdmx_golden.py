"""One-shot generator del vector dorado ISS×CDMX usando Skyfield.

NO se incluye Skyfield en pyproject.toml. Este script se ejecuta una vez en el
entorno del autor, sus outputs se pegan como constantes en el test
``test_pass_prediction_iss_golden.py``.

Uso:
    python scripts/generate_iss_cdmx_golden.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from skyfield.api import EarthSatellite, load, wgs84

ISS_TLE_PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "tle" / "iss_vallado_2008.txt"
EPOCH = datetime(2008, 9, 20, 12, 25, 40, tzinfo=timezone.utc)
WINDOW_HOURS = 48
MIN_ELEVATION_DEG = 10.0
CDMX_LAT, CDMX_LON, CDMX_ALT_M = 19.4326, -99.1332, 2240.0


def main() -> None:
    text = ISS_TLE_PATH.read_text(encoding="ascii").strip().splitlines()
    line0 = text[0] if not text[0].startswith(("1", "2")) else None
    if line0 is not None:
        line1, line2 = text[1], text[2]
        name = line0.strip()
    else:
        line1, line2 = text[0], text[1]
        name = "ISS"

    ts = load.timescale()
    sat = EarthSatellite(line1, line2, name, ts)
    observer = wgs84.latlon(CDMX_LAT, CDMX_LON, elevation_m=CDMX_ALT_M)

    t0 = ts.from_datetime(EPOCH)
    t1 = ts.from_datetime(EPOCH + timedelta(hours=WINDOW_HOURS))

    times, events = sat.find_events(observer, t0, t1, altitude_degrees=MIN_ELEVATION_DEG)
    # events: 0 = rise, 1 = culminate, 2 = set
    passes = []
    current: dict[str, object] = {}
    for ti, ev in zip(times, events):
        utc_dt = ti.utc_datetime()
        topo = (sat - observer).at(ti)
        alt, az, _ = topo.altaz()
        if ev == 0:
            current = {"aos": utc_dt, "aos_az": az.degrees}
        elif ev == 1:
            current["culmination"] = utc_dt
            current["max_elev_deg"] = alt.degrees
            current["culmination_az"] = az.degrees
        elif ev == 2:
            current["los"] = utc_dt
            current["los_az"] = az.degrees
            if all(k in current for k in ("aos", "culmination", "los")):
                passes.append(current)
            current = {}

    print(f"# Skyfield golden master: ISS Vallado 2008-09-20 × CDMX × {WINDOW_HOURS}h × min_elev={MIN_ELEVATION_DEG}°")
    print(f"# Generated offline; copy into test_pass_prediction_iss_golden.py")
    print(f"GOLDEN_PASSES = [")
    for p in passes:
        print(
            f"    dict("
            f"aos='{p['aos'].isoformat()}', "
            f"culmination='{p['culmination'].isoformat()}', "
            f"los='{p['los'].isoformat()}', "
            f"max_elevation_deg={p['max_elev_deg']:.4f}, "
            f"aos_azimuth_deg={p['aos_az']:.2f}, "
            f"culmination_azimuth_deg={p['culmination_az']:.2f}, "
            f"los_azimuth_deg={p['los_az']:.2f}),"
        )
    print(f"]")
    print(f"# n_passes = {len(passes)}")


if __name__ == "__main__":
    main()
