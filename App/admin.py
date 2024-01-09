from django.contrib import admin

from .models import Produit_catalogue, Achat, Avoir_remises, Format_facture, Constante


class Produit_catalogueAdmin(admin.ModelAdmin):
    search_fields = ['code', 'designation']


class AchatAdmin(admin.ModelAdmin):
    search_fields = ['fournisseur']


class Avoir_remisesAdmin(admin.ModelAdmin):
    search_fields = ['numero', 'date', 'mois_concerne']


class Format_factureAdmin(admin.ModelAdmin):
    search_fields = ['format']


class ConstanteAdmin(admin.ModelAdmin):
    search_fields = ['name']


admin.site.register(Produit_catalogue, Produit_catalogueAdmin)
admin.site.register(Achat, AchatAdmin)
admin.site.register(Avoir_remises, Avoir_remisesAdmin)
admin.site.register(Format_facture, Format_factureAdmin)
admin.site.register(Constante, ConstanteAdmin)