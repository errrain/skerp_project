# Generated by Django 5.1.7 on 2025-04-09 08:44

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('injection', '0002_injectionprice_moldhistory'),
        ('vendor', '0004_alter_vendor_outsourcing_type'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='moldhistory',
            name='created_by',
        ),
        migrations.RemoveField(
            model_name='moldhistory',
            name='injection',
        ),
        migrations.RemoveField(
            model_name='injection',
            name='spec',
        ),
        migrations.AddField(
            model_name='injection',
            name='created_by',
            field=models.CharField(blank=True, max_length=50, null=True, verbose_name='생성자'),
        ),
        migrations.AddField(
            model_name='injection',
            name='created_dt',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now, verbose_name='생성일시'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='injection',
            name='cycle_time',
            field=models.CharField(blank=True, max_length=50, null=True, verbose_name='CYCLETIME'),
        ),
        migrations.AddField(
            model_name='injection',
            name='program_name',
            field=models.CharField(default='미정', max_length=200, verbose_name='프로그램명'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='injection',
            name='ton',
            field=models.CharField(blank=True, max_length=50, null=True, verbose_name='사출기 톤수'),
        ),
        migrations.AddField(
            model_name='injection',
            name='updated_by',
            field=models.CharField(blank=True, max_length=50, null=True, verbose_name='수정자'),
        ),
        migrations.AddField(
            model_name='injection',
            name='updated_dt',
            field=models.DateTimeField(auto_now=True, verbose_name='수정일시'),
        ),
        migrations.AddField(
            model_name='injection',
            name='weight',
            field=models.CharField(blank=True, max_length=50, null=True, verbose_name='Weight (g)'),
        ),
        migrations.AlterField(
            model_name='injection',
            name='alias',
            field=models.CharField(blank=True, max_length=200, null=True, verbose_name='별칭'),
        ),
        migrations.AlterField(
            model_name='injection',
            name='delete_yn',
            field=models.CharField(choices=[('Y', '삭제'), ('N', '정상')], default='N', max_length=1, verbose_name='삭제여부'),
        ),
        migrations.AlterField(
            model_name='injection',
            name='material',
            field=models.CharField(blank=True, choices=[('ABS', 'ABS'), ('PC-ABS', 'PC-ABS')], max_length=50, null=True, verbose_name='소재'),
        ),
        migrations.AlterField(
            model_name='injection',
            name='use_yn',
            field=models.CharField(choices=[('Y', '사용'), ('N', '미사용')], default='Y', max_length=1, verbose_name='사용여부'),
        ),
        migrations.AlterField(
            model_name='injection',
            name='vendor',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='vendor.vendor', verbose_name='사출사'),
        ),
        migrations.DeleteModel(
            name='InjectionPrice',
        ),
        migrations.DeleteModel(
            name='MoldHistory',
        ),
    ]
