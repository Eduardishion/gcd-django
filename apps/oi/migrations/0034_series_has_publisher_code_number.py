# Generated by Django 2.2.12 on 2021-02-06 10:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('oi', '0033_publisher_code_number'),
    ]

    operations = [
        migrations.AddField(
            model_name='seriesrevision',
            name='has_publisher_code_number',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='characterrevision',
            name='description',
            field=models.TextField(blank=True, help_text='concise description, including background and premise'),
        ),
        migrations.AlterField(
            model_name='characterrevision',
            name='disambiguation',
            field=models.CharField(blank=True, db_index=True, help_text='if needed add a short phrase for disambiguation', max_length=255),
        ),
        migrations.AlterField(
            model_name='grouprevision',
            name='description',
            field=models.TextField(blank=True, help_text='concise description, including background and premise'),
        ),
        migrations.AlterField(
            model_name='grouprevision',
            name='disambiguation',
            field=models.CharField(blank=True, db_index=True, help_text='if needed add a short phrase for disambiguation', max_length=255),
        ),
        migrations.AlterField(
            model_name='publishercodenumberrevision',
            name='number',
            field=models.CharField(db_index=True, help_text='structured publisher code number, from cover or indicia', max_length=50),
        ),
    ]
