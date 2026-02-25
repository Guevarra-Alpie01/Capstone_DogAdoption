from django.contrib import admin
from .models import  Citation



@admin.register(Citation)
class CitationAdmin(admin.ModelAdmin):
    list_display = ('id', 'owner_name', 'penalty', 'date_issued')