# -*- coding: utf-8 -*-
# Generated by Django 1.11.16 on 2019-05-30 09:13


from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('gcd', '0015_cleanup_award_migration'),
        ('oi', '0016_cleanup_award_migration'),
    ]

    operations = [
        migrations.DeleteModel(
            name='CreatorAward',
        ),
    ]
