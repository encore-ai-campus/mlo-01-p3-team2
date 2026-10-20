"""호출자가 설정·HTTP·연결·응답 오류를 구분할 수 있는 예외."""


class AdsError(Exception):
    """광고 통신 실패의 공통 예외. 원본 요청과 인증 키는 보관하지 않는다."""


class AdsHTTPError(AdsError):
    def __init__(self, status: int, *, code: str | None = None,
                 request_id: str | None = None, retry_after: int | None = None) -> None:
        self.status = status
        self.code = code
        self.request_id = request_id
        self.retry_after = retry_after
        # 서버 본문을 예외 문자열로 복사하지 않는다. 조사에 필요한 값만 별도 속성으로 제공한다.
        super().__init__(f"광고 서버가 HTTP {status}로 응답했습니다.")


class AdsTransportError(AdsError):
    """타임아웃·연결 실패. 서버가 요청을 처리했는지는 확인할 수 없다."""


class AdsResponseError(AdsError):
    def __init__(self, message: str, *, request_id: str | None = None,
                 acknowledged: bool = False) -> None:
        self.request_id = request_id
        # 반응 PUT에서 2xx를 확인했다면 본문이 손상돼도 접수 사실을 잃지 않는다.
        self.acknowledged = acknowledged
        super().__init__(message)
