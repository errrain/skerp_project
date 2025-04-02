from django.shortcuts import render, get_object_or_404, redirect
from .models import Process, ProcessFile
from .forms import ProcessForm, ProcessFileForm
from django.core.paginator import Paginator
from django.http import FileResponse
from django.contrib.auth.decorators import login_required


@login_required
def process_list(request):
    search_name = request.GET.get('name', '')
    processes = Process.objects.all()
    if search_name:
        processes = processes.filter(name__icontains=search_name)

    paginator = Paginator(processes, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'process/process_list.html', {
        'page_obj': page_obj,
        'search_name': search_name,
    })


@login_required
def process_add(request):
    if request.method == 'POST':
        form = ProcessForm(request.POST)
        if form.is_valid():
            process = form.save()
            return redirect('process:process_edit', pk=process.pk)
    else:
        form = ProcessForm()
    return render(request, 'process/process_form.html', {
        'form': form,
        'files': [],
        'file_form': ProcessFileForm()
    })


@login_required
def process_edit(request, pk):
    process = get_object_or_404(Process, pk=pk)
    files = process.files.all().order_by('-created_at')

    if request.method == 'POST':
        if 'save_process' in request.POST:
            form = ProcessForm(request.POST, instance=process)
            if form.is_valid():
                form.save()
                return redirect('process:process_edit', pk=pk)
        elif 'upload_file' in request.POST:
            file_form = ProcessFileForm(request.POST, request.FILES)
            if file_form.is_valid():
                new_file = file_form.save(commit=False)
                new_file.process = process
                new_file.created_by = request.user.username
                new_file.note = file_form.cleaned_data['note']  # ✅ 비고 저장
                new_file.save()
                return redirect('process:process_edit', pk=pk)
    else:
        form = ProcessForm(instance=process)
        file_form = ProcessFileForm()

    return render(request, 'process/process_form.html', {
        'form': form,
        'files': files,
        'file_form': file_form,
        'process': process,
    })


@login_required
def process_delete(request, pk):
    process = get_object_or_404(Process, pk=pk)
    process.delete()
    return redirect('process:process_list')


@login_required
def process_file_update(request, process_id, file_id):
    file = get_object_or_404(ProcessFile, pk=file_id, process_id=process_id)
    if request.method == 'POST':
        file.note = request.POST.get('note', '')
        file.save()
    return redirect('process:process_edit', pk=process_id)


@login_required
def process_file_delete(request, process_id, file_id):
    file = get_object_or_404(ProcessFile, pk=file_id, process_id=process_id)
    file.delete()
    return redirect('process:process_edit', pk=process_id)


@login_required
def process_file_download(request, process_id):
    latest_file = ProcessFile.objects.filter(process_id=process_id).order_by('-created_at').first()
    if latest_file and latest_file.file:
        return FileResponse(latest_file.file.open('rb'), as_attachment=True, filename=latest_file.file.name)
    return redirect('process:process_edit', pk=process_id)
