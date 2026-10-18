# roles/edge/templates/edge-certbot-renew.service.j2

[역할 개요](../README.md) · [원본](../../../../../roles/edge/templates/edge-certbot-renew.service.j2)

oneshot 서비스에서 지정 IP lineage의 certbot renew를 실행한다. edge_domain이 있으면 도메인 lineage 갱신 ExecStart도 이어 실행한다. non-interactive·quiet·no-random-sleep-on-renew를 사용하며 deploy hook은 nginx -t 성공 후 reload한다. 기존 수동 game-domain-cert-renew.timer는 이 코드가 삭제하지 않는다. 자동 반복은 edge-certbot-renew.timer가 담당한다.
