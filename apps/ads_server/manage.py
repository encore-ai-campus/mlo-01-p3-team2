#!/usr/bin/env python
import os
import sys


def main():
    from config.env import load_env

    load_env()
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # 테스트는 항상 test 설정. `.env`가 DJANGO_SETTINGS_MODULE 을 지정해도 덮어쓴다(--settings 는 그 뒤에 적용된다).
        os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test"
    else:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
