# -*- coding: utf-8 -*-

from __future__ import unicode_literals

import os
from string import capitalize

from django.db import models
from django.conf import settings
from django.contrib.contenttypes import models as content_models
from django.contrib.contenttypes import fields as generic_fields
from django.core import urlresolvers

from imagekit.models import ImageSpecField
from imagekit.processors import ResizeToFit

from .gcddata import GcdData
from apps.oi import states


class ImageType(models.Model):
    class Meta:
        app_label = 'gcd'
        db_table = 'gcd_image_type'

    name = models.CharField(max_length=50, db_index=True, unique=True)
    unique = models.BooleanField(default=True)
    description = models.CharField(max_length=255)

    def __unicode__(self):
        return self.name


# we need to save the model instance first without a file to get an id and
# then save the file
def get_generic_image_path(instance, filename):
    return os.path.join(settings.GENERIC_IMAGE_DIR,
                        str(int(instance.id/1000)),
                        filename)


class Image(GcdData):
    class Meta:
        app_label = 'gcd'
        db_table = 'gcd_image'

    content_type = models.ForeignKey(content_models.ContentType, null=True)
    object_id = models.PositiveIntegerField(db_index=True, null=True)
    object = generic_fields.GenericForeignKey('content_type', 'object_id')

    type = models.ForeignKey(ImageType)

    image_file = models.ImageField(upload_to=get_generic_image_path)
    scaled_image = ImageSpecField([ResizeToFit(width=400)],
                                  source='image_file',
                                  format='JPEG',
                                  options={'quality': 90})
    thumbnail = ImageSpecField([ResizeToFit(height=50)],
                               source='image_file',
                               format='JPEG',
                               options={'quality': 90})
    icon = ImageSpecField([ResizeToFit(height=30)],
                          source='image_file',
                          format='JPEG',
                          options={'quality': 90})

    marked = models.BooleanField(default=False)

    def deletable(self):
        return self.revisions.filter(changeset__state__in=states.ACTIVE)\
                             .count() == 0

    def description(self):
        return u'%s for %s' % (self.type.description, unicode(self.object))

    def get_absolute_url(self):
        if self.content_type == content_models.ContentType.objects\
                                              .get(name='Issue'):
            return urlresolvers.reverse(
                'issue_images',
                kwargs={'issue_id': self.object.id})
        elif self.content_type == content_models.ContentType.objects\
                                                .get(name='Brand'):
            return urlresolvers.reverse(
                'show_brand',
                kwargs={'brand_id': self.object.id})
        else:
            return ''

    def __unicode__(self):
        return u'%s: %s' % (unicode(self.object),
                            capitalize(self.type.description))
