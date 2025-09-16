#vendor/views.py
from django.shortcuts import render, redirect, get_object_or_404
from .models import Vendor
from .forms import VendorForm
from django.core.paginator import Paginator

def vendor_list(request):
    vendors = Vendor.objects.all()

    # 필터 검색값 수집
    name = request.GET.get('name', '')
    outsourcing_type = request.GET.get('outsourcing_type', '')
    status = request.GET.get('status', '')
    page_size = request.GET.get('page_size', 10)

    if name:
        vendors = vendors.filter(name__icontains=name)
    if outsourcing_type:
        vendors = vendors.filter(outsourcing_type=outsourcing_type)
    if status == 'active':
        vendors = vendors.filter(status='active')
    elif status == 'inactive':
        vendors = vendors.filter(status='inactive')

    # ✅ 페이지 크기 설정
    try:
        page_size = int(page_size)
    except ValueError:
        page_size = 10

    paginator = Paginator(vendors, page_size)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'vendors': page_obj,
        'page_obj': page_obj,
        'name': name,
        'outsourcing_type': outsourcing_type,
        'status': status,
        'page_size': page_size,
    }
    return render(request, 'vendor/vendor_list.html', context)


def vendor_create(request):
    if request.method == 'POST':
        form = VendorForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('vendor:vendor_list')
    else:
        form = VendorForm()
    return render(request, 'vendor/vendor_form.html', {'form': form})


def vendor_edit(request, pk):
    vendor = get_object_or_404(Vendor, pk=pk)
    if request.method == 'POST':
        form = VendorForm(request.POST, instance=vendor)
        if form.is_valid():
            form.save()
            return redirect('vendor:vendor_list')
    else:
        form = VendorForm(instance=vendor)
    return render(request, 'vendor/vendor_form.html', {'form': form})


def vendor_delete(request, pk):
    vendor = get_object_or_404(Vendor, pk=pk)
    vendor.delete()
    return redirect('vendor:vendor_list')
