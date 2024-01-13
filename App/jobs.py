import logging
from datetime import datetime
from .utils import supprimer_fichiers_dossier
from .methods import get_factures_from_directory, process_factures
from .constants import DL_FOLDER_PATH_AUTO
from .selenium_cerp import main_cerp
from .selenium_digipharmacie import main_digi
from .models import Constante, Produit_catalogue, Achat


logger = logging.getLogger(__name__)


def import_factures_auto():
    # On télécharge les factures avec selenium
    
    success_cerp = main_cerp()
    success_digi = main_digi()

    logger.error(f'Success CERP : {success_cerp}, Success Digi : {success_digi}')

    if success_cerp or success_digi:
        # On les traite
        facture_paths = get_factures_from_directory()
        if facture_paths != []:
            success, table_achats_finale, events, texte_page, tables_page, tables_page_2 = process_factures(facture_paths)

            if success:
                supprimer_fichiers_dossier(DL_FOLDER_PATH_AUTO)
                # UPDATER LA DATE DE DERNIERE IMPORTATION
                logger.error(f'Succès de l\'importation automatique et du traitement. Factures supprimées dans le dossier.')

                if success_cerp:
                    last_import_date_cerp = Constante.objects.get(pk="LAST_IMPORT_DATE_CERP")
                    last_import_date_cerp.value = datetime.now().strftime("%d/%m/%Y")
                    last_import_date_cerp.save()
                
                if success_digi:
                    last_import_date_digi = Constante.objects.get(pk="LAST_IMPORT_DATE_DIGIPHARMACIE")
                    last_import_date_digi.value = datetime.now().strftime("%d/%m/%Y")
                    last_import_date_digi.save()

            else:
                logger.error('Erreur de traitement, les fichiers ont été conservés.')
        else:
            logger.error("Aucune facture n'a été téléchargée aujourd'hui")
    else:
        logger.error('Erreur d\'importation sur les deux sites, les fichiers téléchargés ont été conservés.')

    logger.error("Completion des fournisseurs génériques...")
    completer_fournisseur_generique_job()

    logger.error("Catégorisation des achats...")
    categoriser_achats_job()

    logger.error("Calcul des remises...")
    calcul_remises_job()

    logger.error("Traitement quotidien terminé.")


def completer_fournisseur_generique_job():
    from .utils import determiner_fournisseur_generique

    try:
        produits = Produit_catalogue.objects.all()
        compteur = 0

        for produit in produits:
            type_change = ""
            new_fournisseur_generique = determiner_fournisseur_generique(produit.designation)

            if new_fournisseur_generique != "":
                prev_fournisseur = produit.fournisseur_generique
                produit.fournisseur_generique = new_fournisseur_generique
                if produit.type == "":
                    produit.type = "GENERIQUE"
                    type_change = f'Le produit a été typé comme générique'
                produit.save()
                if prev_fournisseur != new_fournisseur_generique or type_change != "":
                    compteur += 1
                    print(f'fournisseur modifié pour le produit {produit.code} {produit.designation} : {prev_fournisseur} => {produit.fournisseur_generique} // {type_change}')

        logger.error(f"Succès de la complétion du fournisseur générique. {compteur} modifications effectuées")

    except Exception as e:
        logger.error(f"Echec de la complétion du fournisseur générique : {e}")
    

def categoriser_achats_job():
    from .utils import categoriser_achat

    try:
        achats = Achat.objects.all()
        prev_categorie = ""
        compteur = 0

        for achat in achats:
            prev_categorie = achat.categorie
            
            produit = Produit_catalogue.objects.get(code=achat.produit, annee=achat.date.year)
            achat.categorie = categoriser_achat(achat.designation, achat.fournisseur, achat.tva, achat.prix_unitaire_ht, achat.remise_pourcent, produit.coalia, produit.type == "GENERIQUE", produit.type == "MARCHE PRODUITS", produit.pharmupp, produit.lpp)

            achat.save()

            if achat.categorie != prev_categorie:
                print(f'categorie modifiée pour l\'achat {achat.produit} {achat.date} : {prev_categorie} => {achat.categorie}')

        logger.error(f"Succès de la catégorisation des achats. {compteur} modifications effectuées")

    except Exception as e:
        logger.error(f"Echec de la catégorisation des achats : {e}")


def calcul_remises_job():
    from .utils import calculer_remise_theorique
    
    try:
        achats = Achat.objects.all()
        prev_remise = 0
        compteur = 0

        for achat in achats:
            prev_remise = achat.remise_theorique_totale

            produit = Produit_catalogue.objects.get(code=achat.produit, annee=achat.date.year)
            achat = calculer_remise_theorique(produit, achat)

            achat.save()

            if achat.remise_theorique_totale != prev_remise:
                print(f'remise théorique modifiée pour l\'achat {achat.produit} {achat.date} : {prev_remise} => {achat.remise_theorique_totale}')

        logger.error(f"Succès du calcul des remises théoriques. {compteur} modifications effectuées")

    except Exception as e:
        logger.error(f"Echec du calcul des remises théoriques : {e}")