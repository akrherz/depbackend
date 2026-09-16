Include /opt/iemwebfarm/config/vhost_common.conf

  DocumentRoot /opt/depbackend/htdocs
  ServerAdmin akrherz@iastate.edu

  # RewriteEngine is not enabled for vhosts by default
  RewriteEngine On

  Alias /static/ "/mnt/idep/2/data/static/"
  <Directory "/mnt/idep/2/data/static/">
  	Options Indexes MultiViews
  </Directory>

  Alias /usage/ "/mesonet/share/usage/depbackend/"
  <Directory "/mesonet/share/usage/depbackend/">
    Options Indexes MultiViews
    AllowOverride None
    Order allow,deny
    Allow from all
  </Directory>

  <Directory "/opt/depbackend/htdocs">
    Options Indexes FollowSymLinks
    AllowOverride None
    Require all granted

    WSGIProcessGroup iemwsgi_ap
    AddHandler wsgi-script .py
    Options +ExecCGI
  </Directory>

  <Directory "/opt/depbackend/htdocs/auto">
    RewriteRule ^([0-9]{4})([01][0-9])([0-3][0-9])_([0-9]{4})([01][0-9])([0-3][0-9])_([0-9]+)_(.*).png$ mapper.py?sdate=$1-$2-$3&edate=$4-$5-$6&scenario=$7&v=$8 [QSA]
    RewriteRule ^huc([0-9]{8,12})_([0-9]{4})([01][0-9])([0-3][0-9])_([0-9]{4})([01][0-9])([0-3][0-9])_([0-9]+)_(.*).png$ mapper.py?year=$2&month=$3&day=$4&year2=$5&month2=$6&day2=$7&scenario=$8&v=$9&huc=$1 [QSA]
    RewriteRule ^([0-9]{8,12})_report.pdf$ huc12report.py?huc=$1 [QSA]
    RewriteRule ^([0-9]{4})([0-9]{2})([0-9]{2})_([0-9]{4})([0-9]{2})([0-9]{2}).json$ huc12data.py?sdate=$1-$2-$3&edate=$4-$5-$6 [QSA]
    # Allow script.png to forward to script.py
    RewriteRule ^([A-Za-z0-9_-]+).png$ $1.py [QSA]
  </Directory>

  <Directory "/opt/depbackend/htdocs/geojson">
    SetOutputFilter DEFLATE
    RewriteRule ^huc12.geojson$ huc12_static.py
  </Directory>

  Alias "/admin" "/opt/depbackend/admin"
  <Directory "/opt/depbackend/admin">
        AuthUserFile /opt/iem/config/admin.users
        AuthGroupFile /dev/null
        AuthName Administrative
        AuthType Basic

        order deny,allow
        require user dep

    Options Indexes MultiViews FollowSymLinks
    AllowOverride All
  </Directory>

  <Directory "/opt/depbackend/admin/plots">
    RewriteRule "^slopes([0-9]+)_([0-9]{12})_([0-9A-Z]+).png$" "slopes.py?scenario=$1&huc_12=$2&model_twp=$3"
  </Directory>


  # http://enable-cors.org/server_apache.html
  Header set Access-Control-Allow-Origin "*"
