# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models

class Error(models.Model):
    """
    Store errors from gcd database.
    """
    class Meta:
        app_label = 'gcd'

    class Admin:
        pass

    error_key = models.CharField(primary_key=True, max_length=40, editable=False)
    error_text = models.TextField(null=True, blank=True)

    is_safe = models.BooleanField(default=False)

    def __unicode__(self):
        return self.error_text

