# -*- coding: utf-8 -*-
import datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Adding model 'Collector'
        db.create_table('mycomics_collector', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('user', self.gf('django.db.models.fields.related.OneToOneField')(to=orm['auth.User'], unique=True)),
            ('grade_system', self.gf('django.db.models.fields.related.ForeignKey')(related_name='+', to=orm['mycomics.ConditionGradeScale'])),
            ('default_have_collection', self.gf('django.db.models.fields.related.ForeignKey')(related_name='+', null=True, to=orm['mycomics.Collection'])),
            ('default_want_collection', self.gf('django.db.models.fields.related.ForeignKey')(related_name='+', null=True, to=orm['mycomics.Collection'])),
            ('default_language', self.gf('django.db.models.fields.related.ForeignKey')(related_name='+', to=orm['gcd.Language'])),
        ))
        db.send_create_signal('mycomics', ['Collector'])

        # Adding model 'Collection'
        db.create_table('mycomics_collection', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('collector', self.gf('django.db.models.fields.related.ForeignKey')(related_name='collections', to=orm['mycomics.Collector'])),
            ('name', self.gf('django.db.models.fields.CharField')(max_length=255, db_index=True)),
            ('description', self.gf('django.db.models.fields.TextField')(blank=True)),
            ('public', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('condition_used', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('acquisition_date_used', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('sell_date_used', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('location_used', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('purchase_location_used', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('was_read_used', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('for_sale_used', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('signed_used', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('price_paid_used', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('market_value_used', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('sell_price_used', self.gf('django.db.models.fields.BooleanField')(default=False)),
        ))
        db.send_create_signal('mycomics', ['Collection'])

        # Adding model 'Location'
        db.create_table('mycomics_location', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('user', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['mycomics.Collector'])),
            ('name', self.gf('django.db.models.fields.CharField')(max_length=255, blank=True)),
            ('description', self.gf('django.db.models.fields.TextField')(blank=True)),
        ))
        db.send_create_signal('mycomics', ['Location'])

        # Adding model 'PurchaseLocation'
        db.create_table('mycomics_purchase_location', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('user', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['mycomics.Collector'])),
            ('name', self.gf('django.db.models.fields.CharField')(max_length=255, blank=True)),
            ('description', self.gf('django.db.models.fields.TextField')(blank=True)),
        ))
        db.send_create_signal('mycomics', ['PurchaseLocation'])

        # Adding model 'CollectionItem'
        db.create_table('mycomics_collection_item', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('issue', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['gcd.Issue'])),
            ('location', self.gf('django.db.models.fields.related.ForeignKey')(null=True, to=orm['mycomics.Location'])),
            ('purchase_location', self.gf('django.db.models.fields.related.ForeignKey')(null=True, to=orm['mycomics.PurchaseLocation'])),
            ('notes', self.gf('django.db.models.fields.TextField')(blank=True)),
            ('grade', self.gf('django.db.models.fields.related.ForeignKey')(null=True, related_name='+', to=orm['mycomics.ConditionGrade'])),
            ('acquisition_date', self.gf('django.db.models.fields.related.ForeignKey')(null=True, related_name='+', to=orm['stddata.Date'])),
            ('sell_date', self.gf('django.db.models.fields.related.ForeignKey')(null=True, related_name='+', to=orm['stddata.Date'])),
            ('was_read', self.gf('django.db.models.fields.NullBooleanField')(default=None, null=True, blank=True)),
            ('for_sale', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('signed', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('price_paid', self.gf('django.db.models.fields.FloatField')(null=True, blank=True)),
            ('price_paid_currency', self.gf('django.db.models.fields.related.ForeignKey')(null=True, related_name='+', to=orm['stddata.Currency'])),
            ('market_value', self.gf('django.db.models.fields.FloatField')(null=True, blank=True)),
            ('market_value_currency', self.gf('django.db.models.fields.related.ForeignKey')(null=True, related_name='+', to=orm['stddata.Currency'])),
            ('sell_price', self.gf('django.db.models.fields.FloatField')(null=True, blank=True)),
            ('sell_price_currency', self.gf('django.db.models.fields.related.ForeignKey')(null=True, related_name='+', to=orm['stddata.Currency'])),
        ))
        db.send_create_signal('mycomics', ['CollectionItem'])

        # Adding M2M table for field collections on 'CollectionItem'
        db.create_table('mycomics_collection_item_collections', (
            ('id', models.AutoField(verbose_name='ID', primary_key=True, auto_created=True)),
            ('collectionitem', models.ForeignKey(orm['mycomics.collectionitem'], null=False)),
            ('collection', models.ForeignKey(orm['mycomics.collection'], null=False))
        ))
        db.create_unique('mycomics_collection_item_collections', ['collectionitem_id', 'collection_id'])

        # Adding model 'ConditionGradeScale'
        db.create_table('mycomics_condition_grade_scale', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('name', self.gf('django.db.models.fields.CharField')(max_length=255)),
            ('description', self.gf('django.db.models.fields.CharField')(max_length=2000, blank=True)),
        ))
        db.send_create_signal('mycomics', ['ConditionGradeScale'])

        # Adding model 'ConditionGrade'
        db.create_table('mycomics_condition_grade', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('scale', self.gf('django.db.models.fields.related.ForeignKey')(related_name='grades', to=orm['mycomics.ConditionGradeScale'])),
            ('code', self.gf('django.db.models.fields.CharField')(max_length=20)),
            ('name', self.gf('django.db.models.fields.CharField')(max_length=255)),
            ('value', self.gf('django.db.models.fields.FloatField')()),
        ))
        db.send_create_signal('mycomics', ['ConditionGrade'])


    def backwards(self, orm):
        # Deleting model 'Collector'
        db.delete_table('mycomics_collector')

        # Deleting model 'Collection'
        db.delete_table('mycomics_collection')

        # Deleting model 'Location'
        db.delete_table('mycomics_location')

        # Deleting model 'PurchaseLocation'
        db.delete_table('mycomics_purchase_location')

        # Deleting model 'CollectionItem'
        db.delete_table('mycomics_collection_item')

        # Removing M2M table for field collections on 'CollectionItem'
        db.delete_table('mycomics_collection_item_collections')

        # Deleting model 'ConditionGradeScale'
        db.delete_table('mycomics_condition_grade_scale')

        # Deleting model 'ConditionGrade'
        db.delete_table('mycomics_condition_grade')


    models = {
        'auth.group': {
            'Meta': {'object_name': 'Group'},
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '80'}),
            'permissions': ('django.db.models.fields.related.ManyToManyField', [], {'to': "orm['auth.Permission']", 'symmetrical': 'False', 'blank': 'True'})
        },
        'auth.permission': {
            'Meta': {'ordering': "('content_type__app_label', 'content_type__model', 'codename')", 'unique_together': "(('content_type', 'codename'),)", 'object_name': 'Permission'},
            'codename': ('django.db.models.fields.CharField', [], {'max_length': '100'}),
            'content_type': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['contenttypes.ContentType']"}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '50'})
        },
        'auth.user': {
            'Meta': {'object_name': 'User'},
            'date_joined': ('django.db.models.fields.DateTimeField', [], {'default': 'datetime.datetime.now'}),
            'email': ('django.db.models.fields.EmailField', [], {'max_length': '75', 'blank': 'True'}),
            'first_name': ('django.db.models.fields.CharField', [], {'max_length': '30', 'blank': 'True'}),
            'groups': ('django.db.models.fields.related.ManyToManyField', [], {'to': "orm['auth.Group']", 'symmetrical': 'False', 'blank': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'is_active': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            'is_staff': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'is_superuser': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'last_login': ('django.db.models.fields.DateTimeField', [], {'default': 'datetime.datetime.now'}),
            'last_name': ('django.db.models.fields.CharField', [], {'max_length': '30', 'blank': 'True'}),
            'password': ('django.db.models.fields.CharField', [], {'max_length': '128'}),
            'user_permissions': ('django.db.models.fields.related.ManyToManyField', [], {'to': "orm['auth.Permission']", 'symmetrical': 'False', 'blank': 'True'}),
            'username': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '30'})
        },
        'contenttypes.contenttype': {
            'Meta': {'ordering': "('name',)", 'unique_together': "(('app_label', 'model'),)", 'object_name': 'ContentType', 'db_table': "'django_content_type'"},
            'app_label': ('django.db.models.fields.CharField', [], {'max_length': '100'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'model': ('django.db.models.fields.CharField', [], {'max_length': '100'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '100'})
        },
        'gcd.brand': {
            'Meta': {'ordering': "['name']", 'object_name': 'Brand'},
            'created': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'blank': 'True'}),
            'deleted': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'issue_count': ('django.db.models.fields.IntegerField', [], {'default': '0'}),
            'modified': ('django.db.models.fields.DateTimeField', [], {'auto_now': 'True', 'blank': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '255', 'db_index': 'True'}),
            'notes': ('django.db.models.fields.TextField', [], {}),
            'parent': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['gcd.Publisher']"}),
            'reserved': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'url': ('django.db.models.fields.URLField', [], {'default': "u''", 'max_length': '255', 'blank': 'True'}),
            'year_began': ('django.db.models.fields.IntegerField', [], {'null': 'True', 'db_index': 'True'}),
            'year_began_uncertain': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'year_ended': ('django.db.models.fields.IntegerField', [], {'null': 'True'}),
            'year_ended_uncertain': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'})
        },
        'gcd.country': {
            'Meta': {'ordering': "('name',)", 'object_name': 'Country'},
            'code': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '10'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '255', 'db_index': 'True'})
        },
        'gcd.image': {
            'Meta': {'object_name': 'Image'},
            'content_type': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['contenttypes.ContentType']", 'null': 'True'}),
            'created': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'null': 'True', 'blank': 'True'}),
            'deleted': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'image_file': ('django.db.models.fields.files.ImageField', [], {'max_length': '100'}),
            'marked': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'modified': ('django.db.models.fields.DateTimeField', [], {'auto_now': 'True', 'null': 'True', 'blank': 'True'}),
            'object_id': ('django.db.models.fields.PositiveIntegerField', [], {'null': 'True', 'db_index': 'True'}),
            'reserved': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'type': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['gcd.ImageType']"})
        },
        'gcd.imagetype': {
            'Meta': {'object_name': 'ImageType', 'db_table': "'gcd_image_type'"},
            'description': ('django.db.models.fields.CharField', [], {'max_length': '255'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '50', 'db_index': 'True'}),
            'unique': ('django.db.models.fields.BooleanField', [], {'default': 'True'})
        },
        'gcd.indiciapublisher': {
            'Meta': {'ordering': "['name']", 'object_name': 'IndiciaPublisher', 'db_table': "'gcd_indicia_publisher'"},
            'country': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['gcd.Country']"}),
            'created': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'blank': 'True'}),
            'deleted': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'is_surrogate': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'issue_count': ('django.db.models.fields.IntegerField', [], {'default': '0'}),
            'modified': ('django.db.models.fields.DateTimeField', [], {'auto_now': 'True', 'blank': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '255', 'db_index': 'True'}),
            'notes': ('django.db.models.fields.TextField', [], {}),
            'parent': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['gcd.Publisher']"}),
            'reserved': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'url': ('django.db.models.fields.URLField', [], {'default': "u''", 'max_length': '255', 'blank': 'True'}),
            'year_began': ('django.db.models.fields.IntegerField', [], {'null': 'True', 'db_index': 'True'}),
            'year_began_uncertain': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'year_ended': ('django.db.models.fields.IntegerField', [], {'null': 'True'}),
            'year_ended_uncertain': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'})
        },
        'gcd.issue': {
            'Meta': {'ordering': "['series', 'sort_code']", 'unique_together': "(('series', 'sort_code'),)", 'object_name': 'Issue'},
            'barcode': ('django.db.models.fields.CharField', [], {'max_length': '38', 'db_index': 'True'}),
            'brand': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['gcd.Brand']", 'null': 'True'}),
            'created': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'blank': 'True'}),
            'deleted': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'display_volume_with_number': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'editing': ('django.db.models.fields.TextField', [], {}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'indicia_frequency': ('django.db.models.fields.CharField', [], {'max_length': '255'}),
            'indicia_pub_not_printed': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'indicia_publisher': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['gcd.IndiciaPublisher']", 'null': 'True'}),
            'is_indexed': ('django.db.models.fields.IntegerField', [], {'default': '0', 'db_index': 'True'}),
            'isbn': ('django.db.models.fields.CharField', [], {'max_length': '32', 'db_index': 'True'}),
            'key_date': ('django.db.models.fields.CharField', [], {'max_length': '10', 'db_index': 'True'}),
            'modified': ('django.db.models.fields.DateTimeField', [], {'auto_now': 'True', 'db_index': 'True', 'blank': 'True'}),
            'no_barcode': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'no_brand': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'no_editing': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'no_indicia_frequency': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'no_isbn': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'no_title': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'no_volume': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'notes': ('django.db.models.fields.TextField', [], {}),
            'number': ('django.db.models.fields.CharField', [], {'max_length': '50', 'db_index': 'True'}),
            'on_sale_date': ('django.db.models.fields.CharField', [], {'max_length': '10', 'db_index': 'True'}),
            'on_sale_date_uncertain': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'page_count': ('django.db.models.fields.DecimalField', [], {'null': 'True', 'max_digits': '10', 'decimal_places': '3'}),
            'page_count_uncertain': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'price': ('django.db.models.fields.CharField', [], {'max_length': '255'}),
            'publication_date': ('django.db.models.fields.CharField', [], {'max_length': '255'}),
            'reserved': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'series': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['gcd.Series']"}),
            'sort_code': ('django.db.models.fields.IntegerField', [], {'db_index': 'True'}),
            'title': ('django.db.models.fields.CharField', [], {'max_length': '255', 'db_index': 'True'}),
            'valid_isbn': ('django.db.models.fields.CharField', [], {'max_length': '13', 'db_index': 'True'}),
            'variant_name': ('django.db.models.fields.CharField', [], {'max_length': '255'}),
            'variant_of': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'variant_set'", 'null': 'True', 'to': "orm['gcd.Issue']"}),
            'volume': ('django.db.models.fields.CharField', [], {'max_length': '50', 'db_index': 'True'})
        },
        'gcd.language': {
            'Meta': {'ordering': "('name',)", 'object_name': 'Language'},
            'code': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '10'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '255', 'db_index': 'True'})
        },
        'gcd.publisher': {
            'Meta': {'ordering': "['name']", 'object_name': 'Publisher'},
            'brand_count': ('django.db.models.fields.IntegerField', [], {'default': '0', 'db_index': 'True'}),
            'country': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['gcd.Country']"}),
            'created': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'blank': 'True'}),
            'deleted': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'imprint_count': ('django.db.models.fields.IntegerField', [], {'default': '0'}),
            'indicia_publisher_count': ('django.db.models.fields.IntegerField', [], {'default': '0', 'db_index': 'True'}),
            'is_master': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'issue_count': ('django.db.models.fields.IntegerField', [], {'default': '0'}),
            'modified': ('django.db.models.fields.DateTimeField', [], {'auto_now': 'True', 'blank': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '255', 'db_index': 'True'}),
            'notes': ('django.db.models.fields.TextField', [], {}),
            'parent': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'imprint_set'", 'null': 'True', 'to': "orm['gcd.Publisher']"}),
            'reserved': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'series_count': ('django.db.models.fields.IntegerField', [], {'default': '0'}),
            'url': ('django.db.models.fields.URLField', [], {'default': "u''", 'max_length': '255', 'blank': 'True'}),
            'year_began': ('django.db.models.fields.IntegerField', [], {'null': 'True', 'db_index': 'True'}),
            'year_began_uncertain': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'year_ended': ('django.db.models.fields.IntegerField', [], {'null': 'True'}),
            'year_ended_uncertain': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'})
        },
        'gcd.series': {
            'Meta': {'ordering': "['sort_name', 'year_began']", 'object_name': 'Series'},
            'binding': ('django.db.models.fields.CharField', [], {'default': "u''", 'max_length': '255'}),
            'color': ('django.db.models.fields.CharField', [], {'default': "u''", 'max_length': '255'}),
            'country': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['gcd.Country']"}),
            'created': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'blank': 'True'}),
            'deleted': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'dimensions': ('django.db.models.fields.CharField', [], {'default': "u''", 'max_length': '255'}),
            'first_issue': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'first_issue_series_set'", 'null': 'True', 'to': "orm['gcd.Issue']"}),
            'format': ('django.db.models.fields.CharField', [], {'default': "u''", 'max_length': '255'}),
            'has_barcode': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'has_gallery': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'has_indicia_frequency': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'has_isbn': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'has_issue_title': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'has_volume': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'imprint': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'imprint_series_set'", 'null': 'True', 'to': "orm['gcd.Publisher']"}),
            'is_comics_publication': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'is_current': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'issue_count': ('django.db.models.fields.IntegerField', [], {}),
            'language': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['gcd.Language']"}),
            'last_issue': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'last_issue_series_set'", 'null': 'True', 'to': "orm['gcd.Issue']"}),
            'modified': ('django.db.models.fields.DateTimeField', [], {'auto_now': 'True', 'blank': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '255', 'db_index': 'True'}),
            'notes': ('django.db.models.fields.TextField', [], {}),
            'open_reserve': ('django.db.models.fields.IntegerField', [], {'null': 'True'}),
            'paper_stock': ('django.db.models.fields.CharField', [], {'default': "u''", 'max_length': '255'}),
            'publication_dates': ('django.db.models.fields.CharField', [], {'max_length': '255'}),
            'publication_notes': ('django.db.models.fields.TextField', [], {}),
            'publisher': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['gcd.Publisher']"}),
            'publishing_format': ('django.db.models.fields.CharField', [], {'default': "u''", 'max_length': '255'}),
            'reserved': ('django.db.models.fields.BooleanField', [], {'default': 'False', 'db_index': 'True'}),
            'sort_name': ('django.db.models.fields.CharField', [], {'max_length': '255', 'db_index': 'True'}),
            'tracking_notes': ('django.db.models.fields.TextField', [], {}),
            'year_began': ('django.db.models.fields.IntegerField', [], {'db_index': 'True'}),
            'year_began_uncertain': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'year_ended': ('django.db.models.fields.IntegerField', [], {'null': 'True'}),
            'year_ended_uncertain': ('django.db.models.fields.BooleanField', [], {'default': 'False'})
        },
        'mycomics.collection': {
            'Meta': {'object_name': 'Collection'},
            'acquisition_date_used': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'collector': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'collections'", 'to': "orm['mycomics.Collector']"}),
            'condition_used': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'description': ('django.db.models.fields.TextField', [], {'blank': 'True'}),
            'for_sale_used': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'location_used': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'market_value_used': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '255', 'db_index': 'True'}),
            'price_paid_used': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'public': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'purchase_location_used': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'sell_date_used': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'sell_price_used': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'signed_used': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'was_read_used': ('django.db.models.fields.BooleanField', [], {'default': 'False'})
        },
        'mycomics.collectionitem': {
            'Meta': {'object_name': 'CollectionItem', 'db_table': "'mycomics_collection_item'"},
            'acquisition_date': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'+'", 'to': "orm['stddata.Date']"}),
            'collections': ('django.db.models.fields.related.ManyToManyField', [], {'related_name': "'items'", 'symmetrical': 'False', 'db_table': "'mycomics_collection_item_collections'", 'to': "orm['mycomics.Collection']"}),
            'for_sale': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'grade': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'+'", 'to': "orm['mycomics.ConditionGrade']"}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'issue': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['gcd.Issue']"}),
            'location': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['mycomics.Location']"}),
            'market_value': ('django.db.models.fields.FloatField', [], {'null': 'True', 'blank': 'True'}),
            'market_value_currency': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'+'", 'to': "orm['stddata.Currency']"}),
            'notes': ('django.db.models.fields.TextField', [], {'blank': 'True'}),
            'price_paid': ('django.db.models.fields.FloatField', [], {'null': 'True', 'blank': 'True'}),
            'price_paid_currency': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'+'", 'to': "orm['stddata.Currency']"}),
            'purchase_location': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['mycomics.PurchaseLocation']"}),
            'sell_date': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'+'", 'to': "orm['stddata.Date']"}),
            'sell_price': ('django.db.models.fields.FloatField', [], {'null': 'True', 'blank': 'True'}),
            'sell_price_currency': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'+'", 'to': "orm['stddata.Currency']"}),
            'signed': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'was_read': ('django.db.models.fields.NullBooleanField', [], {'default': 'None', 'null': 'True', 'blank': 'True'})
        },
        'mycomics.collector': {
            'Meta': {'object_name': 'Collector'},
            'default_have_collection': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'+'", 'null': 'True', 'to': "orm['mycomics.Collection']"}),
            'default_language': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'+'", 'to': "orm['gcd.Language']"}),
            'default_want_collection': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'+'", 'null': 'True', 'to': "orm['mycomics.Collection']"}),
            'grade_system': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'+'", 'to': "orm['mycomics.ConditionGradeScale']"}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'user': ('django.db.models.fields.related.OneToOneField', [], {'to': "orm['auth.User']", 'unique': 'True'})
        },
        'mycomics.conditiongrade': {
            'Meta': {'object_name': 'ConditionGrade', 'db_table': "'mycomics_condition_grade'"},
            'code': ('django.db.models.fields.CharField', [], {'max_length': '20'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '255'}),
            'scale': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'grades'", 'to': "orm['mycomics.ConditionGradeScale']"}),
            'value': ('django.db.models.fields.FloatField', [], {})
        },
        'mycomics.conditiongradescale': {
            'Meta': {'object_name': 'ConditionGradeScale', 'db_table': "'mycomics_condition_grade_scale'"},
            'description': ('django.db.models.fields.CharField', [], {'max_length': '2000', 'blank': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '255'})
        },
        'mycomics.location': {
            'Meta': {'object_name': 'Location'},
            'description': ('django.db.models.fields.TextField', [], {'blank': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '255', 'blank': 'True'}),
            'user': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['mycomics.Collector']"})
        },
        'mycomics.purchaselocation': {
            'Meta': {'object_name': 'PurchaseLocation', 'db_table': "'mycomics_purchase_location'"},
            'description': ('django.db.models.fields.TextField', [], {'blank': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '255', 'blank': 'True'}),
            'user': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['mycomics.Collector']"})
        },
        'stddata.currency': {
            'Meta': {'ordering': "('name',)", 'object_name': 'Currency'},
            'code': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '3'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'is_decimal': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '100', 'db_index': 'True'})
        },
        'stddata.date': {
            'Meta': {'ordering': "('year', 'month', 'day')", 'object_name': 'Date'},
            'day': ('django.db.models.fields.CharField', [], {'db_index': 'True', 'max_length': '2', 'blank': 'True'}),
            'day_uncertain': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'month': ('django.db.models.fields.CharField', [], {'db_index': 'True', 'max_length': '2', 'blank': 'True'}),
            'month_uncertain': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'year': ('django.db.models.fields.CharField', [], {'db_index': 'True', 'max_length': '4', 'blank': 'True'}),
            'year_uncertain': ('django.db.models.fields.BooleanField', [], {'default': 'False'})
        },
        'taggit.tag': {
            'Meta': {'object_name': 'Tag'},
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '100'}),
            'slug': ('django.db.models.fields.SlugField', [], {'unique': 'True', 'max_length': '100'})
        },
        'taggit.taggeditem': {
            'Meta': {'object_name': 'TaggedItem'},
            'content_type': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'taggit_taggeditem_tagged_items'", 'to': "orm['contenttypes.ContentType']"}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'object_id': ('django.db.models.fields.IntegerField', [], {'db_index': 'True'}),
            'tag': ('django.db.models.fields.related.ForeignKey', [], {'related_name': "'taggit_taggeditem_items'", 'to': "orm['taggit.Tag']"})
        }
    }

    complete_apps = ['mycomics']