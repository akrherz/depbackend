""".. title:: DEP Climate File by Lat/Lon Point

This service emits a climate file usable by WEPP, WEPS, or NTT.  This file
is provided for the nearest point to the provided latitude and longitude
pair.

Changelog
---------

- 2026-06-26: Added output format support for WEPS.
- 2025-12-08: Allow release of files from all current domains.
- 2025-08-28: Emit climate files for the Europe domain when requested.

Example Requests
----------------

Provide the nearest DEP climate file to point -97.50 East 35.5 North in WEPS
compatable format.

https://mesonet-dep.agron.iastate.edu/dl/climatefile.py?\
lat=35.5&lon=-97.5&format=weps


"""

import os
from io import StringIO
from pathlib import Path
from typing import Annotated

import pandas as pd
from dailyerosion.io.wepp import read_cli
from pydantic import Field
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.exceptions import NoDataFound
from pyiem.iemre import get_domain
from pyiem.util import logger
from pyiem.webutil import CGIModel, ListOrCSVType, iemapp
from sqlalchemy.engine import Connection

LOG = logger()


class Schema(CGIModel):
    """See how we are called."""

    lat: Annotated[
        float, Field(description="Latitude of point", ge=-90, le=90)
    ]
    lon: Annotated[
        float, Field(description="Longitude of point", ge=-180, le=180)
    ]
    format: Annotated[
        str,
        Field(
            description="Output format, wepp (Verbatim DEP File), ntt, or weps",
            pattern=r"^(wepp|ntt|weps)$",
        ),
    ] = "wepp"
    intensity: Annotated[
        ListOrCSVType,
        Field(
            default_factory=list,
            description="Comma delimited list of intensities to compute",
        ),
    ]
    scenario: Annotated[
        int,
        Field(
            description="Scenario ID",
            ge=-9999,
            le=9999,
        ),
    ] = 0


def log_request(
    conn: Connection,
    environ: dict,
    clipath: Path,
    distance: float,
    scenario: int,
):
    """Log this request"""
    conn.execute(
        sql_helper("""
INSERT into climate_file_requests(client_addr, geom, climate_file_id,
distance_degrees) VALUES (:addr, ST_Point(:lon, :lat, 4326),
(select climate_file_id from climate_file
 where scenario_id = :scenario and filepath = :fn),
:dist)
"""),
        {
            "lon": environ["lon"],
            "lat": environ["lat"],
            "fn": str(clipath),
            "dist": distance,
            "addr": environ.get("REMOTE_ADDR"),
            "scenario": scenario,
        },
    )
    conn.commit()


def find_closest_file(conn: Connection, query: Schema) -> tuple:
    """Find the closest climate file to the given point."""
    res = conn.execute(
        sql_helper("""
select filepath, st_distance(geom, ST_Point(:lon, :lat, 4326)) as distance
from climate_file where scenario_id = :scenario and
ST_Contains(ST_MakeEnvelope(:west, :south, :east, :north, 4326), geom)
order by geom <-> ST_Point(:lon, :lat, 4326) asc limit 1
                """),
        {
            "lon": query.lon,
            "lat": query.lat,
            "west": query.lon - 1,
            "south": query.lat - 1,
            "east": query.lon + 1,
            "north": query.lat + 1,
            "scenario": query.scenario,
        },
    )
    if res.rowcount == 0:
        return None, None
    row = res.first()
    return row[0], row[1]


def convert_to_weps(clifn: str) -> str:
    """Read and convert the clifn to a format WEPS likes."""
    dailydf = read_cli(clifn)
    with open(clifn) as fh:
        headerlines = []
        for linenum, line in enumerate(fh):
            headerlines.append(line)
            if linenum >= 14:
                break

    # Replace the version string
    headerlines[0] = " 5.20\n"
    # Replace the format opts line
    headerlines[1] = "   1   0   0\n"
    # Replace the text header, just in case, hopefully not needed
    headerlines[13] = (
        " da mo year   prcp  dur   tp     ip  tmax  tmin  "
        "rad  w-vl w-dir  tdew\n"
    )
    headerlines[14] = (
        "              (mm)  (h)               "
        "(C)   (C) (l/d) (m/s)(Deg)   (C)\n"
    )
    sio = StringIO()
    sio.write("".join(headerlines))
    for dt, row in dailydf.iterrows():
        tpeak = 0.0
        duration = 0.0
        if row["pcpn"] > 0:
            # Approximate until dailyerosion computes this
            tpeak = 0.5
            # Will add this in dailyerosion, but estimating for now
            duration = max(1.0, min(12.0, row["pcpn"] / (row["maxr"] * 4.0)))
        sio.write(
            f" {dt.strftime('%-2d %-2m %Y')} {row['pcpn']:5.1f} "
            f"{duration:5.2f}  "
            f"{tpeak:.2f} {row['maxr']:5.1f} "
            f"{row['tmax']:5.1f} {row['tmin']:5.1f}   {row['rad']:3.0f}"
            f"{row['wvl']:5.1f} {row['wdir']:5.1f} {row['tdew']:5.1f}"
            "\n"
        )

    return sio.getvalue()


@iemapp(help=__doc__, schema=Schema)
def application(environ, start_response):
    """Go Main Go."""
    query: Schema = environ["_cgimodel_schema"]
    domain = get_domain(query.lon, query.lat)
    if domain is None:
        raise NoDataFound("Point is outside of our domain")
    dbname = "dep" if domain == "conus" else f"dep_{domain}"
    with get_sqlalchemy_conn(dbname) as conn:
        fn, distance = find_closest_file(conn, query)
        if fn is None:
            raise NoDataFound("Database query found no files within 1° of pt")
        clipath = Path(fn)
        if not clipath.is_file():
            raise NoDataFound(
                f"Database found a file `{fn}` that does not exist on disk?!?"
            )
        if query.format == "wepp":
            # Log this request
            try:
                log_request(conn, environ, clipath, distance, query.scenario)
            except Exception as exp:
                LOG.exception(exp)

    dlfn = os.path.basename(fn)
    if query.format == "ntt":
        dlfn = dlfn[:-4].replace(".", "_") + ".wth"
    headers = [
        ("Content-type", "application/octet-stream"),
        ("Content-Disposition", f"attachment; filename={dlfn}"),
    ]
    if query.format == "weps":
        payload = convert_to_weps(clipath)
        start_response("200 OK", headers)
        return payload

    start_response("200 OK", headers)
    if query.intensity:
        levels = [int(x) for x in query.intensity]
        df = read_cli(clipath, compute_intensity_over=levels)
        df.index.name = "date"
        df = df.loc[: pd.Timestamp("now")]
        df = df[df["pcpn"] > 0]
        sio = StringIO()
        cols = [
            "pcpn",
        ] + [f"i{x}_mm" for x in levels]
        df[cols].to_csv(sio, float_format="%.2f")
        return sio.getvalue()

    if query.format == "wepp":
        with open(clipath, "rb") as fh:
            payload = fh.read()
    elif query.format == "ntt":
        df = read_cli(clipath)
        payload = StringIO()
        # Convert langleys to MJ
        df["rad"] = df["rad"] * 0.04184
        for dt, row in df.iterrows():
            payload.write(
                f"  {dt.strftime('%Y %-2m %-2d')}  {row['rad']:3.0f}"
                f"{row['tmax']:6.1f} {row['tmin']:6.1f} {row['pcpn']:6.2f}"
                "\r\n"
            )
        payload = payload.getvalue()
    return payload
