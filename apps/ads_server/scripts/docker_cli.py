"""시험 스크립트가 쓰는 `docker` 명령 실행(계획 4-4k). 시간 제한은 부르는 쪽이 정한다(R5 — 클러스터 기동처럼 오래 걸리는 호출과 짧은 호출이 섞여 있다)."""
import subprocess


def docker(*args, timeout, check=True, input=None):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check, timeout=timeout, input=input)
