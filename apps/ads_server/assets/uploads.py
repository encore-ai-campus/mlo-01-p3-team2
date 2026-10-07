from django.core.files.uploadhandler import FileUploadHandler, StopUpload

from django.conf import settings

OVERHEAD = 64 * 1024  # multipart 의 다른 필드·경계 문자열 여유


class MaxUploadSizeHandler(FileUploadHandler):
    """업로드 **전체 크기**가 상한을 크게 넘으면 파일을 디스크에 쌓기 전에 중단한다(위협 T16).

    Django 는 업로드 파일을 임시 파일로 먼저 받으므로, 이 핸들러가 없으면 큰 파일이 검증 전에 디스크를 채운다.
    FILE_UPLOAD_HANDLERS 의 맨 앞에 둔다.
    """

    def handle_raw_input(self, input_data, META, content_length, boundary, encoding=None):
        if content_length is not None and content_length > settings.ASSET_MAX_BYTES + OVERHEAD:
            raise StopUpload(connection_reset=True)

    def receive_data_chunk(self, raw_data, start):
        return raw_data  # 다음 핸들러가 처리한다

    def file_complete(self, file_size):
        return None
