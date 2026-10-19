"""외부 서버 접속 없이 도메인/IP 모드와 인증서 준비 단계를 검증한다."""
from pathlib import Path
import unittest
import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / 'roles/edge'
ENV = jinja2.Environment(undefined=jinja2.StrictUndefined, trim_blocks=True)
ENV.filters['bool'] = bool


def context(domain=True, ip_ready=True, domain_ready=True):
    # 실제 기본 변수를 읽고 Ansible에서 계산하는 값만 시험 입력으로 대체한다.
    data = yaml.safe_load((ROLE / 'defaults/main.yml').read_text())
    data.update(edge_public_ip='43.203.25.153', edge_cert_name='edge-ip-43.203.25.153',
                edge_domain='bootcampmetaverse.site' if domain else '',
                edge_domain_cert_name='bootcampmetaverse.site',
                edge_game_backend_host='10.10.10.166', edge_tls_ready=ip_ready,
                edge_domain_tls_ready=domain_ready, edge_http_redirect=domain,
                edge_frontend_mode=True, edge_https_allowed_cidrs=['222.112.208.69/32'],
                edge_frontend_upstreams=[{'host': '127.0.0.1' if domain else '10.10.10.20',
                                          'port': 8004 if domain else 8000}])
    return data


def render(name, **kwargs):
    return ENV.from_string((ROLE / 'templates' / name).read_text()).render(context(**kwargs))


class EdgeDomainTests(unittest.TestCase):
    def test_domain_routes_and_access(self):
        text = render('nginx.conf.j2')
        self.assertEqual(text.count('listen 443 ssl'), 2)
        self.assertEqual(text.count('return 308 https://bootcampmetaverse.site$request_uri'), 2)
        for value in ('server 127.0.0.1:8004', 'location /ws/campus/',
                      'proxy_pass http://10.10.10.166:8000;', 'location /static/',
                      'allow 222.112.208.69/32;', 'deny all;', 'ads_disabled'):
            self.assertIn(value, text)
        self.assertNotIn('allow 0.0.0.0/0', text)
        self.assertIn('/live/bootcampmetaverse.site/fullchain.pem', text)
        self.assertIn('/live/edge-ip-43.203.25.153/fullchain.pem', text)

    def test_initial_install_has_no_missing_certificate_reference(self):
        text = render('nginx.conf.j2', ip_ready=False, domain_ready=False)
        self.assertNotIn('ssl_certificate', text)
        self.assertIn('/.well-known/acme-challenge/', text)

    def test_migration_keeps_ip_tls_until_domain_ready(self):
        text = render('nginx.conf.j2', domain_ready=False)
        self.assertEqual(text.count('listen 443 ssl'), 1)
        self.assertNotIn('/live/bootcampmetaverse.site/', text)

    def test_ad_front_remains_ip_based(self):
        text = render('nginx.conf.j2', domain=False)
        self.assertEqual(text.count('listen 443 ssl'), 1)
        self.assertIn('server 10.10.10.20:8000', text)
        self.assertIn('location / { return 404; }', text)
        self.assertNotIn('bootcampmetaverse.site', text)
        self.assertNotIn('location /ws/campus/', text)

    def test_both_certificates_are_renewed_only_for_domain_mode(self):
        self.assertEqual(render('edge-certbot-renew.service.j2').count('ExecStart='), 2)
        self.assertEqual(render('edge-certbot-renew.service.j2', domain=False).count('ExecStart='), 1)

    def test_role_yaml_parses(self):
        for path in ROLE.rglob('*.yml'):
            yaml.safe_load(path.read_text())


if __name__ == '__main__':
    unittest.main()
