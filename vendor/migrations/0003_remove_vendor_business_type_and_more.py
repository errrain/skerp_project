# Generated by Django 5.1.7 on 2025-04-01 03:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vendor', '0002_rename_vendor_type_vendor_business_type_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='vendor',
            name='business_type',
        ),
        migrations.RemoveField(
            model_name='vendor',
            name='contact_person',
        ),
        migrations.RemoveField(
            model_name='vendor',
            name='outsourcing',
        ),
        migrations.AddField(
            model_name='vendor',
            name='manager_name',
            field=models.CharField(blank=True, max_length=50, null=True, verbose_name='담당자명'),
        ),
        migrations.AddField(
            model_name='vendor',
            name='outsourcing_type',
            field=models.CharField(choices=[('Y', '외주'), ('N', '자체')], default='N', max_length=1, verbose_name='외주구분'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='vendor',
            name='vendor_type',
            field=models.CharField(choices=[('corporate', '법인'), ('personal', '개인')], default='active', max_length=20, verbose_name='구분'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='vendor',
            name='fax',
            field=models.CharField(blank=True, max_length=20, null=True, verbose_name='대표 팩스'),
        ),
        migrations.AlterField(
            model_name='vendor',
            name='phone',
            field=models.CharField(blank=True, max_length=20, null=True, verbose_name='대표 전화'),
        ),
        migrations.AlterField(
            model_name='vendor',
            name='transaction_type',
            field=models.CharField(choices=[('buy', '매입'), ('sell', '매출'), ('both', '매입매출 병행')], max_length=20, verbose_name='거래구분'),
        ),
    ]
