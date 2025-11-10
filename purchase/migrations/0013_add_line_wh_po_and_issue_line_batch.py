from django.db import migrations, models
import django.db.models.deletion
import uuid


def forward_fill_line_warehouse(apps, schema_editor):
    """
    기존 라인(서브 LOT)의 현재 창고를 헤더의 창고로 초기 채움.
    (이번에 새로 추가된 line.warehouse를 안전하게 기본값 세팅)
    """
    InjectionReceiptLine = apps.get_model("purchase", "InjectionReceiptLine")
    for ln in InjectionReceiptLine.objects.select_related("receipt").all():
        if ln.warehouse_id is None and ln.receipt_id and ln.receipt_id is not None:
            ln.warehouse_id = ln.receipt.warehouse_id
            ln.save(update_fields=["warehouse"])


def backward_noop(apps, schema_editor):
    # 되돌릴 필요 없음 (필드 삭제 시 Django가 알아서 처리)
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("purchase", "0012_enforce_notnull_step2"),
        ("master", "0001_initial"),
    ]

    operations = [
        # ─────────────────────────────────────────────────────────────────────
        # 1) InjectionReceiptLine(서브 LOT 라인)에 현재 창고/PO 키 추가
        # ─────────────────────────────────────────────────────────────────────
        migrations.AddField(
            model_name="injectionreceiptline",
            name="warehouse",
            field=models.ForeignKey(
                related_name="inj_receipt_lines",
                null=True, blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="master.warehouse",
            ),
        ),
        migrations.AddField(
            model_name="injectionreceiptline",
            name="po_lot",
            field=models.CharField(max_length=50, null=True, blank=True, db_index=True),
        ),
        migrations.AddField(
            model_name="injectionreceiptline",
            name="po_part",
            field=models.CharField(max_length=20, null=True, blank=True, db_index=True),
        ),
        # 복합 인덱스 (QR 파싱 후 검색 대비)
        migrations.AddIndex(
            model_name="injectionreceiptline",
            index=models.Index(fields=["po_lot", "po_part"], name="injrec_line_polot_part_idx"),
        ),

        # ─────────────────────────────────────────────────────────────────────
        # 2) InjectionIssue(이동 이력)에 라인 FK + 배치ID 추가
        # ─────────────────────────────────────────────────────────────────────
        migrations.AddField(
            model_name="injectionissue",
            name="receipt_line",
            field=models.ForeignKey(
                related_name="issues",
                null=True, blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="purchase.injectionreceiptline",
            ),
        ),
        migrations.AddField(
            model_name="injectionissue",
            name="batch_id",
            field=models.UUIDField(null=True, blank=True, db_index=True, default=None),
            preserve_default=False,
        ),

        # ─────────────────────────────────────────────────────────────────────
        # 3) 데이터 마이그레이션: 라인.warehouse = 헤더.warehouse
        # ─────────────────────────────────────────────────────────────────────
        migrations.RunPython(forward_fill_line_warehouse, backward_noop),
    ]
