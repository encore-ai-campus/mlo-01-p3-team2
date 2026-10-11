# roles/edge/templates/edge-certbot-renew.timer.j2

[역할 개요](../README.md) · [원본](../../../../../roles/edge/templates/edge-certbot-renew.timer.j2)

OnCalendar=hourly, RandomizedDelaySec=15m, Persistent=true다. 켜지지 않은 시간의 실행을 보충하고 매시간 갱신 필요 여부를 확인한다.
