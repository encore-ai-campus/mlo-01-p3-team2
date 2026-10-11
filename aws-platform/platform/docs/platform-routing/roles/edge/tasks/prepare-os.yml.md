# roles/edge/tasks/prepare-os.yml

[역할 개요](../README.md) · [원본](../../../../../roles/edge/tasks/prepare-os.yml)

Ubuntu 24.04를 검사하고 ubuntu.sources의 공식 archive/security URI를 HTTPS로 바꾼다. ap-northeast-2.ec2.archive 같은 지역별 EC2 호스트도 HTTPS archive.ubuntu.com으로 정규화한다. 변경 전 파일은 백업한다.
