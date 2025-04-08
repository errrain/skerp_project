from django.shortcuts import render, get_object_or_404, redirect
from .models import Product, ProductPrice
from .forms import ProductForm, ProductPriceForm
from django.core.paginator import Paginator
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q

def product_list(request):
    search_name = request.GET.get('name', '')
    search_program = request.GET.get('program_name', '')
    search_status = request.GET.get('status', '')

    products = Product.objects.filter(delete_yn='N')

    if search_name:
        products = products.filter(name__icontains=search_name)
    if search_program:
        products = products.filter(program_name__icontains=search_program)
    if search_status:
        products = products.filter(status=search_status)

    paginator = Paginator(products.order_by('-id'), 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'name': search_name,
        'program_name': search_program,
        'status': search_status,
    }
    return render(request, 'product/product_list.html', context)


def product_add(request):
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save(commit=False)
            product.created_by = request.user.username
            product.updated_by = request.user.username
            product.save()
            return redirect('product:product_list')
    else:
        form = ProductForm()
    return render(request, 'product/product_form.html', {'form': form})


def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            print("✅ 폼 유효성 검사 통과")
            print("📝 저장 예정 데이터:", form.cleaned_data)
            product = form.save(commit=False)
            product.updated_by = request.user.username
            product.save()
            return redirect('product:product_list')
        else:
            print("❌ 폼 유효성 검사 실패")
            print(form.errors)
    else:
        form = ProductForm(instance=product)
    return render(request, 'product/product_form.html', {'form': form})



def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        product.delete_yn = 'Y'
        product.save()
        return redirect('product:product_list')
    return render(request, 'product/product_confirm_delete.html', {'product': product})

def product_price_view(request, pk):
    product = get_object_or_404(Product, pk=pk)

    # 기본정보 미저장 상태 체크
    if not product.id:
        messages.warning(request, "제품을 먼저 등록완료하세요.")
        return redirect('product:product_list')

    # 현재 단가 = 가장 최근 등록된 단가
    latest_price = product.prices.first()

    # 단가 등록 처리
    if request.method == 'POST':
        form = ProductPriceForm(request.POST)
        if form.is_valid():
            price = form.save(commit=False)
            price.product = product
            price.created_by = request.user.username
            price.save()
            return redirect('product:product_price', pk=product.pk)
    else:
        form = ProductPriceForm(initial={
            'date': timezone.now().strftime('%Y-%m-%dT%H:%M')  # HTML5 datetime-local 형식
        })

    context = {
        'product': product,
        'latest_price': latest_price,
        'price_list': product.prices.all(),  # 최신순 정렬됨
        'form': form,
    }
    return render(request, 'product/product_price.html', context)
