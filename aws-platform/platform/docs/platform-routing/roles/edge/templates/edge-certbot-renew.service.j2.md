# roles/edge/templates/edge-certbot-renew.service.j2

[역할 개요](../README.md) · [원본](../../../../../roles/edge/templates/edge-certbot-renew.service.j2)

network-online 이후 지정 lineage만 certbot renew --non-interactive --quiet --no-random-sleep-on-renew로 갱신 확인한다. 단발 서비스이며 자동 반복은 timer가 맡는다.
