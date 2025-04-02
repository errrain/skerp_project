# core/utils.py

from django.shortcuts import redirect
from functools import wraps

def check_permission(menu_code):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            user = request.user
            # 관리자는 모든 접근 허용
            if user.is_authenticated and getattr(user, 'level', '') == 'admin':
                return view_func(request, *args, **kwargs)

            # accessible_menus를 통한 권한 확인
            if user.is_authenticated and hasattr(user, 'accessible_menus'):
                if user.accessible_menus.filter(code=menu_code).exists():
                    return view_func(request, *args, **kwargs)

            # 권한 없음 → 대시보드로 리디렉션
            return redirect('dashboard')  # 또는 권한 없음 페이지
        return _wrapped_view
    return decorator
