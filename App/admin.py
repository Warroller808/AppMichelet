from django.contrib import admin

from .models import Produit_catalogue, Achat, Avoir_remises, Avoir_ratrappage_teva, Releve_alliance, Format_facture, Constante


class Produit_catalogueAdmin(admin.ModelAdmin):
    search_fields = ['code', 'designation']


class AchatAdmin(admin.ModelAdmin):
    search_fields = ['code', 'fournisseur', 'numero_facture']


class Avoir_remisesAdmin(admin.ModelAdmin):
    search_fields = ['numero', 'date', 'mois_concerne']


class Avoir_ratrappage_tevaAdmin(admin.ModelAdmin):
    search_fields = ['numero', 'date', 'mois_concerne']


class Releve_allianceAdmin(admin.ModelAdmin):
    search_fields = ['numero', 'date']


class Format_factureAdmin(admin.ModelAdmin):
    search_fields = ['format']


class ConstanteAdmin(admin.ModelAdmin):
    search_fields = ['name']


admin.site.register(Produit_catalogue, Produit_catalogueAdmin)
admin.site.register(Achat, AchatAdmin)
admin.site.register(Avoir_remises, Avoir_remisesAdmin)
admin.site.register(Avoir_ratrappage_teva, Avoir_ratrappage_tevaAdmin)
admin.site.register(Releve_alliance, Releve_allianceAdmin)
admin.site.register(Format_facture, Format_factureAdmin)
admin.site.register(Constante, ConstanteAdmin)