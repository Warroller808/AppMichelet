from django.contrib import admin

from .models import Produit_catalogue, Achat, Format_facture


class Produit_catalogueAdmin(admin.ModelAdmin):
    search_fields = ['code', 'designation']


class AchatAdmin(admin.ModelAdmin):
    search_fields = ['produit__code', 'designation', 'date', 'categorie']


class Format_factureAdmin(admin.ModelAdmin):
    search_fields = ['format']

admin.site.register(Produit_catalogue, Produit_catalogueAdmin)
admin.site.register(Achat, AchatAdmin)
admin.site.register(Format_facture, Format_factureAdmin)