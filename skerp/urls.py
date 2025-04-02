"""
URL configuration for skerp project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    # path('', include('core.urls')),
    # path('userinfo/', include('userinfo.urls')),
    # path('board/', include('board.urls')),
    path('', include('core.urls')),
    path('master/', include('master.urls')),
    path('userinfo/', include('userinfo.urls')),        # ✅ 사용자 정보 URL 등록
    path('vendor/', include('vendor.urls')),            # ✅ 거래처 정보 URL 등록
    path('mastercode/', include('mastercode.urls')),    # ✅ 코드관리 정보 URL 등록
    path('equipment/', include('equipment.urls')),      # ✅ 설비관리 정보 URL 등록
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
