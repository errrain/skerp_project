from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
from .models import Submaterial, SubmaterialPrice
from .forms import SubmaterialForm, SubmaterialPriceForm

def submaterial_list(request):
    query = request.GET.get('q', '')
    use_yn = request.GET.get('use_yn', '')
    customer = request.GET.get('customer', '')

    items = Submaterial.objects.filter(delete_yn='N')
    if query:
        items = items.filter(Q(name__icontains=query) | Q(spec__icontains=query))
    if use_yn:
        items = items.filter(use_yn=use_yn)
    if customer:
        items = items.filter(customer__name__icontains=customer)

    paginator = Paginator(items.order_by('-id'), 10)
    page = request.GET.get('page')
    page_obj = paginator.get_page(page)

    return render(request, 'submaterial/submaterial_list.html', {
        'page_obj': page_obj,
        'query': query,
        'use_yn': use_yn,
        'customer': customer,
    })

def submaterial_add(request):
    if request.method == 'POST':
        form = SubmaterialForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('submaterial:submaterial_list')
        else:
            print("❌ 폼 유효성 검사 실패")
            print(form.errors)  # <- 폼 에러 출력
    else:
        form = SubmaterialForm()
    return render(request, 'submaterial/submaterial_form.html', {'form': form})

def submaterial_edit(request, pk):
    item = get_object_or_404(Submaterial, pk=pk)
    if request.method == 'POST':
        form = SubmaterialForm(request.POST, request.FILES, instance=item)
        if form.is_valid():
            form.save()
            return redirect('submaterial:submaterial_list')
    else:
        form = SubmaterialForm(instance=item)
    return render(request, 'submaterial/submaterial_form.html', { 'form': form })

def submaterial_delete(request, pk):
    item = get_object_or_404(Submaterial, pk=pk)
    item.delete_yn = 'Y'
    item.save()
    return redirect('submaterial:submaterial_list')

def submaterial_price_view(request, pk):
    item = get_object_or_404(Submaterial, pk=pk)
    if not item.pk:
        return render(request, 'submaterial/submaterial_price.html', {
            'form': SubmaterialPriceForm(),
            'price_list': [],
            'item': item,
            'latest_price': None,
        })

    latest_price = item.prices.order_by('-date').first()
    price_list = item.prices.all()

    if request.method == 'POST':
        form = SubmaterialPriceForm(request.POST)
        if form.is_valid():
            new_price = form.save(commit=False)
            new_price.submaterial = item
            new_price.created_by = request.user.username
            new_price.created_dt = timezone.now()
            new_price.save()
            return redirect('submaterial:submaterial_price', pk=pk)
    else:
        form = SubmaterialPriceForm(initial={'date': timezone.now()})

    return render(request, 'submaterial/submaterial_price.html', {
        'form': form,
        'price_list': price_list,
        'item': item,
        'latest_price': latest_price,
    })
