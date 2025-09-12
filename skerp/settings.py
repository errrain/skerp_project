"""
Django settings for skerp project.
Django 5.1.x
"""

from pathlib import Path
from datetime import date
import os

# ─────────────────────────────────────────────────────────
# 경로
# ─────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

# ─────────────────────────────────────────────────────────
# 환경변수 헬퍼
# ─────────────────────────────────────────────────────────
def env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")

def env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default)

# ─────────────────────────────────────────────────────────
# 보안/기본
# ─────────────────────────────────────────────────────────
# 운영에서는 DJANGO_SECRET_KEY 환경변수를 반드시 설정하세요.
SECRET_KEY = env_str(
    "DJANGO_SECRET_KEY",
    # ↓ 기존 파일의 키를 기본값으로 둬서, 당장 개발환경에서 깨지지 않게 함
    "django-insecure-qjl-2e_i2=feun@g7f%2i6=a2^e3r)*zs4^2=-h(t*!=3m84@_",
)

DEBUG = env_bool("DJANGO_DEBUG", True)

# 쉼표로 구분: "example.com,.example.com,localhost,127.0.0.1"
ALLOWED_HOSTS = [h.strip() for h in env_str("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()]


DUMMY_PRODUCT_ID = 1   # 존재하는 제품 PK
DUMMY_CUSTOMER_ID = 1  # 존재하는 고객사 PK

# ─────────────────────────────────────────────────────────
# 애플리케이션
# ─────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",

    "main",
    "userinfo",
    "board",
    "core",
    "master",
    "resource",
    "sales",            # 영업
    "purchase",         # 구매 (사출 발주 포함)
    "production",       # 생산
    "quality",          # 품질
    "lab",              # 연구실
    "support",          # 경영지원
    "widget_tweaks",
    "vendor",           # 기초코드: 거래처
    "mastercode",       # 기초코드: 코드관리
    "equipment",        # 기초코드: 생산설비관리
    "process",          # 기초코드: 공정항목관리
    "spec",             # 기초코드: 제조사항관리
    "qualityitems",     # 기초코드: 품질관리항목관리
    "product",          # 자원: 제품관리
    "injection",        # 자원: 사출관리
    "chemical",         # 자원: 약품관리
    "nonferrous",       # 자원: 비철관리
    "submaterial",      # 자원: 부자재관리
    "rack",             # 자원: 랙 관리
    "injectionorder",   # 구매: 사출 발주
    "partnerorder",     # 협력사: 발주 처리
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "skerp.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # 필요 시 템플릿 디렉토리 추가: BASE_DIR / "templates"
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "skerp.wsgi.application"

# ─────────────────────────────────────────────────────────
# 데이터베이스
# ─────────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env_str("POSTGRES_DB", "skerp_db"),
        "USER": env_str("POSTGRES_USER", "skerp_user"),
        "PASSWORD": env_str("POSTGRES_PASSWORD", "kwc8264***"),
        "HOST": env_str("POSTGRES_HOST", "localhost"),
        "PORT": env_str("POSTGRES_PORT", "5432"),
    }
}

# ─────────────────────────────────────────────────────────
# 비밀번호 정책
# ─────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ─────────────────────────────────────────────────────────
# 국제화/시간대
# ─────────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True

# 현재 프로젝트는 naive datetime을 사용(USE_TZ=False).
# (views에서 _today_local()로 안전처리함)
USE_TZ = env_bool("DJANGO_USE_TZ", False)

# ─────────────────────────────────────────────────────────
# 정적/미디어
# ─────────────────────────────────────────────────────────
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "core" / "static"]
# 배포 시 collectstatic 대상
STATIC_ROOT = env_str("DJANGO_STATIC_ROOT", str(BASE_DIR / "staticfiles"))

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ─────────────────────────────────────────────────────────
# 사용자/기본 설정
# ─────────────────────────────────────────────────────────
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_REDIRECT_URL = "/dashboard/"
AUTH_USER_MODEL = "userinfo.CustomUser"

# ─────────────────────────────────────────────────────────
# 보안 (운영 시 권장)
# ─────────────────────────────────────────────────────────
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", not DEBUG)
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0" if DEBUG else "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", not DEBUG)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)

# ─────────────────────────────────────────────────────────
# 로깅 (회전 + 포맷 + SQL 분리)
# ─────────────────────────────────────────────────────────
LOG_DIR = BASE_DIR / "logs"
os.makedirs(LOG_DIR, exist_ok=True)

APP_LOG_LEVEL = os.environ.get("APP_LOG_LEVEL", "DEBUG" if DEBUG else "INFO").upper()
SQL_DEBUG = env_bool("DJANGO_SQL_DEBUG", False)

TODAY_LOG = LOG_DIR / f"app_{date.today():%Y-%m-%d}.log"
SQL_LOG   = LOG_DIR / f"sql_{date.today():%Y-%m-%d}.log"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "[{asctime}] {levelname:>7} {name} - {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "concise": {"format": "{levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "concise"},
        "app_file": {
            "class": "logging.FileHandler",
            "filename": str(TODAY_LOG),
            "encoding": "utf-8",
            "formatter": "standard",
        },
        "sql_file": {
            "class": "logging.FileHandler",
            "filename": str(SQL_LOG),
            "encoding": "utf-8",
            "formatter": "standard",
        },
    },
    "root": {"handlers": ["console", "app_file"], "level": APP_LOG_LEVEL},
    "loggers": {
        "django.request": {"handlers": ["console", "app_file"], "level": "WARNING", "propagate": False},
        "django.server":  {"handlers": ["console"], "level": "WARNING", "propagate": False},  # ← 404 잡음 줄임
        "django.security": {"handlers": ["console", "app_file"], "level": "WARNING", "propagate": False},
        "django.db.backends": {
            "handlers": ["sql_file"],
            "level": ("DEBUG" if SQL_DEBUG else "WARNING"),
            "propagate": False,
        },
    },
}
