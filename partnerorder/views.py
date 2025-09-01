from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.views.generic import ListView

from .mixins import VendorScopeQuerysetMixin
from injectionorder.models import InjectionOrder
from django.db.models import Sum
from injectionorder.models import InjectionOrder, STATUS_CHOICES

# --- 목록 ---
class OrderListView(VendorScopeQuerysetMixin, ListView):
    template_name = 'partnerorder/order_list.html'
    paginate_by = 50
    ordering = ['-order_date', '-id']

    def get_queryset(self):
        qs = super().get_queryset().select_related('vendor').prefetch_related('items')
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        dfrom = self.request.GET.get('from'); dto = self.request.GET.get('to')
        if dfrom: qs = qs.filter(order_date__gte=dfrom)
        if dto:   qs = qs.filter(order_date__lte=dto)
        return qs.annotate(qty_sum=Sum('items__quantity'))  # ← 수량합 주입

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # ('미입고','미입고') 형태의 choices에서 표시용 값만 꺼내 템플릿에 전달
        ctx['status_list'] = [label for value, label in STATUS_CHOICES]
        return ctx

# --- 배송등록(미입고/반출 -> 입고대기 + 시간 기록) ---
@login_required
def register_shipping(request, pk):
    if request.method != 'POST':
        return HttpResponseForbidden('POST only')
    order = get_object_or_404(InjectionOrder, pk=pk)

    # 협력사는 소유권 검증
    u = request.user
    if not getattr(u, 'is_internal', False) and order.vendor_id != getattr(u, 'vendor_id', None):
        return HttpResponseForbidden('권한 없음')

    if order.status in ('미입고', '반출'):
        order.status = '입고대기'
        order.shipping_registered_at = timezone.now()
        order.save(update_fields=['status', 'shipping_registered_at', 'updated_at'])
    return redirect('partner:order_list')

# --- QR 출력(선택행만) ---
import io, base64, json, qrcode
@login_required
def print_qr(request):
    ids = request.POST.getlist('ids')
    if not ids:
        return redirect('partner:order_list')

    qs = InjectionOrder.objects.filter(id__in=ids).select_related('vendor').prefetch_related('items')
    u = request.user
    if not getattr(u, 'is_internal', False):
        qs = qs.filter(vendor_id=getattr(u, 'vendor_id', None))

    cards = []
    for o in qs:
        qty_sum = o.items.aggregate(s=Sum('quantity'))['s'] or 0
        item_name = o.items.first().injection.name if o.items.exists() else ''  # injection 모델에 name 필드 가정
        payload = {
            "po": o.order_lot,
            "vendor": o.vendor.name,
            "issue_date": o.order_date.strftime('%Y-%m-%d'),
            "item": item_name,
            "qty": qty_sum,
            "due_date": (o.due_date.strftime('%Y-%m-%d') if o.due_date else ''),
        }
        img = qrcode.make(json.dumps(payload, ensure_ascii=False))
        buf = io.BytesIO(); img.save(buf, format='PNG')
        cards.append({"o": o, "qty_sum": qty_sum, "qr_b64": base64.b64encode(buf.getvalue()).decode()})

    return TemplateResponse(request, 'partnerorder/print_qr.html', {"cards": cards})
