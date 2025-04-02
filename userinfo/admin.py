# userinfo/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser


class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ('username', 'full_name', 'department', 'level', 'status', 'is_active', 'last_login')
    list_filter = ('department', 'level', 'status', 'is_active')
    search_fields = ('username', 'full_name', 'email', 'department')

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('개인 정보', {'fields': ('full_name', 'email', 'phone', 'department')}),
        ('권한 정보',
         {'fields': ('level', 'status', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('로그인 정보', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
            'username', 'full_name', 'password1', 'password2', 'email', 'phone', 'department', 'level', 'status',
            'is_active')}
         ),
    )


admin.site.register(CustomUser, CustomUserAdmin)
