"""Mapping Interface."""

from datetime import date, datetime
from io import BytesIO

import geopandas as gpd
import matplotlib.colors as mpcolors
import pandas as pd
from matplotlib.patches import Polygon, Rectangle
from pydantic import Field
from pyiem.database import get_sqlalchemy_conn, sql_helper
from pyiem.dep import RAMPS
from pyiem.exceptions import NoDataFound
from pyiem.plot.colormaps import dep_erosion, james
from pyiem.plot.geoplot import Z_OVERLAY2, MapPlot
from pyiem.plot.util import pretty_bins
from pyiem.reference import EPSG
from pyiem.webutil import CGIModel, iemapp

V2NAME = {
    "avg_loss": "Detachment",
    "qc_precip": "Precipitation",
    "avg_delivery": "Hillslope Soil Loss",
    "avg_runoff": "Runoff",
    "dt": "Dominant Tillage Code",
    "slp": "Average Slope Ratio",
}
V2MULTI = {
    "avg_loss": 4.463,
    "qc_precip": 1.0 / 25.4,
    "avg_delivery": 4.463,
    "avg_runoff": 1.0 / 25.4,
    "dt": 1,
    "slp": 1,
}
V2UNITS = {
    "avg_loss": "tons/acre",
    "qc_precip": "inches",
    "avg_delivery": "tons/acre",
    "avg_runoff": "inches",
    "dt": "categorical",
    "slp": "ratio",
}


class Schema(CGIModel):
    """See how we are called."""

    dpi: int = Field(100, description="Dots per inch", ge=50, le=300)
    year: int = Field(2024, description="Year of start date.")
    month: int = Field(1, description="Month of start date.")
    day: int = Field(1, description="Day of start date.")
    year2: int = Field(None, description="Year of end date.")
    month2: int = Field(None, description="Month of end date.")
    day2: int = Field(None, description="Day of end date.")
    scenario: int = Field(0, description="Scenario ID")
    v: str = Field("avg_loss", description="Variable to plot")
    huc: str = Field(None, description="HUC12 to plot")
    zoom: float = Field(10.0, description="Zoom level")
    overview: bool = Field(False, description="Generate overview map")
    averaged: bool = Field(False, description="Averaged over period")
    progressbar: bool = Field(False, description="Show progress bar")
    cruse: bool = Field(False, description="Show crude conversion")
    iowa: bool = Field(False, description="Limit to Iowa")
    mn: bool = Field(False, description="Limit to Minnesota")


def make_overviewmap(environ: dict):
    """Draw a pretty map of just the HUC."""
    huc = environ["huc"]
    projection = EPSG[5070]
    params = {}
    huclimiter = ""
    if huc is not None and len(huc) >= 8:
        huclimiter = " and substr(huc_12, 1, 8) = :huc8 "
        params["huc8"] = huc[:8]
    with get_sqlalchemy_conn("idep") as conn:
        df = gpd.read_postgis(
            sql_helper(
                """
            SELECT simple_geom as geom, huc_12,
            ST_x(ST_Transform(ST_Centroid(geom), 4326)) as centroid_x,
            ST_y(ST_Transform(ST_Centroid(geom), 4326)) as centroid_y, name
            from huc12 i WHERE i.scenario = 0 {huclimiter}
        """,
                huclimiter=huclimiter,
            ),
            conn,
            geom_col="geom",
            params=params,
            index_col="huc_12",
        )  # type: ignore
    if df.empty:
        raise NoDataFound("No Data Found for this scenario and date")
    minx, miny, maxx, maxy = df["geom"].total_bounds
    buf = environ["zoom"] * 1000.0  # 10km
    hucname = "" if huc not in df.index else df.at[huc, "name"]
    subtitle = "The HUC8 is in tan"
    if len(huc) == 12:
        subtitle = "HUC12 highlighted in red, the HUC8 it resides in is in tan"
    m = MapPlot(
        axisbg="#EEEEEE",
        logo="dep",
        sector="custom",
        south=miny - buf,
        north=maxy + buf,
        west=minx - buf,
        east=maxx + buf,
        projection=projection,
        continentalcolor="white",
        title=f"DEP HUC {huc}:: {hucname}",
        subtitle=subtitle,
        titlefontsize=20,
        subtitlefontsize=18,
        caption="Daily Erosion Project",
    )
    for _huc12, row in df.iterrows():
        p = Polygon(
            row["geom"].exterior.coords,
            fc="red" if _huc12 == huc else "tan",
            ec="k",
            zorder=Z_OVERLAY2,
            lw=0.1,
        )
        m.ax.add_patch(p)
        # If this is our HUC, add some text to prevent cities overlay overlap
        if _huc12 == huc:
            m.plot_values(
                [row["centroid_x"]],
                [row["centroid_y"]],
                ["    .    "],
                color="None",
                outlinecolor="None",
            )
    if huc is not None:
        m.drawcounties()
        m.drawcities()
    ram = BytesIO()
    m.fig.savefig(ram, format="png", dpi=100)
    ram.seek(0)
    return ram


def label_scenario(ax, scenario, conn):
    """Overlay a simple label of this scenario."""
    if scenario == 0:
        return
    res = conn.execute(
        sql_helper("select label from scenarios where id = :id"),
        {"id": scenario},
    )
    if res.rowcount == 0:
        return
    label = res.fetchone()[0]
    ax.text(
        0.99,
        0.99,
        f"Scenario {scenario}: {label}",
        transform=ax.transAxes,
        ha="right",
        va="top",
        bbox=dict(color="white"),
        zorder=1000,
    )


def make_map(conn, huc, ts, ts2, scenario, v, environ):
    """Make the map"""
    projection = EPSG[5070]
    # suggested for runoff and precip
    if v in ["qc_precip", "avg_runoff"]:
        # c = ['#ffffa6', '#9cf26d', '#76cc94', '#6399ba', '#5558a1']
        cmap = james()
    # suggested for detachment
    else:
        # c =['#cbe3bb', '#c4ff4d', '#ffff4d', '#ffc44d', '#ff4d4d', '#c34dee']
        cmap = dep_erosion()

    title = f"for {ts:%-d %B %Y}"
    aextra = ""
    if ts != ts2:
        title = f"for period between {ts:%-d %b %Y} and {ts2:%-d %b %Y}"
        if environ["averaged"]:
            aextra = "/yr"
            if f"{ts:%m%d}" == "0101" and f"{ts2:%m%d}" == "1231":
                title = f"averaged over inclusive years ({ts:%Y}-{ts2:%Y})"
            else:
                title = (
                    f"averaged between {ts:%-d %b} and {ts2:%-d %b} "
                    f"({ts:%Y}-{ts2:%Y})"
                )
    # Compute what the huc12 scenario is for this scenario
    res = conn.execute(
        sql_helper("select huc12_scenario from scenarios where id = :id"),
        {"id": scenario},
    )
    huc12_scenario = res.fetchone()[0]

    # Check that we have data for this date!
    res = conn.execute(
        sql_helper("SELECT value from properties where key = 'last_date_0'"),
    )
    if res.rowcount == 0:
        lastts = datetime(2007, 1, 1)
    else:
        lastts = datetime.strptime(res.fetchone()[0], "%Y-%m-%d")
    floor = date(2007, 1, 1)
    if ts > lastts.date() or ts2 > lastts.date() or ts < floor:
        raise NoDataFound("Data Not Availale Yet, check back later.")
    params = {
        "scenario": scenario,
        "huc12_scenario": huc12_scenario,
        "sday1": f"{ts:%m%d}",
        "sday2": f"{ts2:%m%d}",
        "ts": ts,
        "ts2": ts2,
        "dbcol": V2MULTI[v],
    }
    huclimiter = ""
    if huc is not None:
        if len(huc) == 8:
            huclimiter = " and substr(i.huc_12, 1, 8) = :huc8 "
            params["huc8"] = huc
        elif len(huc) == 12:
            huclimiter = " and i.huc_12 = :huc12 "
            params["huc12"] = huc
    if environ["iowa"]:
        huclimiter += " and i.states ~* 'IA' "
    if environ["mn"]:
        huclimiter += " and i.states ~* 'MN' "
    if v in ["dt", "slp"]:
        colname = "dominant_tillage" if v == "dt" else "average_slope_ratio"
        df = gpd.read_postgis(
            sql_helper(
                """
        SELECT simple_geom as geom,
        {colname} as data
        from huc12 i WHERE scenario = :huc12_scenario {huclimiter}
        """,
                huclimiter=huclimiter,
                colname=colname,
            ),
            conn,
            params=params,
            geom_col="geom",
        )  # type: ignore
    elif environ["averaged"]:
        df = gpd.read_postgis(
            sql_helper(
                """
        WITH data as (
        SELECT huc_12, sum({v}) / 10. as d from results_by_huc12
        WHERE scenario = :scenario and to_char(valid, 'mmdd') between
        :sday1 and :sday2
        and valid between :ts and :ts2
        GROUP by huc_12)

        SELECT simple_geom as geom,
        coalesce(d.d, 0) * :dbcol as data
        from huc12 i LEFT JOIN data d
        ON (i.huc_12 = d.huc_12) WHERE i.scenario = :huc12_scenario
        {huclimiter}
        """,
                huclimiter=huclimiter,
                v=v,
            ),
            conn,
            params=params,
            geom_col="geom",
        )  # type: ignore

    else:
        df = gpd.read_postgis(
            sql_helper(
                """
        WITH data as (
        SELECT huc_12, sum({v})  as d from results_by_huc12
        WHERE scenario = :scenario and valid between :ts and :ts2
        GROUP by huc_12)

        SELECT simple_geom as geom,
        coalesce(d.d, 0) * :dbcol as data
        from huc12 i LEFT JOIN data d
        ON (i.huc_12 = d.huc_12) WHERE i.scenario = :huc12_scenario
        {huclimiter}
        """,
                huclimiter=huclimiter,
                v=v,
            ),
            conn,
            params=params,
            geom_col="geom",
        )  # type: ignore
    if df.empty:
        raise NoDataFound("No Data Found for this scenario and date")
    minx, miny, maxx, maxy = df["geom"].total_bounds
    buf = 10000.0  # 10km
    mp = MapPlot(
        axisbg="#EEEEEE",
        logo="dep",
        sector="custom",
        south=miny - buf,
        north=maxy + buf,
        west=minx - buf,
        east=maxx + buf,
        projection=projection,
        title=f"DEP {V2NAME[v]} by HUC12 {title}",
        titlefontsize=16,
        caption="Daily Erosion Project",
    )
    if ts == ts2:
        # Daily
        bins = RAMPS["english"][0]
    else:
        bins = RAMPS["english"][1]
    # Check if our ramp makes sense
    p95 = df["data"].describe(percentiles=[0.95])["95%"]
    if not pd.isna(p95) and p95 > bins[-1]:
        bins = pretty_bins(0, p95)
        bins[0] = 0.01
    if v == "dt":
        bins = range(1, 8)
    if v == "slp":
        bins = [0, 0.01, 0.03, 0.05, 0.07, 0.1, 0.5]
    norm = mpcolors.BoundaryNorm(bins, cmap.N)
    for _, row in df.to_crs(mp.panels[0].crs).iterrows():
        p = Polygon(
            row["geom"].exterior.coords,
            fc=cmap(norm([row["data"]]))[0],
            ec="k",
            zorder=5,
            lw=0.1,
        )
        mp.ax.add_patch(p)

    label_scenario(mp.ax, scenario, conn)

    lbl = [round(_, 2) for _ in bins]
    if huc is not None:
        mp.drawcounties()
        mp.drawcities()
    mp.draw_colorbar(
        bins,
        cmap,
        norm,
        units=V2UNITS[v] + aextra,
        clevlabels=lbl,
        spacing="uniform",
    )
    avgval = None
    if environ["progressbar"]:
        avgval = df["data"].mean()
        _ll = ts.year if environ["averaged"] else "Avg"
        mp.fig.text(
            0.06,
            0.905,
            f"{_ll}: {avgval:4.1f} T/a",
            fontsize=14,
        )
        bar_width = 0.698
        # yes, a small one off with years having 366 days
        proportion = (ts2 - ts).days / 365.0 * bar_width
        rect1 = Rectangle(
            (0.20, 0.905),
            bar_width,
            0.02,
            color="k",
            zorder=40,
            transform=mp.fig.transFigure,
            figure=mp.fig,
        )
        mp.fig.patches.append(rect1)
        rect2 = Rectangle(
            (0.201, 0.907),
            proportion,
            0.016,
            color=cmap(norm(avgval)),
            zorder=50,
            transform=mp.fig.transFigure,
            figure=mp.fig,
        )
        mp.fig.patches.append(rect2)
    if environ["cruse"]:
        # Crude conversion of T/a to mm depth
        depth = avgval / 5.0
        mp.ax.text(
            0.9,
            0.92,
            f"{depth:.2f}mm",
            zorder=1000,
            fontsize=24,
            transform=mp.ax.transAxes,
            ha="center",
            va="center",
            bbox=dict(color="k", alpha=0.5, boxstyle="round,pad=0.1"),
            color="white",
        )
    ram = BytesIO()
    mp.fig.savefig(ram, format="png", dpi=environ["dpi"])
    ram.seek(0)
    return ram


def get_ts_ts2(environ):
    """Figure out the ts and ts2."""
    year = environ["year"]
    month = environ["month"]
    day = environ["day"]
    year2 = year if environ["year2"] is None else environ["year2"]
    month2 = month if environ["month2"] is None else environ["month2"]
    day2 = day if environ["day2"] is None else environ["day2"]
    ts = date(year, month, day)
    ts2 = date(year2, month2, day2)
    return ts, ts2


def get_mckey(environ):
    """Figure out the memcache key."""
    ts, ts2 = get_ts_ts2(environ)
    key = (
        f"/auto/map.py/{environ['huc']}/{ts:%Y%m%d}/{ts2:%Y%m%d}/"
        f"{environ['scenario']}/{environ['v']}"
    )
    if environ["overview"]:
        key = f"/auto/map.py/{environ['huc']}/{environ['zoom']}"
    return key


@iemapp(
    memcachekey=get_mckey,
    content_type="image/png",
    help=__doc__,
    schema=Schema,
    parse_times=False,
)
def application(environ, start_response):
    """Our mod-wsgi handler"""
    response_headers = [("Content-type", "image/png")]
    start_response("200 OK", response_headers)
    scenario = environ["scenario"]
    v = environ["v"]
    huc = environ["huc"]
    ts, ts2 = get_ts_ts2(environ)
    if environ["overview"] and huc is not None:
        res = make_overviewmap(environ).read()
    else:
        with get_sqlalchemy_conn("idep") as conn:
            res = make_map(conn, huc, ts, ts2, scenario, v, environ).read()

    return res
