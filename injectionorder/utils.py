# injectionorder/utils.py

from django.utils import timezone
from .models import InjectionOrder

def generate_order_lot():
    today = timezone.now().strftime("%Y%m%d")
    count = InjectionOrder.objects.filter(order_lot__startswith=f"ORD{today}").count() + 1
    return f"ORD{today}{str(count).zfill(3)}"