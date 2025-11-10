from django.db import migrations

def forwards(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        # 1) 사출 입고 라인: used_qty 기본값, use_status 일괄 보정
        cur.execute("UPDATE purchase_injectionreceiptline SET used_qty = COALESCE(used_qty, 0)")
        cur.execute("""
            UPDATE purchase_injectionreceiptline
            SET use_status = CASE
                WHEN used_qty <= 0 THEN '미사용'
                WHEN used_qty >= qty THEN '사용완료'
                ELSE '부분사용'
            END
        """)

        # 2) 통합(약품/비철/부자재) 입고: used_qty 기본값, use_status 일괄 보정
        cur.execute("UPDATE purchase_receipt SET used_qty = COALESCE(used_qty, 0)")
        cur.execute("""
            UPDATE purchase_receipt
            SET use_status = CASE
                WHEN used_qty <= 0 THEN '미사용'
                WHEN used_qty >= qty THEN '사용완료'
                ELSE '부분사용'
            END
        """)

def backwards(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        # 되돌림: 보수적으로 0/미사용 처리
        cur.execute("UPDATE purchase_injectionreceiptline SET used_qty = 0, use_status = '미사용'")
        cur.execute("UPDATE purchase_receipt SET used_qty = 0, use_status = '미사용'")

class Migration(migrations.Migration):

    dependencies = [
        ('purchase', '0014_add_usage_fields_and_ledgers'),  # 바로 직전 파일에 맞춰 주세요
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
