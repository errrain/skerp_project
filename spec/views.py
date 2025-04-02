from django.shortcuts import render, get_object_or_404, redirect
from .models import Spec
from .forms import SpecForm
from django.core.paginator import Paginator
from django.db.models import Q

def spec_list(request):
    query = request.GET.get('q', '')
    spec_list = Spec.objects.all()
    if query:
        spec_list = spec_list.filter(description__icontains=query)

    paginator = Paginator(spec_list, 10)
    page = request.GET.get('page')
    specs = paginator.get_page(page)

    return render(request, 'spec/spec_list.html', {
        'specs': specs,
        'query': query,
    })

def spec_add(request):
    if request.method == 'POST':
        form = SpecForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('spec:spec_list')
    else:
        form = SpecForm()
    return render(request, 'spec/spec_form.html', {'form': form})

def spec_edit(request, pk):
    spec = get_object_or_404(Spec, pk=pk)
    if request.method == 'POST':
        form = SpecForm(request.POST, request.FILES, instance=spec)
        if form.is_valid():
            form.save()
            return redirect('spec:spec_list')
    else:
        form = SpecForm(instance=spec)
    return render(request, 'spec/spec_form.html', {'form': form, 'spec': spec})

def spec_delete(request, pk):
    spec = get_object_or_404(Spec, pk=pk)
    spec.delete()
    return redirect('spec:spec_list')
