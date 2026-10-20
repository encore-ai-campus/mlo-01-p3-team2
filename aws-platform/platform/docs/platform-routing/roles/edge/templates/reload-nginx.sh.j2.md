# roles/edge/templates/reload-nginx.sh.j2

[역할 개요](../README.md) · [원본](../../../../../roles/edge/templates/reload-nginx.sh.j2)

Certbot deploy hook으로 /etc/letsencrypt/renewal-hooks/deploy/edge-nginx에 설치한다. 설정 검사 실패 시 종료하며 성공 후 nginx를 reload한다.
