; /etc/bind/zones/db.ai.kilop.ru на хосте; named.conf.local:
;   zone "ai.kilop.ru" { type master; file "/etc/bind/zones/db.ai.kilop.ru"; allow-update { none; }; };
; NS-делегация ai.kilop.ru -> этот сервер (glue: ns1.ai.kilop.ru = 151.252.106.119)
$TTL    300
@   IN  SOA ns1.ai.kilop.ru. admin.kilop.ru. (
        2026102301 ; serial — увеличивать при правке!
        3600 600 86400 300 )
@   IN  NS  ns1.ai.kilop.ru.
@   IN  A   151.252.106.119
ns1 IN  A   151.252.106.119
*   IN  A   151.252.106.119
