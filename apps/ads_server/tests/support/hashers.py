from django.contrib.auth.hashers import Argon2PasswordHasher


class FastArgon2PasswordHasher(Argon2PasswordHasher):
    """테스트 전용: 알고리즘(argon2)은 같고 비용만 낮춘다."""

    time_cost = 1
    memory_cost = 8
    parallelism = 1
