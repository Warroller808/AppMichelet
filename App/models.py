from django.db import models
from datetime import datetime
from django.core.management.base import BaseCommand


class Produit_catalogue(models.Model):
    code = models.CharField("CODE", max_length=128)
    annee = models.IntegerField("ANNEE", default=int(datetime.now().year))
    designation = models.CharField("DESIGNATION", max_length=128, blank=True, default='')
    type = models.CharField("TYPE", max_length=128, default="")
    fournisseur_generique = models.CharField("FOURNISSEUR GENERIQUE", max_length=128, default="")
    coalia = models.BooleanField("COALIA", default=False)
    pharmupp = models.BooleanField("PHARMUPP", default=False)
    lpp = models.BooleanField("LPP", default=False)
    remise_grossiste = models.CharField("REMISE_GROSSISTE", max_length=128, default="")
    remise_direct = models.CharField("REMISE_DIRECT", max_length=128, default="")
    tva = models.DecimalField("TVA", max_digits=15, decimal_places=3, default=0.00)
    date_creation = models.DateField("DATE CREATION", blank=True, default=datetime.now)
    creation_auto = models.BooleanField("CREATION AUTO", default=True)

    def __str__(self):
        return f"{self.code}"
    
    class Meta:
        unique_together = ('code', 'annee')
    
class Achat(models.Model):
    code = models.CharField("CODE", max_length=128, blank=False, default='')
    produit = models.ForeignKey(Produit_catalogue, on_delete=models.PROTECT, null=True, default=None)
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
    categorie_remise = models.CharField("CATEGORIE", max_length=128, default='')

    def __str__(self):
        return f"{self.code} {self.designation} {self.date} {self.fournisseur} - {self.categorie}"
    

class Avoir_remises(models.Model):
    numero = models.CharField("NUMERO", max_length=128, primary_key=True)
    date = models.DateField("DATE", blank=False)
    mois_concerne = models.CharField("MOIS_CONCERNÉ", max_length=128, blank=False, default="")
    specialites_pharmaceutiques_montant = models.DecimalField("MONTANT SPECIALITÉS PHARMACEUTIQUES", max_digits=15, decimal_places=4, default=0.00)
    lpp_cinq_ou_dix_montant = models.DecimalField("MONTANT LPP 5,5 OU 10%", max_digits=15, decimal_places=4, default=0.00)
    lpp_vingt_montant = models.DecimalField("MONTANT LPP 20%", max_digits=15, decimal_places=4, default=0.00)
    parapharmacie_montant = models.DecimalField("MONTANT PARAPHARMACIE", max_digits=15, decimal_places=4, default=0.00)
    total_montant = models.DecimalField("MONTANT TOTAL", max_digits=15, decimal_places=4, default=0.00)
    specialites_pharmaceutiques_remise = models.DecimalField("REMISE SPECIALITÉS_PHARMACEUTIQUES", max_digits=15, decimal_places=4, default=0.00)
    lpp_cinq_ou_dix_remise = models.DecimalField("REMISE LPP 5,5 OU 10%", max_digits=15, decimal_places=4, default=0.00)
    lpp_vingt_remise = models.DecimalField("REMISE LPP 20%", max_digits=15, decimal_places=4, default=0.00)
    parapharmacie_remise = models.DecimalField("REMISE PARAPHARMACIE", max_digits=15, decimal_places=4, default=0.00)
    avantage_commercial = models.DecimalField("AVANTAGE_COMMERCIAL", max_digits=15, decimal_places=4, default=0.00)
    total_remise = models.DecimalField("REMISE TOTALE", max_digits=15, decimal_places=4, default=0.00)
    avoirs_exceptionnels = models.DecimalField("AVOIRS_EXCEPTIONNELS", max_digits=15, decimal_places=4, default=0.00)
    generiques_montant = models.DecimalField("MONTANT GENERIQUES", max_digits=15, decimal_places=4, default=0.00)
    marche_produits_montant = models.DecimalField("MONTANT MARCHE PRODUITS", max_digits=15, decimal_places=4, default=0.00)
    upp_montant = models.DecimalField("MONTANT UPP", max_digits=15, decimal_places=4, default=0.00)
    autres_montant = models.DecimalField("MONTANT AUTRES", max_digits=15, decimal_places=4, default=0.00)
    coalia_montant = models.DecimalField("MONTANT COALIA", max_digits=15, decimal_places=4, default=0.00)
    pharmat_montant = models.DecimalField("MONTANT PHARMAT", max_digits=15, decimal_places=4, default=0.00)
    generiques_remise = models.DecimalField("REMISE GENERIQUES", max_digits=15, decimal_places=4, default=0.00)
    marche_produits_remise = models.DecimalField("REMISE MARCHE PRODUITS", max_digits=15, decimal_places=4, default=0.00)
    upp_remise = models.DecimalField("REMISE UPP", max_digits=15, decimal_places=4, default=0.00)
    autres_remise = models.DecimalField("REMISE AUTRES", max_digits=15, decimal_places=4, default=0.00)
    coalia_remise = models.DecimalField("REMISE COALIA", max_digits=15, decimal_places=4, default=0.00)
    pharmat_remise = models.DecimalField("REMISE PHARMAT", max_digits=15, decimal_places=4, default=0.00)

    def __str__(self):
        return f"{self.numero} émis le {self.date} - Mois concerné : {self.mois_concerne}"
    

class Avoir_ratrappage_teva(models.Model):
    numero = models.CharField("NUMERO", max_length=128, primary_key=True)
    date = models.DateField("DATE", blank=False)
    mois_concerne = models.CharField("MOIS_CONCERNÉ", max_length=128, blank=False, default="")
    montant_ratrappage = models.DecimalField("MONTANT RATTRAPAGE", max_digits=15, decimal_places=4, default=0.00)

    def __str__(self):
        return f"{self.numero} émis le {self.date} - Mois concerné : {self.mois_concerne}"


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


class Constante(models.Model):
    name = models.CharField("NOM", max_length=128, primary_key=True)
    value = models.CharField("VALEUR", max_length=128, blank=True, default="")


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
        

    def completer_fournisseur_generique_et_type():
        from .jobs import completer_fournisseur_generique_et_type_job

        confirmation = input("Voulez-vous vraiment exécuter cette opération ? (y/n): ").lower()
        if not confirmation:
            return "Script non exécuté"
        
        try:
            completer_fournisseur_generique_et_type_job()
            print("Succès")

        except Exception as e:
            print(f'Echec : {e}')
    
    def categoriser_achats():
        from .jobs import categoriser_achats_job

        confirmation = input("Voulez-vous vraiment exécuter cette opération ? (y/n): ").lower()
        if not confirmation:
            return "Script non exécuté"

        try:
            categoriser_achats_job()
            print("Succès")
            
        except Exception as e:
            print(f'Echec : {e}')


    def calcul_remises():
        from .jobs import calcul_remises_job

        confirmation = input("Voulez-vous vraiment exécuter cette opération ? (y/n): ").lower()
        if not confirmation:
            return "Script non exécuté"
        
        try:
            calcul_remises_job()
            print("Succès")
            
        except Exception as e:
            print(f'Echec : {e}')


    def afficher_achat():
        achats = Achat.objects.filter(produit="7323190196562", date="2023-10-16")

        for achat in achats:
            print(vars(achat))

    
    def calcul_remise_pourcent_si_absente():
        from decimal import Decimal

        confirmation = input("Voulez-vous vraiment exécuter cette opération ? (y/n): ").lower()
        if not confirmation:
            return "Script non exécuté"
        
        try:
            achats = Achat.objects.all()
            prev_pourcentage = 0
            compteur = 0

            for achat in achats:
                if (achat.remise_pourcent > -0.0001 and achat.remise_pourcent < 0.0001) and achat.prix_unitaire_remise_ht > 0.1:
                    prev_pourcentage = Decimal(achat.remise_pourcent)

                    achat.remise_pourcent = round(Decimal(1) - (Decimal(achat.prix_unitaire_remise_ht) / Decimal(achat.prix_unitaire_ht)), 4)

                    achat.save()

                    if achat.remise_pourcent != prev_pourcentage:
                        compteur += 1
                        print(f'pourcentage de remise modifié pour l\'achat {achat.produit} {achat.date} {achat.fournisseur} : {prev_pourcentage} => {achat.remise_pourcent}')

            print(f"Succès du calcul des remises théoriques. {compteur} modifications effectuées")

        except Exception as e:
            print(f"Echec du calcul des remises théoriques : {e}")


    def extraire_produits_categorises():
        from AppMichelet.settings import BASE_DIR
        import pandas as pd
        import os
        from django.db.models import F

        excel_file_path = os.path.join(BASE_DIR, f'extractions/Produits_categorises_{datetime.now().strftime("%d-%m-%Y")}.xlsx')

        data = Achat.objects.values(
            'code',
            'designation',
            'tva',
            'prix_unitaire_ht',
            'remise_pourcent',
            'fournisseur',
            'categorie',
            type=F('produit__type'),
            fournisseur_generique=F('produit__fournisseur_generique')
        ).distinct()

        df = pd.DataFrame.from_records(data)

        df.to_excel(excel_file_path, index=False)


    def extraire_catalogue():
        from AppMichelet.settings import BASE_DIR
        import pandas as pd
        import os
        from django.db.models import F

        excel_file_path = os.path.join(BASE_DIR, f'extractions/Catalogue_{datetime.now().strftime("%d-%m-%Y")}.xlsx')

        data = Produit_catalogue.objects.values(
            'code',
            'annee',
            'designation',
            'type',
            'fournisseur_generique',
            'coalia',
            'pharmupp',
            'lpp',
            'remise_grossiste',
            'remise_direct',
            'tva'
        ).distinct()

        df = pd.DataFrame.from_records(data)

        df.to_excel(excel_file_path, index=False)


    def attribuer_produit_to_achats():

        confirmation = input("Voulez-vous vraiment exécuter cette opération ? (y/n): ").lower()
        if not confirmation:
            return "Script non exécuté"

        achats_sans_produit = Achat.objects.filter(produit__isnull=True)

        for achat in achats_sans_produit:
            try:
                produit = Produit_catalogue.objects.get(code=achat.code, annee=achat.date.year)
                achat.produit = produit
                achat.save()
                print(f'Achat {achat.code} associé au produit {produit.code}')
            except Exception as e:
                print(f'Erreur sur l\'achat {achat.code} : {e}')

        print('Mise à jour des achats terminée.')


    def afficher_remises_teva():
        from decimal import Decimal

        confirmation = input("Voulez-vous vraiment exécuter cette opération ? (y/n): ").lower()
        if not confirmation:
            return "Script non exécuté"

        remises = (
            Achat.objects
            .filter(
                    produit__fournisseur_generique="TEVA",
                    produit__type="GENERIQUE",
            )
            .values('remise_pourcent')
        ).distinct()

        print(remises)

        remises_2 = (
            Achat.objects
            .filter(
                    fournisseur="TEVA",
                    produit__type="GENERIQUE",
                    remise_pourcent__gt=Decimal(0.029),
                    remise_pourcent__lt=Decimal(0.099),
            )
            .values('code', 'remise_pourcent')
        ).distinct()

        print(remises_2)


    def categoriser_remises_teva():
        from .utils import get_categorie_remise

        confirmation = input("Voulez-vous vraiment exécuter cette opération ? (y/n): ").lower()
        if not confirmation:
            return "Script non exécuté"
        
        achats = (
            Achat.objects
            .filter(
                produit__fournisseur_generique = "TEVA"
            )
        )

        for achat in achats:
            produit = Produit_catalogue.objects.get(code=achat.code, annee=achat.date.year)
            achat.categorie_remise = get_categorie_remise(produit.fournisseur_generique, achat.fournisseur, achat.remise_pourcent)
            achat.save()
            print(f"Catégorie remise attribuée au produit {produit.code} - {produit.fournisseur_generique} => {achat.categorie_remise}")

        print("Succès")

        
    def corriger_cat_generiques():
        #Permet de retirer le type générique aux produits de laboratoires n'ayant pas le nom du labo dans leur désignation

        from .constants import LABORATOIRES_GENERIQUES

        confirmation = input("Voulez-vous vraiment exécuter cette opération ? (y/n): ").lower()
        if not confirmation:
            return "Script non exécuté"
        
        produits = (
            Produit_catalogue.objects
            .filter(
                type="GENERIQUE"
            )
            .exclude(
                fournisseur_generique=""
            )
        )

        for produit in produits:
            if not any(element in produit.designation.upper().replace('®', '') for element in LABORATOIRES_GENERIQUES):
                prev_type = produit.type
                produit.type = ""
                produit.save()
                print(f"{produit.code} {produit.designation} - ce produit a été retiré des génériques : {prev_type} {produit.fournisseur_generique} => '' {produit.fournisseur_generique}")


    def extract_remises_theoriques_manquantes():
        from decimal import Decimal
        from AppMichelet.settings import BASE_DIR
        import pandas as pd
        import os
        from django.db.models import F, Q

        excel_file_path = os.path.join(BASE_DIR, f'extractions/Produits_sans_remise_{datetime.now().strftime("%d-%m-%Y")}.xlsx')

        achats = (
            Achat.objects
            .filter(
                Q(produit__remise_grossiste = "") | Q(produit__remise_direct = ""),
                produit__type = "GENERIQUE",
                produit__annee = int(2023)
            )
            .exclude(
                remise_pourcent = Decimal(0)
            )
            .values(
                'code',
                'designation',
                'tva',
                'prix_unitaire_ht',
                'remise_pourcent',
                'fournisseur',
                'categorie',
                type=F('produit__type'),
                fournisseur_generique=F('produit__fournisseur_generique'),
                remise_direct=F('produit__remise_direct'),
                remise_grossiste=F('produit__remise_grossiste'),
            )
        ).distinct()

        df = pd.DataFrame.from_records(achats)

        df.to_excel(excel_file_path, index=False)