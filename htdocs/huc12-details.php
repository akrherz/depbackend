<?php
date_default_timezone_set('America/Chicago');
$huc_12 = isset($_REQUEST['huc12']) ? substr($_REQUEST['huc12'], 0, 12) : die();
$date = isset($_REQUEST['date']) ? strtotime($_REQUEST['date']) : die();
$date2 = isset($_REQUEST['date2']) ? strtotime($_REQUEST['date2']) : null;
$scenario = isset($_REQUEST["scenario"]) ? intval($_REQUEST["scenario"]) : 0;
$metric = isset($_REQUEST["metric"]) ? intval($_REQUEST["metric"]) : 0;
$year = date("Y", $date);

$dbconn = pg_connect("dbname=dep host=iemdb-dep.local user=nobody");

/* Find the HUC12 this location is in */
$rs = pg_prepare(
    $dbconn,
    "SELECT",
    "SELECT name from huc12 WHERE huc12_code = $1 and scenario_id = $2",
);
$rs = pg_execute($dbconn, "SELECT", array($huc_12, $scenario));
if (pg_num_rows($rs) != 1) {
    echo "ERROR: HUC12 was not found!";
    die();
}
$row = pg_fetch_assoc($rs, 0);
$hu12name = $row["name"];

$nicedate = date("d M Y", $date);
if ($date2 != null) {
    $nicedate = sprintf("%s to %s", date("d M Y", $date), date("d M Y", $date2));
}
echo <<<EOF
<h4>Detailed Data:</h4>
<h4>{$hu12name}</h4>
<form name="changer" method="GET">
<strong>HUC 12:</strong>
<input type="text" value="$huc_12" name="huc_12" id="huc_12" size="12"/>
<br />&nbsp;
<p>
<button data-action="view-events" data-huc12="{$huc_12}" data-period="daily"
 class="btn btn-sm btn-primary" type="button" data-bs-toggle="modal"
 data-bs-target="#eventsModal">
 <i class="fa fa-th-list"></i> View Daily Data</button>
<button data-action="view-events" data-huc12="{$huc_12}" data-period="yearly"
 class="btn btn-sm btn-primary" type="button" data-bs-toggle="modal"
 data-bs-target="#eventsModal">
 <i class="fa fa-th-list"></i> View Yearly Data</button>
</p>
</form>
EOF;

/* Fetch Results */
echo "<h4>{$nicedate} Summary</h4>";
$rs = pg_prepare($dbconn, "RES", "select sum(qc_precip_mm) as qc_precip,
        sum(avg_runoff_mm) as avg_runoff, sum(avg_loss_kgm2) as avg_loss,
        sum(avg_delivery_kgm2) as avg_delivery from water_results_by_huc12 WHERE
        valid >= $1 and valid <= $2 and huc12_id = get_huc12_id($3, $4)
        and scenario_id = $4");
$rs = pg_execute($dbconn, "RES", array(
    date("Y-m-d", $date),
    date("Y-m-d", ($date2 == null) ? $date : $date2),
    $huc_12,
    $scenario
));
if (pg_num_rows($rs) == 0) {
    $row = array(
        "qc_precip" => 0,
        'avg_runoff' => 0,
        'avg_loss' => 0,
        'avg_delivery' => 0
    );
} else {
    $row = pg_fetch_assoc($rs, 0);
}
if ($metric == 0) {
    $row["qc_precip"] = $row["qc_precip"] / 25.4;
    $row["avg_runoff"] = $row["avg_runoff"] / 25.4;
    $row["avg_loss"] = $row["avg_loss"] * 4.46091345;
    $row["avg_delivery"] = $row["avg_delivery"] * 4.46091345;
    $punit = "inch";
    $lunit = "ton/acre";
} else {
    // Convert kg/m2 to tonnes/ha
    $row["avg_loss"] = $row["avg_loss"] * 10;
    $row["avg_delivery"] = $row["avg_delivery"] * 10;
    $punit = "mm";
    $lunit = "tonne/ha";
}
echo '<table class="table table-condensed table-bordered">';
echo "<tr><th>Precipitation</th><td>" . sprintf("%.2f %s", $row["qc_precip"], $punit) . "</td></tr>";
echo "<tr><th>Runoff</th><td>" . sprintf("%.2f %s", $row["avg_runoff"], $punit) . "</td></tr>";
echo "<tr><th>Detachment</th><td>" . sprintf("%.2f %s", $row["avg_loss"], $lunit) . "</td></tr>";
echo "<tr><th>Hillslope Soil Delivery</th><td>" . sprintf("%.2f %s", $row["avg_delivery"], $lunit) . "</td></tr>";
echo "</table>";

/* Get top events */
$rs = pg_prepare($dbconn, "TRES", "select valid from water_results_by_huc12 WHERE
        huc12_id = get_huc12_id($1, $2) and valid > '2007-01-01' and scenario_id = $2 and avg_loss_kgm2 > 0
        ORDER by avg_loss_kgm2 DESC LIMIT 10");
$rs = pg_execute($dbconn, "TRES", array($huc_12, $scenario));
if (pg_num_rows($rs) == 0) {
    echo "<br /><strong>Top events are missing!</strong>";
} else {
    echo "<h4>Top 10 Soil Loss Days:</h4>";
    echo "<table class=\"table table-condensed table-striped table-bordered\">";
    for ($i = 0; $row = @pg_fetch_assoc($rs, $i); $i++) {
        $ts = strtotime($row["valid"]);
        if ($i % 2 == 0) {
            echo "<tr>";
        }
        echo sprintf(
            "<td><span class=\"badge text-bg-secondary\">%s</span> <a href='#' data-action='set-date' data-year='%s' data-month='%s' data-day='%s'>%s</a></td>",
            $i + 1,
            date("Y", $ts),
            date("m", $ts),
            date("d", $ts),
            date("M j, Y", $ts)
        );
        if ($i % 2 == 1) {
            echo "</tr>\n";
        }
    }
    echo "</table>";
}
