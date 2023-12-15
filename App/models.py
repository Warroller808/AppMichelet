from django.db import models
from datetime import datetime
from django.core.management.base import BaseCommand


# Create your models here.

class Produit_catalogue(models.Model):
    code = models.CharField("CODE", max_length=128)
    annee = models.IntegerField("ANNEE", default=int(datetime.now().year))
    designation = models.CharField("DESIGNATION", max_length=128, blank=True, default='')
    type = models.CharField("TYPE", max_length=128, default="")
    fournisseur_generique = models.CharField("FOURNISSEUR GENERIQUE", max_length=128, default="")
    coalia = models.BooleanField("COALIA", default=False)
    remise_grossiste = models.CharField("REMISE_GROSSISTE", max_length=128, default="")
    remise_direct = models.CharField("REMISE_DIRECT", max_length=128, default="")
    tva = models.DecimalField("TVA", max_digits=15, decimal_places=3, default=0.00)

    def __str__(self):
        return f"{self.code}"
    
    class Meta:
        unique_together = ('code', 'annee')
    
class Achat(models.Model):
    produit = models.CharField("PRODUIT", max_length=128, blank=False, default='')
    designation = models.CharField("DESIGNATION", max_length=128, blank=True, default='')
    nb_boites = models.IntegerField("NB_BOITES",default=0)
    prix_unitaire_ht = models.DecimalField("PRIX_UNITAIRE_HT", max_digits=15, decimal_places=4, default=0.00)
    prix_unitaire_remise_ht = models.DecimalField("PRIX_UNITAIRE_REMISÉ_HT", max_digits=15, decimal_places=4, default=0.00)
    remise_pourcent = models.DecimalField("REMISE_POURCENT", max_digits=10, decimal_places=4, default=0.00)
    montant_ht_hors_remise = models.DecimalField("MONTANT_HT_HORS_REMISE", max_digits=15, decimal_places=4, default=0.00)
    montant_ht = models.DecimalField("MONTANT_HT", max_digits=15, decimal_places=4, default=0.00)
    remise_theorique_totale = models.DecimalField("REMISE_THEORIQUE_TOTALE", max_digits=15, decimal_places=4, default=0.00)
    tva = models.DecimalField("TVA", max_digits=15, decimal_places=3, default=0.00)
    date = models.DateField("DATE", blank=True)
    fichier_provenance = models.CharField("FICHIER_PROVENANCE", max_length=128, default='')
    numero_facture = models.CharField("NUMERO FACTURE", max_length=128, default='')
    fournisseur = models.CharField("FOURNISSEUR", max_length=128, default='')
    categorie = models.CharField("CATEGORIE", max_length=128, default='')

    def __str__(self):
        return f"{self.produit} {self.designation} {self.date} {self.fournisseur} - {self.categorie}"


class Format_facture(models.Model):
    format = models.CharField("FORMAT", max_length=128, primary_key=True)
    table_settings = models.JSONField(max_length=256, blank=True, default=dict)
    regex_reconnaissance = models.CharField(max_length=256, blank=False)
    regex_date = models.CharField(max_length=256, blank=False)
    regex_numero_facture = models.CharField(max_length=256, blank=False)
    pre_traitement = models.BooleanField(default=False)
    reconnaissance_table_ppale = models.CharField(max_length=128, blank=False, default="")
    regex_ligne_table = models.CharField(max_length=256, blank=False, default="")
    indice_code_produit = models.IntegerField(blank=True, default=-1)
    indice_designation = models.IntegerField(blank=True, default=-1)
    indice_nb_boites = models.IntegerField(blank=True, default=-1)
    indice_prix_unitaire_ht = models.IntegerField(blank=True, default=-1)
    indice_prix_unitaire_remise_ht = models.IntegerField(blank=True, default=-1)
    indice_remise_pourcent = models.IntegerField(blank=True, default=-1)
    indice_montant_ht_hors_remise = models.IntegerField(blank=True, default=-1)
    indice_montant_ht = models.IntegerField(blank=True, default=-1)
    indice_tva = models.IntegerField(blank=True, default=-1)


class Command(BaseCommand):
    help = 'Management de la bdd'

    def supprimer_catalogue():
        confirmation = input("Voulez-vous vraiment exécuter cette opération ? (y/n): ").lower()
        if not confirmation:
            return "Script non exécuté"
        
        resultat_suppression_catalogue = ""
        try:
            instances_a_supprimer = Produit_catalogue.objects.all()
            for instance in instances_a_supprimer:
                instance.delete()
            resultat_suppression_catalogue = "Le catalogue existant a bien été supprimé."
        except Exception as e:
            resultat_suppression_catalogue = f"Erreur lors de la suppression du catalogue : {str(e)}"
            
        return resultat_suppression_catalogue


    def supprimer_achats():
        confirmation = input("Voulez-vous vraiment exécuter cette opération ? (y/n): ").lower()
        if not confirmation:
            return "Script non exécuté"
        
        resultat_suppression_achats = ""
        try:
            instances_a_supprimer = Achat.objects.all()
            for instance in instances_a_supprimer:
                instance.delete()
            resultat_suppression_achats = "Les achats existants ont bien été supprimés."
        except Exception as e:
            resultat_suppression_achats = f"Erreur lors de la suppression des achats : {str(e)}"
        
        return resultat_suppression_achats