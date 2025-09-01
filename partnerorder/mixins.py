#partnerorder/mixins.py

from django.contrib.auth.mixins import LoginRequiredMixin
from injectionorder.models import InjectionOrder

class VendorScopeQuerysetMixin(LoginRequiredMixin):
    """사내: 전체 / 협력사: 자사만"""
    model = InjectionOrder

    def get_queryset(self):
        qs = super().get_queryset()
        u = self.request.user
        return qs if getattr(u, 'is_internal', False) else qs.filter(vendor_id=getattr(u, 'vendor_id', None))
