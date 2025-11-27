# production/nfadd/views.py

from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.forms import inlineformset_factory
from django.shortcuts import get_object_or_404, redirect, render

from ..models import NonFerrousAddition, NonFerrousAdditionLine
from ..forms import NonFerrousAdditionForm, NonFerrousAdditionLineFormSet, NonFerrousAdditionLineForm

from process.models import Process, ProcessNonFerrous
from django.contrib import messages


# ============================================================
#  비철 투입일지 목록
#   - /production/nfadd/
#   - 공정별 필터, 일자 필터(선택)
# ============================================================
@login_required
def nfadd_list(request):
    qs = (
        NonFerrousAddition.objects
        .select_related("process", "created_by")
        .filter(is_active=True, dlt_yn="N")
        .order_by("-work_date", "-id")
    )

    process_id = request.GET.get("process")
    work_date_str = request.GET.get("work_date")

    # 공정 필터
    if process_id:
        try:
            qs = qs.filter(process_id=int(process_id))
        except ValueError:
            pass

    # 일자 필터 (YYYY-MM-DD 형식 가정)
    if work_date_str:
        try:
            year, month, day = map(int, work_date_str.split("-"))
            qs = qs.filter(work_date=date(year, month, day))
        except Exception:
            # 형식 이상하면 그냥 무시
            pass

    paginator = Paginator(qs, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # 공정 드롭다운용
    processes = Process.objects.all().order_by("display_order", "id")

    context = {
        "page_obj": page_obj,
        "additions": page_obj,  # 템플릿에서 for row in additions 로 써도 되게
        "processes": processes,
        "selected_process_id": process_id,
        "work_date": work_date_str,
    }
    return render(request, "production/nfadd/nfadd_list.html", context)


# ============================================================
#  비철 투입일지 신규 등록
#   - /production/nfadd/create/?process=<id>
#   - process에 매핑된 ProcessNonFerrous 기준으로 라인 initial 생성
# ============================================================
@login_required
def nfadd_create(request):
    """
    비철 투입일지 신규 등록

    - GET:
      * 선택한 공정(process)에 매핑된 ProcessNonFerrous 를 조회
      * 매핑 개수만큼 extra 를 갖는 inline formset 을 runtime 에 생성해서
        initial 로 비철 리스트를 채운다.
    - POST:
      * 기존 NonFerrousAdditionLineFormSet(전역 정의) 로 검증하고 저장
    """

    process_id = request.GET.get("process")
    initial_header = {"work_date": date.today()}

    # 공정 선택되어 있으면 헤더 초기값에도 process 세팅
    if process_id:
        try:
            initial_header["process"] = int(process_id)
        except (TypeError, ValueError):
            pass

    # ---------------- POST : 저장 처리 ----------------
    if request.method == "POST":
        form = NonFerrousAdditionForm(request.POST)
        formset = NonFerrousAdditionLineFormSet(
            request.POST,
            prefix="lines",
        )

        if form.is_valid() and formset.is_valid():
            addition = form.save(commit=False)
            addition.created_by = request.user
            addition.save()

            formset.instance = addition
            formset.save()

            messages.success(request, "비철 투입 정보가 저장되었습니다.")
            return redirect("production:nfadd:nfadd_edit", pk=addition.pk)

        # 에러 디버깅용 로그 (원하시면 주석 처리 가능)
        if not form.is_valid():
            print("=== [nfadd_create] form errors:", form.errors)
        if not formset.is_valid():
            print("=== [nfadd_create] formset errors:", formset.errors)

    # ---------------- GET : 신규 입력 화면 ----------------
    else:
        form = NonFerrousAdditionForm(initial=initial_header)

        # 1) 공정에 매핑된 비철 목록을 initial_lines 로 구성
        initial_lines = []

        if process_id:
            try:
                process_obj = Process.objects.get(pk=int(process_id))
            except (Process.DoesNotExist, TypeError, ValueError):
                process_obj = None
                print("=== [nfadd_create] Process not found for id:", process_id)
            else:
                print("=== [nfadd_create] Process loaded:",
                      process_obj.pk, getattr(process_obj, "name", ""))

            if process_obj is not None:
                qs = (
                    ProcessNonFerrous.objects
                    .select_related("nonferrous")
                    .filter(process=process_obj)
                    .order_by("order", "id")
                )

                print("=== [nfadd_create] ProcessNonFerrous SQL ===")
                print(qs.query)

                mappings = list(qs)
                print("=== [nfadd_create] mappings count:", len(mappings))

                for m in mappings:
                    nf = getattr(m, "nonferrous", None)
                    print(
                        "    mapping row -> id:",
                        m.pk,
                        "nonferrous_id:",
                        getattr(m, "nonferrous_id", None),
                        "nonferrous_name:",
                        getattr(nf, "name", None),
                    )

                    if nf is None:
                        continue

                    initial_lines.append(
                        {
                            "nonferrous": nf.pk,
                            "nonferrous_label": getattr(nf, "name", str(nf)),
                        }
                    )
        else:
            print("=== [nfadd_create] no process_id in GET")

        # 2) initial_lines 개수만큼 extra 를 갖는 formset 클래스를 runtime 에 생성
        extra_count = len(initial_lines)

        RuntimeLineFormSet = inlineformset_factory(
            NonFerrousAddition,
            NonFerrousAdditionLine,
            form=NonFerrousAdditionLineForm,
            extra=extra_count,   # 🔥 매핑 개수만큼 폼 생성
            can_delete=True,
        )

        # 3) initial 을 넘겨서 각 폼에 nonferrous / nonferrous_label 채우기
        formset = RuntimeLineFormSet(
            prefix="lines",
            initial=initial_lines,
        )

        # 디버그: 실제 formset 에 폼이 몇 개 생겼는지 확인 (원하면 로그만 보고 지워도 됨)
        print("=== [nfadd_create] formset.total_form_count():", formset.total_form_count())
        for i, f in enumerate(formset.forms):
            print(f"    form #{i} initial nonferrous =",
                  f.initial.get("nonferrous"),
                  ", label =", getattr(f, "nonferrous_label", None))

    context = {
        "form": form,
        "formset": formset,
        "object": None,
    }
    return render(request, "production/nfadd/nfadd_form.html", context)


# ============================================================
#  비철 투입일지 수정
#   - /production/nfadd/<pk>/edit/
# ============================================================
@login_required
def nfadd_edit(request, pk):
    """비철 투입일지 수정"""
    addition = get_object_or_404(NonFerrousAddition, pk=pk)

    if request.method == "POST":
        form = NonFerrousAdditionForm(request.POST, instance=addition)
        formset = NonFerrousAdditionLineFormSet(
            request.POST,
            prefix="lines",
            instance=addition,
        )

        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()

            # ✅ 수정 성공 메시지
            messages.success(request, "비철 투입 정보가 저장되었습니다.")

            # PRG 패턴: 새로고침 시 중복 POST 방지
            return redirect("production:nfadd:nfadd_edit", pk=addition.pk)
    else:
        form = NonFerrousAdditionForm(instance=addition)
        formset = NonFerrousAdditionLineFormSet(
            prefix="lines",
            instance=addition,
        )

    context = {
        "form": form,
        "formset": formset,
        "object": addition,
    }
    return render(request, "production/nfadd/nfadd_form.html", context)


# ============================================================
#  비철 투입일지 삭제
#   - /production/nfadd/<pk>/delete/
#   - 지금은 하드 delete, 필요시 soft delete 로 변경
# ============================================================
@login_required
def nfadd_delete(request, pk):
    addition = get_object_or_404(NonFerrousAddition, pk=pk)

    if request.method == "POST":
        addition.delete()
        return redirect("production:nfadd:nfadd_list")

    # GET 으로 직접 들어오면 목록으로 돌려보냄
    return redirect("production:nfadd:nfadd_list")
