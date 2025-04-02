# userinfo/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models

USER_LEVEL_CHOICES = [
    ('admin', '관리자'),
    ('user', '사용자'),
]

USER_STATUS_CHOICES = [
    ('pending', '대기'),
    ('active', '승인'),
]

class CustomUser(AbstractUser):
    full_name = models.CharField('이름', max_length=50)
    department = models.CharField('부서', max_length=100)
    level = models.CharField('레벨', max_length=10, choices=USER_LEVEL_CHOICES, default='user')
    status = models.CharField('상태', max_length=10, choices=USER_STATUS_CHOICES, default='pending')
    phone = models.CharField('전화번호', max_length=20, blank=True, null=True)
    email = models.EmailField('이메일', unique=True)
    last_login = models.DateTimeField('마지막 로그인', blank=True, null=True)

    def __str__(self):
        return self.username
