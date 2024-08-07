import os
import pdfplumber
import pytesseract
import logging
import traceback
from datetime import datetime, date
from collections import defaultdict
from django.conf import settings
from django.db.models import Sum, F, Q, ExpressionWrapper, fields
from django.db.models.functions import ExtractMonth, ExtractYear
from openpyxl import Workbook
from decimal import Decimal
from datetime import timedelta
from .constants import DL_FOLDER_PATH_MANUAL, DL_FOLDER_PATH_AUTO, PRODUITS_LPP
from .utils import extraire_format_fournisseur, extraire_date, extraire_numero_facture, extraire_produits
from .utils import process_avoir_remises, process_avoir_remises_deuxieme_page, process_ratrappage_teva, process_releve_alliance, process_tables, process_releve_cerp
from .utils import categoriser_achat, determiner_fournisseur_generique, get_categorie_remise, calculer_remise_theorique, get_taux_avantage_commercial
from .utils import get_data_from_dict, quicksort_dict, quicksort_liste, quicksort_tableau, quicksort_tableau_dates_classiques, convert_date
from .models import Achat, Produit_catalogue, Avoir_remises, Avoir_ratrappage_teva, Releve_alliance, Format_facture, Releve_CERP


BASE_DIR = settings.BASE_DIR
logger = logging.getLogger(__name__)


def handle_uploaded_facture(facture):
    dossier_sauvegarde = DL_FOLDER_PATH_MANUAL

    # On s'assure que le dossier de sauvegarde existe, sinon on le crée
    if not os.path.exists(dossier_sauvegarde):
        os.makedirs(dossier_sauvegarde)

    # Chemin complet pour la sauvegarde de la facture
    chemin_sauvegarde = os.path.join(dossier_sauvegarde, facture.name)

    # Enregistre la facture dans le dossier de sauvegarde
    with open(chemin_sauvegarde, 'wb+') as destination:
        for chunk in facture.chunks():
            destination.write(chunk)

    return chemin_sauvegarde, facture.name


def get_factures_from_directory():
    dossier_factures = DL_FOLDER_PATH_AUTO
    
    try:
        facture_files = [f for f in os.listdir(dossier_factures) if os.path.isfile(os.path.join(dossier_factures, f))]

        facture_paths = [(os.path.join(dossier_factures, f), f) for f in facture_files]
        
        return facture_paths
    
    except FileNotFoundError:
        logger.error("Le dossier des factures n'existe pas ou aucune facture n'a été trouvée.")
        return []
    

def process_factures(facture_paths):
    table_achats_finale = []
    table_produits_finale = []
    events = []
    success = True

    try:
        for index, (facture_path, facture_name) in enumerate(facture_paths, start=1):

            logger.error(f'Traitement du fichier {index}/{len(facture_paths)}')
            print(f'Traitement du fichier {index}/{len(facture_paths)}')

            #Extraction des infos
            table_donnees, table_produits, events_facture, texte_page, tables_page, tables_page_2 = extract_data(facture_path, facture_name)
            #Ajout des infos à la bdd + Contrôles
            events_save = save_data(table_donnees)

            table_achats_finale.extend(table_donnees)
            table_produits_finale.extend(table_produits)
            events.extend(events_facture)
            events.extend(events_save)

        events.insert(0, "Importation terminée.")
        logger.error("Importation terminée.")
        #logger.error(events)

    except Exception as e:
        logger.error(f'Erreur dans l\'exécution de process factures. Erreur : {e}. Traceback : {traceback.format_exc()}')
        success = False

    return success, table_achats_finale, events, texte_page, tables_page, tables_page_2


def extract_data(facture_path, facture_name):
    with pdfplumber.open(facture_path) as pdf:

        table_donnees = []
        table_produits = []
        texte_page_tout = []
        tables_page_toutes = []
        events = []

        for num_page in range(len(pdf.pages)):
            page = pdf.pages[num_page]

            if num_page % 40 == 0:
                logger.error(f'({round((num_page + 1) / len(pdf.pages) * 100, 0)}%) {facture_name} - {num_page + 1} en cours de traitement...')

            texte_page = page.extract_text()
            tables_page = []
            tables_page_2 = page.extract_tables()
                
            #print(texte_page)

            try:
                texte_page_tout.append(texte_page)
                tables_page_toutes.append(tables_page)

                format, fournisseur = extraire_format_fournisseur(texte_page)

                if format is not None:
                    format_inst = Format_facture.objects.get(pk=format)
                else:
                    if "ALLIANCE" in facture_name.upper() and texte_page != "":
                        pdf_img = page.to_image(resolution=600)
                        texte_page = pytesseract.image_to_string(pdf_img.original)
                        texte_page_tout.append("VERSION TESSERACT" + texte_page)
                        format, fournisseur = extraire_format_fournisseur(texte_page)
                        if format is not None:
                            format_inst = Format_facture.objects.get(pk=format)
                        else:
                            events.append(f'Format de facture ALLIANCE non reconnu, page {num_page + 1} - {facture_name}')
                            continue
                    elif texte_page == "":
                        events.append(f'Page vide, page {num_page + 1} - {facture_name}')
                        continue
                    else:
                        events.append(f'Format de facture non reconnu, page {num_page + 1} - {facture_name}')
                        continue

            except Exception as e:
                logger.error(f'Erreur de récupération du format. Format de facture : {format} - fichier : {facture_name}, page : {num_page}. Erreur: {e}')

            try:
                if format_inst.regex_date == "NA":
                    events.append(f'Facture ignorée, page {num_page + 1} - {facture_name}')
                    continue
                tables_page = page.extract_tables(table_settings=format_inst.table_settings)

                date = extraire_date(format, texte_page)
                numero_facture = None
                if format_inst.regex_numero_facture != "NA":
                    numero_facture = extraire_numero_facture(format, texte_page)

                # print(format, fournisseur, date, numero_facture)

                if not date or (format_inst.regex_numero_facture != "NA" and not numero_facture):
                    print(f'error date ou num sur page {num_page + 1} - {facture_name}')
                    logger.error(f'Erreur de récupération de la date ou du numéro de facture donc page ignorée. Date : {date}, numéro de facture : {numero_facture}, format de facture : {format} - fichier : {facture_name}, page : {num_page}')
                    texte_page_tout.append(texte_page)
                    continue

                date = datetime.strptime(date, '%d/%m/%Y').date()

                texte_page_tout.append(texte_page)
                tables_page_toutes.append(tables_page)

            except:  # noqa: E722
                texte_page_tout.append(texte_page)
                tables_page_toutes.append(tables_page)
                continue

            if "AVOIR REMISES CERP" not in format and format != "RATRAPPAGE TEVA" and format != "RELEVE ALLIANCE" and format != "RELEVE CERP":
                # On vérifie si la facture a déjà été traitée, si oui on prévient
                if not Achat.objects.filter(numero_facture=numero_facture):
                    processed_table, events_achats = process_tables(format, tables_page)
                    produits = extraire_produits(format, fournisseur, tables_page)

                    for ligne in range(len(processed_table)):
                        processed_table[ligne].extend([date, facture_name, numero_facture, fournisseur])
                        table_donnees.append(processed_table[ligne])

                    table_produits.extend(produits)
                    if events_achats:
                        events_achats.insert(0, facture_name)
                    events.extend(events_achats)
                    texte_page_tout.append(texte_page)
                    tables_page_toutes.append(tables_page)
                else:
                    events.append(f'La facture {facture_name} - {numero_facture}, page {num_page +1} a déjà été traitée par le passé, elle n\'a donc pas été traitée à nouveau')
            else:
                if format == "AVOIR REMISES CERP":
                    if not Avoir_remises.objects.filter(numero=numero_facture):
                        success = process_avoir_remises(format, tables_page, numero_facture, date)

                        if success:
                            events.append(f'L\'avoir de remises {facture_name} - {numero_facture}, page {num_page +1} a été traité et sauvegardé')
                        else:
                            events.append(f'L\'avoir de remises {facture_name} - {numero_facture}, page {num_page +1} a rencontré une erreur de traitement, il n\'a pas été sauvegardé')
                    else:
                        events.append(f'L\'avoir de remises {facture_name} - {numero_facture}, page {num_page +1} a déjà été traité par le passé, il n\'a donc pas été traité à nouveau')
                elif format == "AVOIR REMISES CERP DEUXIEME PAGE":
                    date_mois_concerne = date.replace(day=1) - timedelta(days=1)
                    mois_concerne = f"{date_mois_concerne.month}/{date_mois_concerne.year}"

                    try:
                        avoir_concerne = Avoir_remises.objects.get(mois_concerne=mois_concerne)
                        if not avoir_concerne or (avoir_concerne and (avoir_concerne.avoirs_exceptionnels > -0.0001 and avoir_concerne.avoirs_exceptionnels < 0.0001)):
                            success = process_avoir_remises_deuxieme_page(format, tables_page, mois_concerne, date)

                            if success:
                                events.append(f'L\'avoir de remises page 2 {facture_name} - {mois_concerne}, page {num_page +1} a été traité et sauvegardé')
                            else:
                                events.append(f'L\'avoir de remises page 2 {facture_name} - {mois_concerne}, page {num_page +1} a rencontré une erreur de traitement, il n\'a pas été sauvegardé')
                        else:
                            events.append(f'L\'avoir de remises page 2 {facture_name} - {mois_concerne}, page {num_page +1} a déjà été traité par le passé, il n\'a donc pas été traité à nouveau')
                    except Exception as e:
                        events.append(f'L\'avoir de remises concerné par la page 2 {facture_name} - {mois_concerne}, page {num_page +1} n\'a pas pu être importé : {e}')
                elif format == "RATRAPPAGE TEVA":
                    events.append(f'Avoir de ratrappage teva {facture_name} - {numero_facture}, détecté, non traité car valeurs saisies manuellement (voir avec administrateur)')
                    continue
                    if not Avoir_ratrappage_teva.objects.filter(numero=numero_facture):
                        success = process_ratrappage_teva(format, tables_page, texte_page, numero_facture, date)

                        if success:
                            events.append(f'L\'avoir de ratrappage teva {facture_name} - {numero_facture}, page {num_page +1} a été traité et sauvegardé')
                        else:
                            events.append(f'L\'avoir de ratrappage teva {facture_name} - {numero_facture}, page {num_page +1} a rencontré une erreur de traitement, il n\'a pas été sauvegardé')
                    else:
                        events.append(f'L\'avoir de ratrappage teva {facture_name} - {numero_facture}, page {num_page +1} a déjà été traité par le passé, il n\'a donc pas été traité à nouveau')
                elif format == "RELEVE ALLIANCE":
                    #events.append(f'Relevé Alliance {facture_name} - {numero_facture} - {date}, détecté, non traité (voir avec administrateur)')
                    created = not Releve_alliance.objects.filter(numero=numero_facture).exists()
                    success = process_releve_alliance(texte_page, numero_facture, date)

                    if success:
                        if created:
                            events.append(f'Le relevé Alliance {facture_name} - {numero_facture}, page {num_page + 1} a été ajouté')
                        else:
                            events.append(f'Le relevé Alliance {facture_name} - {numero_facture}, page {num_page + 1} a été édité')
                    else:
                        events.append(f'Le relevé Alliance {facture_name} - {numero_facture}, page {num_page + 1} a rencontré une erreur de traitement, il n\'a pas été sauvegardé')
                elif format == "RELEVE CERP":
                    created = not Releve_CERP.objects.filter(numero=numero_facture).exists()
                    success = process_releve_cerp(texte_page, numero_facture, date)

                    if success:
                        if created:
                            events.append(f'Le relevé CERP {facture_name} - {numero_facture}, page {num_page + 1} a été ajouté')
                        else:
                            events.append(f'Le relevé CERP {facture_name} - {numero_facture}, page {num_page + 1} a été édité')
                    else:
                        events.append(f'Le relevé CERP {facture_name} - {numero_facture}, page {num_page + 1} a rencontré une erreur de traitement, il n\'a pas été sauvegardé')
                else:
                    events.append(f'Format reconnu pour {facture_name} - {numero_facture} - {date}: {format}, mais non traité (voir avec administrateur)')
                    continue

    return table_donnees, table_produits, events, texte_page_tout, tables_page_toutes, tables_page_2


def save_data(table_donnees):
    #Sauvegarde les données d'une facture
    events = []

    #Enregistrement des achats dans la bdd
    for ligne in table_donnees:

        dictligne = {
            "code": ligne[0],
            "designation": ligne[1],
            "nb_boites": ligne[2],
            "prix_unitaire_ht": ligne[3],
            "prix_unitaire_remise_ht": ligne[4],
            "remise_pourcent": ligne[5],
            "montant_ht_hors_remise": ligne[6],
            "montant_ht": ligne[7],
            "tva": ligne[8],
            "date": ligne[9],
            "fichier_provenance": ligne[10],
            "numero_facture": ligne[11],
            "fournisseur": ligne[12],
        }

        #CATEGORISATION DE L'ACHAT

        #Si le produit existe, on récupère les paramèrtres coalia et générique
        coalia = False
        generique = False
        try:
            produit = Produit_catalogue.objects.get(code=dictligne["code"], annee=dictligne["date"].year)
            try:
                generique = (produit.type == "GENERIQUE")
                marche_produits = (produit.type == "MARCHE PRODUITS")
                pharmupp = produit.pharmupp
                lpp = produit.lpp
                # SI LA TVA MANQUE ON L'AJOUTE AVANT LA CATEGORISATION
                if dictligne["tva"] != 0:
                    if produit.tva > -0.0001 and produit.tva < 0.0001:
                        produit.tva = dictligne["tva"]
                        produit.save()
                # SI FACTURE COALIA, LE PRODUIT EST MARQUE COMME VENDU CHEZ COALIA POUR LES FUTURS UPP
                if dictligne["fournisseur"] == "CERP COALIA" and not produit.coalia:
                    produit.coalia = True
                    produit.save()

                coalia = produit.coalia
            except Exception as e:
                logger.error(f"Erreur lors de l'importation des données du produit existant : {e}. Traceback : {traceback.format_exc()}")

        except:  # noqa: E722
            coalia = (dictligne["fournisseur"] == "CERP COALIA")
            generique = (dictligne["fournisseur"] == "TEVA" or dictligne["fournisseur"] == "EG" or dictligne["fournisseur"] == "BIOGARAN"  or dictligne["fournisseur"] == "ARROW")
            marche_produits = False
            pharmupp = False
            lpp = False

        #MODIFIER LA CATEGORISATION POUR RECUP DEPUIS LE PRODUIT LE MARCHE PRODUITS
        new_categorie = categoriser_achat(dictligne["designation"], dictligne["fournisseur"], dictligne["tva"], dictligne["prix_unitaire_ht"], dictligne["remise_pourcent"], coalia, generique, marche_produits, pharmupp, lpp)

        #IMPORTATION DU PRODUIT POUR AVOIR LA REMISE THEORIQUE
        if not Produit_catalogue.objects.filter(code=dictligne["code"], annee=dictligne["date"].year):
            #SI LE PRODUIT N'EXISTE PAS IL FAUT LE CREER

            new_coalia = False
            new_fournisseur_generique = ""
            new_type = ""
            new_lpp = any(element in dictligne["designation"].upper() for element in PRODUITS_LPP)

            if new_categorie == "COALIA":
                new_coalia = True
            elif new_categorie.split()[0].upper() == "GENERIQUE":
                new_fournisseur_generique = determiner_fournisseur_generique(dictligne["designation"], dictligne["fournisseur"])
                new_type = "GENERIQUE"

            #if dictligne["date"].year == datetime.now().year:
                # SI NOUVEAU PRODUIT DE CETTE ANNEE, ON REGARDE SI ON A PLUS D'INFOS SUR LE PRODUIT DE L'ANNEE PRECEDENTE
                #new_type, new_fournisseur_generique, new_lpp, new_remise_grossiste, new_remise_direct = check_last_year(dictligne['code'], new_fournisseur_generique, new_type)

            nouveau_produit = Produit_catalogue(
                code = dictligne["code"],
                annee = int(dictligne["date"].year),
                designation = dictligne["designation"],
                type = new_type,
                fournisseur_generique = new_fournisseur_generique,
                coalia = new_coalia,
                lpp = new_lpp,
                remise_grossiste = "",
                remise_direct = "",
                tva = dictligne["tva"],
                date_creation = datetime.now(),
                creation_auto = True
            )
            nouveau_produit.save()
            events.append(f'Le produit suivant a été créé sans remise, merci de compléter sa fiche dans l\'interface admin : {ligne[0]} - {ligne[1]}')

        else:
            #produit existe => mise à jour en fonction de la catégorie
            produit = Produit_catalogue.objects.get(code=dictligne["code"], annee=dictligne["date"].year)
            if produit.type == "":
                if new_categorie.split()[0].upper() == "GENERIQUE":
                    produit.type = "GENERIQUE"
                    produit.save()
                    logger.error(f"Produit existant {dictligne['code']} {dictligne['date'].year} typé en générique. Facture {dictligne['fichier_provenance']} - {dictligne['numero_facture']}.")
                elif new_categorie == "MARCHE PRODUITS":
                    produit.type = new_categorie
                    produit.save()
                    logger.error(f"Produit existant {dictligne['code']} {dictligne['date'].year} typé en marché produits. Facture {dictligne['fichier_provenance']} - {dictligne['numero_facture']}.")
            if new_categorie.split()[0].upper() == "GENERIQUE" and produit.fournisseur_generique == "":
                new_fournisseur_generique = determiner_fournisseur_generique(dictligne["designation"], dictligne["fournisseur"])
                produit.fournisseur_generique = new_fournisseur_generique
                produit.save()
                logger.error(f"Fournisseur générique {dictligne['code']} {dictligne['date'].year} complété : {new_fournisseur_generique}. Facture {dictligne['fichier_provenance']} - {dictligne['numero_facture']}.")
            if not produit.lpp and any(element in dictligne["designation"].upper() for element in PRODUITS_LPP):
                produit.lpp = True
                produit.save()
                logger.error(f"Produit existant {dictligne['code']} {dictligne['date'].year} passé en lpp. Facture {dictligne['fichier_provenance']} - {dictligne['numero_facture']}.")

        #ON IMPORTE LE PRODUIT A NOUVEAU
        produit = Produit_catalogue.objects.get(code=dictligne["code"], annee=dictligne["date"].year)

        #ON CREE L'ACHAT
        nouvel_achat = Achat(
            code = dictligne["code"],
            produit = produit,
            designation = dictligne["designation"],
            nb_boites = dictligne["nb_boites"],
            prix_unitaire_ht = dictligne["prix_unitaire_ht"],
            prix_unitaire_remise_ht = dictligne["prix_unitaire_remise_ht"],
            remise_pourcent = dictligne["remise_pourcent"],
            montant_ht_hors_remise = dictligne["montant_ht_hors_remise"],
            montant_ht = dictligne["montant_ht"],
            tva = dictligne["tva"],
            date = dictligne["date"],
            fichier_provenance = dictligne["fichier_provenance"],
            numero_facture = dictligne["numero_facture"],
            fournisseur = dictligne["fournisseur"],
            categorie = new_categorie,
            categorie_remise = get_categorie_remise(produit.fournisseur_generique, dictligne["fournisseur"], dictligne["remise_pourcent"])
        )
        
        #ON CALCULE LA REMISE THEORIQUE
        nouvel_achat = calculer_remise_theorique(produit, nouvel_achat)

        nouvel_achat.save()

    return events


def telecharger_excel(data, modele):

    try:
        workbook = Workbook()
        sheet = workbook.active

        champs = data[0].keys()

        if modele == "Achat":
            sheet.append(
                [
                    'Code',
                    'Designation',
                    'Nb de boites',
                    'Prix unitaire ht',
                    'Prix unitaire remisé',
                    'Remise en pourcents',
                    'Montant ht avant remise',
                    'Montant ht après remise',
                    'Remise grossiste présente dans le catalogue',
                    'Remise direct présente dans le catalogue',
                    'Remise théorique calculée',
                    'TVA',
                    'Date de la facture',
                    'Numero facture',
                    'Format de la facture',
                    'Categorie',
                    'Categorie de remise si applicable (TEVA, EG)',
                    'Année associée au produit dans le catalogue',
                    'Fournisseur générique',
                    'Vendu par Coalia',
                    'Présent sur Pharmupp',
                    'Indiqué LPP sur le site CERP',
                    'Créé automatiquement par l\'outil'
                ]
            )
        elif modele == "Releve_alliance":
            sheet.append(
                [
                    'numero',
                    'date',
                    'net_a_payer',
                    'montant_grossiste',
                    'echeance_grossiste',
                    'montant_short_list',
                    'echeance_short_list',
                    'avantages_commerciaux',
                    'frais_generaux',
                    'facturation_services'
                ]
            )

        for instance in data:
            sheet.append([instance[champ] for champ in champs])

        from io import BytesIO
        excel_file = BytesIO()
        workbook.save(excel_file)
        excel_file.seek(0)

        return excel_file

    except Exception as e:
        logger.error(f'Erreur de génération du fichier Excel {modele} : {e}')
        return None


# -----------------------------------

# -------- TABLEAUX -----------------

# -----------------------------------


# -----------------------------------

# -------- TABLEAU SYNTHESE CERP ----

# -----------------------------------


def generer_tableau_synthese():

    tableau_synthese_assiette_globale = []
    tableau_synthese_autres = []
    data_dict = {}

    categories_assiette_globale = [
        'Mois/Année',
        '<450€ tva 2,1% TOTAL HT = ASSIETTE GLOBALE',
        'ASSIETTE GLOBALE -9%',
        'REMISE ASSIETTE GLOBALE THEORIQUE',
        'REMISE ASSIETTE GLOBALE OBTENUE',
        'DIFFERENCE REMISE ASSIETTE GLOBALE',
        '>450€ tva 2,1% TOTAL HT',
        'NB BOITES >450€',
        'REMISE THEORIQUE >450€',
        'REMISE >450€ OBTENUE',
        'PARAPHARMACIE TOTAL HT',
        'REMISE PARAPHARMACIE THEORIQUE',
        'REMISE PARAPHARMACIE OBTENUE',
        'LPP 5,5 OU 10% TOTAL HT',
        'REMISE LPP 5,5 OU 10% THEORIQUE',
        'REMISE LPP 5,5 OU 10% OBTENUE',
        'LPP 20% TOTAL HT',
        'REMISE LPP 20% THEORIQUE',
        'REMISE LPP 20% OBTENUE',
        'REMISE AVANTAGE COMMERCIAL THEORIQUE',
        'REMISE AVANTAGE COMMERCIAL OBTENUE',
        'SOUS TOTAL REMISE GROSSISTE THEORIQUE',
        'SOUS TOTAL REMISE GROSSISTE OBTENUE',
        'DIFFERENCE SOUS TOTAL REMISE GROSSISTE',
        'REMISE GROSSISTE TOTALE THEORIQUE',
        'REMISE GROSSISTE TOTALE OBTENUE',
        'DIFFERENCE REMISE GROSSISTE',
    ]

    categories_autres = [
        'Mois/Année',
        'GENERIQUE 2,1% TOTAL HT',
        'GENERIQUE 5,5% TOTAL HT',
        'GENERIQUE 10% TOTAL HT',
        'GENERIQUE 20% TOTAL HT',
        "GENERIQUE TOTAL HT",
        'NON GENERIQUE DIRECT LABO TOTAL HT',
        'OTC DIRECT LABO TOTAL HT',
        'NON REMBOURSABLE DIRECT LABO TOTAL HT',
        'NON GENERIQUE GROSSISTE TOTAL HT',
        'OTC GROSSISTE TOTAL HT',
        'NON REMBOURSABLE GROSSISTE TOTAL HT',
        'MARCHE PRODUITS TOTAL HT',
        'MARCHE PRODUITS REMISE OBTENUE HT',
        'MAGASIN GENERAL TOTAL HT',
        'MAGASIN GENERAL REMISE OBTENUE HT',
        'UPP TOTAL HT',
        'UPP REMISE OBTENUE HT',
        'COALIA TOTAL HT',
        'COALIA REMISE OBTENUE HT',
        'PHARMAT TOTAL HT',
        'TOTAL GENERAL HT',
    ]

    displayed_categories_assiette_globale = [
        'Mois/Année',
        'ASSIETTE GLOBALE : CA < 450€',
        'ASSIETTE GLOBALE -9%',
        'REMISE ASSIETTE GLOBALE THEORIQUE 2,5%',
        'REMISE ASSIETTE GLOBALE OBTENUE 2,5%',
        'DIFFERENCE REMISE ASSIETTE GLOBALE',
        'CA >450€',
        'NB BOITES > 450€',
        'REMISE > 450€ THEORIQUE: 15€/BTE',
        'REMISE >450€ OBTENUE',
        'PARAPHARMACIE TOTAL HT',
        'REMISE PARAPHARMACIE THEORIQUE',
        'REMISE PARAPHARMACIE OBTENUE',
        'LPP 5,5 OU 10% TOTAL HT',
        'REMISE LPP 5,5 OU 10% THEORIQUE',
        'REMISE LPP 5,5 OU 10% OBTENUE',
        'LPP 20% TOTAL HT',
        'REMISE LPP 20% THEORIQUE',
        'REMISE LPP 20% OBTENUE',
        'AVANTAGE COMMERCIAL THEORIQUE',
        'AVANTAGE COMMERCIAL OBTENU',
        'SOUS TOTAL REMISE GROSSISTE THEORIQUE',
        'SOUS TOTAL REMISE GROSSISTE OBTENUE',
        'DIFFERENCE SOUS TOTAL REMISE GROSSISTE',
        'TOTAL REMISE GROSSISTE THEORIQUE',
        'TOTAL REMISE GROSSISTE OBTENUE',
        'DIFFERENCE TOTAL REMISE GROSSISTE',
    ]

    explications = {
        "REMISE ASSIETTE GLOBALE OBTENUE 2,5%": "Ligne spécialités pharmaceutiques des avoirs de remises",
        "DIFFERENCE REMISE ASSIETTE GLOBALE": "Remise obtenue 2,5% - remise théorique 2,5%",
        "SOUS TOTAL REMISE GROSSISTE THEORIQUE": "Somme (assiette globale + LPP + parapharmacie) x 3,8% théorique",
        "TOTAL REMISE GROSSISTE THEORIQUE": "Somme (assiette globale + LPP + parapharmacie) x 3,8% + remise > 450€ theorique",
        "SOUS TOTAL REMISE GROSSISTE OBTENUE": "Somme (assiette globale + LPP + parapharmacie) x 3,8% obtenue",
        "DIFFERENCE SOUS TOTAL REMISE GROSSISTE": "Sous total remise grossiste obtenue - sous total remise grossiste théorique",
        "TOTAL REMISE GROSSISTE OBTENUE": "Somme des remises obtenues : remise spécialités pharmaceutiques (assiette globale) + remise LPP + remise parapharmacie + avantage commercial + remise >450€",
        "DIFFERENCE REMISE GROSSISTE": "Total remise grossiste obtenue - total remise grossiste théorique",
    }

    displayed_categories_autres = [
        'Mois/Année',
        'GENERIQUE 2,1% TOTAL HT',
        'GENERIQUE 5,5% TOTAL HT',
        'GENERIQUE 10% TOTAL HT',
        'GENERIQUE 20% TOTAL HT',
        'GENERIQUE TOTAL HT',
        'NON GENERIQUE DIRECT LABO TOTAL HT',
        'OTC DIRECT LABO TOTAL HT',
        'NON REMBOURSABLE DIRECT LABO TOTAL HT',
        'NON GENERIQUE GROSSISTE TOTAL HT',
        'OTC GROSSISTE TOTAL HT',
        'NON REMBOURSABLE GROSSISTE TOTAL HT',
        'MARCHE PRODUITS TOTAL HT',
        'MARCHE PRODUITS REMISE OBTENUE HT',
        'MAGASIN GENERAL TOTAL HT',
        'MAGASIN GENERAL REMISE OBTENUE HT',
        'UPP TOTAL HT',
        'UPP REMISE OBTENUE HT',
        'COALIA TOTAL HT',
        'COALIA REMISE OBTENUE HT',
        'PHARMAT TOTAL HT',
        'TOTAL GENERAL HT',
    ]

    map_assglob = {colonne: i for i, colonne in enumerate(categories_assiette_globale)}
    map_autres = {colonne: i for i, colonne in enumerate(categories_autres)}

    try:

        data = (
            Achat.objects
            .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
            .values('mois', 'annee', 'categorie')
            .annotate(
                total_ht_hors_remise=Sum('montant_ht_hors_remise'), 
                remise_obtenue=Sum(ExpressionWrapper(F('remise_pourcent') * F('montant_ht_hors_remise'), output_field=fields.DecimalField()))
            )
        )

        #On nettoie et organise le data dict
        for entry in data:
            mois_annee = f"{entry['mois']}/{entry['annee']}"
            categorie = entry['categorie']
            total_ht_hors_remise = entry['total_ht_hors_remise']
            remise_obtenue = entry['remise_obtenue']
            #remise_theorique_totale = entry['remise_theorique_totale']

            # Si la clé mois_annee n'existe pas encore dans le dictionnaire, créez-la
            if mois_annee not in data_dict:
                data_dict[mois_annee] = {}

            # Remplissage du dictionnaire avec les valeurs
            data_dict[mois_annee][f"{categorie} TOTAL HT"] = total_ht_hors_remise
            data_dict[mois_annee][f"{categorie} REMISE OBTENUE HT"] = remise_obtenue
            #data_dict[mois_annee][f"{categorie} REMISE HT"] = remise_theorique_totale

        #Calcul du total général CERP (pour déterminer le taux d'avantage commercial et la remise LPP)
        data_dict_total_cerp_mois = get_data_dict_total_cerp_mois()

        #pour chaque catégorie connue, on ajoute la somme dans le tableau
        tableau_synthese_assiette_globale = remplir_valeurs_categories(data_dict, tableau_synthese_assiette_globale, categories_assiette_globale)
        tableau_synthese_autres = remplir_valeurs_categories(data_dict, tableau_synthese_autres, categories_autres)

        #REMPLISSAGE DES COLONNES ASSIETTE GLOBALE
        tableau_synthese_assiette_globale = traitement_colonnes_assiette_globale(tableau_synthese_assiette_globale, map_assglob, data_dict_total_cerp_mois)
        tableau_synthese_autres = traitement_totaux_autres(tableau_synthese_assiette_globale, tableau_synthese_autres, map_assglob, map_autres)

        #REMPLISSAGE REMISES OBTENUES ASSIETTE GLOBALE
        tableau_synthese_assiette_globale = remplir_remises_obtenues(tableau_synthese_assiette_globale, map_assglob)

        #LIGNES DE TOTAUX PAR ANNEE
        tableau_synthese_assiette_globale = totaux_pourcentages_par_annee(tableau_synthese_assiette_globale, categories_assiette_globale, map_assglob)
        tableau_synthese_autres = totaux_pourcentages_par_annee(tableau_synthese_autres, categories_autres, map_autres)

        return tableau_synthese_assiette_globale, displayed_categories_assiette_globale, tableau_synthese_autres, displayed_categories_autres, explications
    
    except Exception as e:
        logger.error(f"Erreur de génération du tableau synthèse, erreur {e}. Traceback : {traceback.format_exc()}")
        return tableau_synthese_assiette_globale, displayed_categories_assiette_globale, tableau_synthese_autres, displayed_categories_autres, explications
    

def remplir_valeurs_categories(data_dict, tableau, categories):

    i = 0

    for mois_annee, values in data_dict.items():
        tableau.append([mois_annee])
        #On parcourt les colonnes grace à la liste des titres de colonne
        for cat in categories[1:]:
            #Si la colonne n'est jamais trouvée, on met la valeur à 0
            found = False
            if "TOTAL HT" in cat:
                for categorie, montant in values.items():
                    if categorie in cat:
                        tableau[i].append(round(montant, 2))
                        found = True
            elif "REMISE OBTENUE HT" in cat:
                for categorie, montant in values.items():
                    if categorie in cat:
                        tableau[i].append(round(montant, 2))
                        found = True
            if not found:
                tableau[i].append(0.00)
        i += 1

    tableau = quicksort_tableau(tableau)

    return tableau


def traitement_colonnes_assiette_globale(tableau, map_assglob, data_dict_total_cerp_mois):

    try:
        data_dict_nb_boites = extract_nb_boites()

        for ligne in range(len(tableau)):
            if tableau[ligne][0] in data_dict_nb_boites:
                tableau[ligne][map_assglob["NB BOITES >450€"]] = data_dict_nb_boites[tableau[ligne][0]]["Total_boites"]
            else:
                tableau[ligne][map_assglob["NB BOITES >450€"]] = round(Decimal(0), 0)

        for ligne in range(len(tableau)):
            try:
                taux_de_base, taux_avantage, taux_lpp = get_taux_avantage_commercial(tableau[ligne][map_assglob["Mois/Année"]], data_dict_total_cerp_mois[tableau[ligne][map_assglob["Mois/Année"]]]["Total_cerp"])
                #print(tableau[ligne][map_assglob["Mois/Année"]], data_dict_total_cerp_mois[tableau[ligne][map_assglob["Mois/Année"]]]["Total_cerp"], round(taux_de_base, 3), round(taux_avantage, 3), round(taux_lpp, 3))
            except KeyError:
                taux_de_base, taux_avantage, taux_lpp = 0, 0, 0

            tableau[ligne][map_assglob["ASSIETTE GLOBALE -9%"]] = round(Decimal(tableau[ligne][map_assglob["<450€ tva 2,1% TOTAL HT = ASSIETTE GLOBALE"]]) * Decimal(0.91), 2)
            tableau[ligne][map_assglob["REMISE ASSIETTE GLOBALE THEORIQUE"]] = round(Decimal(tableau[ligne][map_assglob["ASSIETTE GLOBALE -9%"]]) * taux_de_base, 2)
            tableau[ligne][map_assglob["REMISE THEORIQUE >450€"]] = round(Decimal(tableau[ligne][map_assglob["NB BOITES >450€"]]) * Decimal(15), 2)

            tableau[ligne][map_assglob["REMISE PARAPHARMACIE THEORIQUE"]] = round(Decimal(tableau[ligne][map_assglob["PARAPHARMACIE TOTAL HT"]]) * Decimal(0.91) * (taux_de_base + taux_avantage), 2)
            tableau[ligne][map_assglob["REMISE LPP 5,5 OU 10% THEORIQUE"]] = round(Decimal(tableau[ligne][map_assglob["LPP 5,5 OU 10% TOTAL HT"]]) * Decimal(0.91) * (taux_lpp), 2)
            tableau[ligne][map_assglob["REMISE LPP 20% THEORIQUE"]] = round(Decimal(tableau[ligne][map_assglob["LPP 20% TOTAL HT"]]) * Decimal(0.91) * (taux_lpp), 2)
            tableau[ligne][map_assglob["REMISE AVANTAGE COMMERCIAL THEORIQUE"]] = round(Decimal(tableau[ligne][map_assglob["ASSIETTE GLOBALE -9%"]]) * taux_avantage, 2)

            sous_total = round(Decimal(tableau[ligne][map_assglob["ASSIETTE GLOBALE -9%"]]) * (taux_de_base + taux_avantage), 2)
            sous_total += Decimal(tableau[ligne][map_assglob["REMISE PARAPHARMACIE THEORIQUE"]])
            sous_total += Decimal(tableau[ligne][map_assglob["REMISE LPP 5,5 OU 10% THEORIQUE"]])
            sous_total += Decimal(tableau[ligne][map_assglob["REMISE LPP 20% THEORIQUE"]])
            tableau[ligne][map_assglob["SOUS TOTAL REMISE GROSSISTE THEORIQUE"]] = sous_total
            
            remise_totale = round(Decimal(tableau[ligne][map_assglob["REMISE ASSIETTE GLOBALE THEORIQUE"]]), 2)
            remise_totale += round(Decimal(tableau[ligne][map_assglob["REMISE THEORIQUE >450€"]]), 2)
            remise_totale += Decimal(tableau[ligne][map_assglob["REMISE PARAPHARMACIE THEORIQUE"]])
            remise_totale += Decimal(tableau[ligne][map_assglob["REMISE LPP 5,5 OU 10% THEORIQUE"]])
            remise_totale += Decimal(tableau[ligne][map_assglob["REMISE LPP 20% THEORIQUE"]])
            remise_totale += round(Decimal(tableau[ligne][map_assglob["ASSIETTE GLOBALE -9%"]]) * taux_avantage, 2)
            tableau[ligne][map_assglob["REMISE GROSSISTE TOTALE THEORIQUE"]] = remise_totale

    except Exception as e:
        logger.error(f'Erreur de traitement des colonnes assiette globale : {e}. Traceback : {traceback.format_exc()}')

    return tableau


def remplir_remises_obtenues(tableau, map_assglob):

    for ligne in range(len(tableau)):
        avoir_remises = Avoir_remises.objects.filter(mois_concerne=tableau[ligne][0]).first()
        
        if avoir_remises is not None:
            tableau[ligne][map_assglob["REMISE ASSIETTE GLOBALE OBTENUE"]] = round(avoir_remises.specialites_pharmaceutiques_remise, 2)
            tableau[ligne][map_assglob["REMISE LPP 5,5 OU 10% OBTENUE"]] = round(avoir_remises.lpp_cinq_ou_dix_remise, 2)
            tableau[ligne][map_assglob["REMISE LPP 20% OBTENUE"]] = round(avoir_remises.lpp_vingt_remise, 2)
            tableau[ligne][map_assglob["REMISE PARAPHARMACIE OBTENUE"]] = round(avoir_remises.parapharmacie_remise, 2)
            tableau[ligne][map_assglob["REMISE AVANTAGE COMMERCIAL OBTENUE"]] = round(avoir_remises.avantage_commercial, 2)
            tableau[ligne][map_assglob["REMISE >450€ OBTENUE"]] = round(avoir_remises.avoirs_exceptionnels, 2)

            tableau[ligne][map_assglob["DIFFERENCE REMISE ASSIETTE GLOBALE"]] = (Decimal(tableau[ligne][map_assglob["REMISE ASSIETTE GLOBALE OBTENUE"]])
                                                                       - Decimal(tableau[ligne][map_assglob["REMISE ASSIETTE GLOBALE THEORIQUE"]])
                                                                    )

            tableau[ligne][map_assglob["SOUS TOTAL REMISE GROSSISTE OBTENUE"]] = round(avoir_remises.specialites_pharmaceutiques_remise, 2)
            tableau[ligne][map_assglob["SOUS TOTAL REMISE GROSSISTE OBTENUE"]] += round(avoir_remises.lpp_cinq_ou_dix_remise, 2)
            tableau[ligne][map_assglob["SOUS TOTAL REMISE GROSSISTE OBTENUE"]] += round(avoir_remises.lpp_vingt_remise, 2)
            tableau[ligne][map_assglob["SOUS TOTAL REMISE GROSSISTE OBTENUE"]] += round(avoir_remises.parapharmacie_remise, 2)
            tableau[ligne][map_assglob["SOUS TOTAL REMISE GROSSISTE OBTENUE"]] += round(avoir_remises.avantage_commercial, 2)

            tableau[ligne][map_assglob["DIFFERENCE SOUS TOTAL REMISE GROSSISTE"]] = (Decimal(tableau[ligne][map_assglob["SOUS TOTAL REMISE GROSSISTE OBTENUE"]])
                                                                       - Decimal(tableau[ligne][map_assglob["SOUS TOTAL REMISE GROSSISTE THEORIQUE"]])
                                                                    )

            tableau[ligne][map_assglob["REMISE GROSSISTE TOTALE OBTENUE"]] = tableau[ligne][map_assglob["REMISE ASSIETTE GLOBALE OBTENUE"]] 
            tableau[ligne][map_assglob["REMISE GROSSISTE TOTALE OBTENUE"]] += tableau[ligne][map_assglob["REMISE LPP 5,5 OU 10% OBTENUE"]]
            tableau[ligne][map_assglob["REMISE GROSSISTE TOTALE OBTENUE"]] += tableau[ligne][map_assglob["REMISE LPP 20% OBTENUE"]]
            tableau[ligne][map_assglob["REMISE GROSSISTE TOTALE OBTENUE"]] += tableau[ligne][map_assglob["REMISE PARAPHARMACIE OBTENUE"]] 
            tableau[ligne][map_assglob["REMISE GROSSISTE TOTALE OBTENUE"]] += tableau[ligne][map_assglob["REMISE AVANTAGE COMMERCIAL OBTENUE"]]
            tableau[ligne][map_assglob["REMISE GROSSISTE TOTALE OBTENUE"]] += tableau[ligne][map_assglob["REMISE >450€ OBTENUE"]]

            tableau[ligne][map_assglob["DIFFERENCE REMISE GROSSISTE"]] = (Decimal(tableau[ligne][map_assglob["REMISE GROSSISTE TOTALE OBTENUE"]])
                                                                       - Decimal(tableau[ligne][map_assglob["REMISE GROSSISTE TOTALE THEORIQUE"]])
                                                                    )

    return tableau


def traitement_totaux_autres(tableau_assiette_globale, tableau_autres, map_assglob, map_autres):
    
    #On traite la dernière colonne du tableau autres

    for ligne in range(len(tableau_autres)):
        total_generiques = Decimal(tableau_autres[ligne][map_autres["GENERIQUE 2,1% TOTAL HT"]])
        total_generiques += Decimal(tableau_autres[ligne][map_autres["GENERIQUE 5,5% TOTAL HT"]])
        total_generiques += Decimal(tableau_autres[ligne][map_autres["GENERIQUE 10% TOTAL HT"]])
        total_generiques += Decimal(tableau_autres[ligne][map_autres["GENERIQUE 20% TOTAL HT"]])
        tableau_autres[ligne][map_autres["GENERIQUE TOTAL HT"]] = total_generiques

        total_general = Decimal(tableau_assiette_globale[ligne][map_assglob["<450€ tva 2,1% TOTAL HT = ASSIETTE GLOBALE"]])
        total_general += Decimal(tableau_assiette_globale[ligne][map_assglob[">450€ tva 2,1% TOTAL HT"]])
        total_general += Decimal(tableau_assiette_globale[ligne][map_assglob["PARAPHARMACIE TOTAL HT"]])
        total_general += Decimal(tableau_assiette_globale[ligne][map_assglob["LPP 5,5 OU 10% TOTAL HT"]]) 
        total_general += Decimal(tableau_assiette_globale[ligne][map_assglob["LPP 20% TOTAL HT"]])
        total_general += Decimal(tableau_autres[ligne][map_autres["GENERIQUE TOTAL HT"]]) 
        total_general += Decimal(tableau_autres[ligne][map_autres["NON GENERIQUE DIRECT LABO TOTAL HT"]])
        total_general += Decimal(tableau_autres[ligne][map_autres["OTC DIRECT LABO TOTAL HT"]])
        total_general += Decimal(tableau_autres[ligne][map_autres["NON REMBOURSABLE DIRECT LABO TOTAL HT"]])
        total_general += Decimal(tableau_autres[ligne][map_autres["NON GENERIQUE GROSSISTE TOTAL HT"]])
        total_general += Decimal(tableau_autres[ligne][map_autres["OTC GROSSISTE TOTAL HT"]])
        total_general += Decimal(tableau_autres[ligne][map_autres["NON REMBOURSABLE GROSSISTE TOTAL HT"]])
        total_general += Decimal(tableau_autres[ligne][map_autres["MARCHE PRODUITS TOTAL HT"]]) 
        total_general += Decimal(tableau_autres[ligne][map_autres["UPP TOTAL HT"]])
        total_general += Decimal(tableau_autres[ligne][map_autres["COALIA TOTAL HT"]]) 
        total_general += Decimal(tableau_autres[ligne][map_autres["PHARMAT TOTAL HT"]])
        tableau_autres[ligne][-1] = total_general
    
    return tableau_autres


def totaux_pourcentages_par_annee(tableau, categories, map):
    ligne = 0
    ligne_annee_precedente = -1

    while ligne < len(tableau):
        #print(f'ligne: {ligne}, derniere ligne: {len(tableau) - 1}')
        if tableau[ligne][0] != "" and tableau[ligne][0] != "TOTAL" and tableau[ligne - 1][0] != "TOTAL":
            
            traitement = False
            double_traitement = False

            if ligne == 0:
                if ligne == len(tableau) - 1:
                    traitement = True
                    # on simule l'avance sur la prochaine ligne
                    ligne += 1
            elif ligne == len(tableau) - 1:
                #on regarde si il y a changement à l'avant derniere ligne
                #print(f'derniere ligne : ligne {ligne} / {len(tableau) - 1}. Nb elements : {len(tableau)}')
                if tableau[ligne - 1][0] != "" and tableau[ligne - 1][0] != "Mois/Année" and tableau[ligne - 1][0] != "Huitaine":
                    if convert_date(tableau[ligne][0]).year != convert_date(tableau[ligne - 1][0]).year:
                        traitement = True
                        double_traitement = True
                    else:
                        traitement = True
                        # on simule l'avance sur la prochaine ligne
                        ligne += 1
                else:
                    traitement = True
                    ligne += 1
                
            elif tableau[ligne - 1][0] != "" and tableau[ligne - 1][0] != "Mois/Année" and tableau[ligne - 1][0] != "Huitaine":
                # print(tableau[ligne][0], convert_date(tableau[ligne][0]).year)
                if convert_date(tableau[ligne][0]).year != convert_date(tableau[ligne - 1][0]).year:
                    traitement = True
                    #print("comparaison de dates")
            else:
                pass
                #print("ne correspond à aucun cas")
            
            #print(traitement)
            if traitement:
                # print(traitement, tableau[ligne - 1][0], f'TOTAL {convert_date(tableau[ligne - 1][0]).year}')
                # ici, ligne est la ligne juste après le changement de date, donc on va insérer les totaux avant
                # Ligne de totaux initialisée avec un vide pour la colonne mois annee
                totaux = [f'TOTAL {convert_date(tableau[ligne - 1][0]).year}']
                for colonne in range(1, len(tableau[0])):
                    try:
                        if not categories[colonne].startswith("%") and categories[colonne] != "Cumul mois":
                            total = Decimal(0)
                            for ligne_annee in range(ligne_annee_precedente + 1, ligne):
                                total += Decimal(tableau[ligne_annee][colonne])
                            totaux.append(round(total, 2))
                        else:
                            totaux.append("")
                    except:  # noqa: E722
                        totaux.append("")
                        continue

                #print(f'totaux calculés entre {ligne_annee_precedente + 1} et {ligne - 1}')

                #ligne de pourcentages initialisée avec un vide pour la colonne mois annee
                pourcentages = calcul_pourcentages(len(tableau[0]), totaux, categories, map)

                tableau.insert(ligne, totaux)
                tableau.insert(ligne + 1, pourcentages)
                if ligne + 1 != len(tableau) - 1:
                    tableau.insert(ligne + 2, categories)
                #print(f'totaux inseres en {ligne} et pourcentages en {ligne + 1}')
                if not double_traitement:
                    ligne_annee_precedente = ligne + 2
                    ligne += 3
                else:
                    ligne_annee_precedente = ligne + 2
                    ligne += 1
            else:
                ligne += 1
        else:
            ligne += 1

    return tableau


def calcul_pourcentages(taille_tableau, totaux, categories, map_categories):

    pourcentages = ['']
    for colonne in range(1, taille_tableau):
        if "REMISE GROSSISTE TOTALE OBTENUE" in categories[colonne]:
            if totaux[map_categories["REMISE GROSSISTE TOTALE THEORIQUE"]] != 0 and totaux[map_categories["REMISE GROSSISTE TOTALE THEORIQUE"]] != '':
                pourcentages.append(f'{round(totaux[colonne] / totaux[map_categories["REMISE GROSSISTE TOTALE THEORIQUE"]] * 100, 2)} %')
            else:
                pourcentages.append('NA')
        elif "GROSSISTE REMISE OBTENUE" in categories[colonne]:
            if totaux[map_categories["GROSSISTE REMISE THEORIQUE"]] != 0 and totaux[map_categories["GROSSISTE REMISE THEORIQUE"]] != '':
                pourcentages.append(f'{round(totaux[colonne] / totaux[map_categories["GROSSISTE REMISE THEORIQUE"]] * 100, 2)} %')
            else:
                pourcentages.append('NA')
        elif "DIRECT REMISE OBTENUE" in categories[colonne]:
            if totaux[map_categories["DIRECT REMISE THEORIQUE"]] != 0 and totaux[map_categories["DIRECT REMISE THEORIQUE"]] != '':
                pourcentages.append(f'{round(totaux[colonne] / totaux[map_categories["DIRECT REMISE THEORIQUE"]] * 100, 2)} %')
            else:
                pourcentages.append('NA')
        elif "TOTAL REMISE OBTENUE HT (HORS 0%)" in categories[colonne]:
            if totaux[map_categories["TOTAL REMISE THEORIQUE HT (HORS 0%)"]] != 0 and totaux[map_categories["TOTAL REMISE THEORIQUE HT (HORS 0%)"]] != '':
                pourcentages.append(f'{round(totaux[colonne] / totaux[map_categories["TOTAL REMISE THEORIQUE HT (HORS 0%)"]] * 100, 2)} %')
            else:
                pourcentages.append('NA')
        elif "REMISE OBTENUE HT" in categories[colonne]:
            if totaux[colonne - 1] != 0 and totaux[colonne - 1] != '':
                pourcentages.append(f'{round(totaux[colonne] / totaux[colonne - 1] * 100, 2)} %')
            else:
                pourcentages.append('NA')
        elif "Remise > 450€ 15€/bt" in categories[colonne]:
            pourcentages.append('')
        elif categories[colonne].startswith("Remise"):
            if categories[colonne] == "Remise Générique":
                i = 3
            else:
                i = 1
            if totaux[colonne - i] != 0 and totaux[colonne - i] != '':
                pourcentages.append(f'{round(totaux[colonne] / totaux[colonne - i] * 100, 2)} %')
            else:
                pourcentages.append('NA')
        else:
            pourcentages.append('')
    
    return pourcentages


def extract_nb_boites():
    data_dict_nb_boites = {}

    data_nb_boites = (
        Achat.objects
        .filter(categorie=">450€ tva 2,1%")
        .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
        .values('mois', 'annee')
        .annotate(total_boites=Sum('nb_boites'))
    )

    for entry in data_nb_boites:
        mois_annee = f"{entry['mois']}/{entry['annee']}"
        total_boites = entry['total_boites']
        #remise_theorique_totale = entry['remise_theorique_totale']

        # Si la clé mois_annee n'existe pas encore dans le dictionnaire, créez-la
        if mois_annee not in data_dict_nb_boites:
            data_dict_nb_boites[mois_annee] = {}

        # Remplissage du dictionnaire avec les valeurs
        data_dict_nb_boites[mois_annee]["Total_boites"] = total_boites
        #data_dict[mois_annee][f"{categorie} REMISE HT"] = remise_theorique_totale

    return data_dict_nb_boites


def get_data_dict_total_cerp_mois():
    data_dict_total_cerp_mois = {}

    data_cerp = (
            Achat.objects
            .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
            .filter(fournisseur__icontains='CERP')
            .values('mois', 'annee')
            .annotate(
                total_ht_hors_remise=Sum('montant_ht_hors_remise'), 
            )
        )
    
    for entry in data_cerp:
        mois_annee = f"{entry['mois']}/{entry['annee']}"
        total_cerp = entry['total_ht_hors_remise']

        if mois_annee not in data_dict_total_cerp_mois:
            data_dict_total_cerp_mois[mois_annee] = {}

        data_dict_total_cerp_mois[mois_annee]["Total_cerp"] = total_cerp

    return quicksort_dict(data_dict_total_cerp_mois)


# -----------------------------------

# -------- TABLEAU GROSSISTE -------- 

# -----------------------------------


def generer_tableau_grossiste(annee):

    colonnes = [
        "Mois/Année",
        "CA < 450€",
        "Remise < 450€",
        "CA > 450€ 15€/bt",
        "nb de boites",
        "Remise > 450€ 15€/bt",
        "CA Générique",
        "dont FDL",
        "dont Commandes Réseau",
        "Remise Générique",
        "CA Marché produits",
        "Remise Marché produits",
        "CA UPP",
        "Remise UPP",
        "CA COALIA",
        "Remise COALIA",
        "CA Total",
    ]

    map_colonnes = {colonne: i for i, colonne in enumerate(colonnes)}

    data = (
        Achat.objects
        .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
        .filter(
            annee=annee,
            fournisseur__icontains="CERP"
        )
        .values('mois', 'annee', 'fournisseur', 'categorie')
        .annotate(
            total_ht_hors_remise=Sum('montant_ht_hors_remise'), 
            remise_obtenue=Sum(ExpressionWrapper(F('remise_pourcent') * F('montant_ht_hors_remise'), output_field=fields.DecimalField()))
        )
    )
    
    tableau_grossiste = init_tableau_grossiste(map_colonnes, data)

    for entry in data:
        mois_annee = f"{entry['mois']}/{entry['annee']}"
        for ligne in tableau_grossiste:
            if ligne[0] == mois_annee:
                if '<450€ tva 2,1%' in entry['categorie']:
                    ligne[map_colonnes["CA < 450€"]] = Decimal(ligne[map_colonnes["CA < 450€"]]) + round(Decimal(entry['total_ht_hors_remise']) * Decimal(0.91), 2)
                elif 'LPP 5,5 OU 10%' in entry['categorie']:
                    ligne[map_colonnes["CA < 450€"]] = Decimal(ligne[map_colonnes["CA < 450€"]]) + round(Decimal(entry['total_ht_hors_remise']) * Decimal(0.91), 2)
                elif 'PARAPHARMACIE' in entry['categorie']:
                    ligne[map_colonnes["CA < 450€"]] = Decimal(ligne[map_colonnes["CA < 450€"]]) + round(Decimal(entry['total_ht_hors_remise']) * Decimal(0.91), 2)
                elif '>450€ tva 2,1%' in entry['categorie']:
                    ligne[map_colonnes["CA > 450€ 15€/bt"]] = Decimal(ligne[map_colonnes["CA > 450€ 15€/bt"]]) + round(entry['total_ht_hors_remise'], 2)
                elif entry['categorie'].startswith("GENERIQUE"):
                    ligne[map_colonnes["CA Générique"]] = Decimal(ligne[map_colonnes["CA Générique"]]) + round(entry['total_ht_hors_remise'], 2)
                    if "COMMANDE RESEAU" in entry['fournisseur']:
                        ligne[map_colonnes["dont Commandes Réseau"]] = Decimal(ligne[map_colonnes["dont Commandes Réseau"]]) + round(entry['total_ht_hors_remise'], 2)
                    else:
                        ligne[map_colonnes["dont FDL"]] = Decimal(ligne[map_colonnes["dont FDL"]]) + round(entry['total_ht_hors_remise'], 2)
                    ligne[map_colonnes["Remise Générique"]] = Decimal(ligne[map_colonnes["Remise Générique"]]) + round(entry['remise_obtenue'], 2)
                elif 'MARCHE PRODUITS' in entry['categorie']:
                    ligne[map_colonnes["CA Marché produits"]] = Decimal(ligne[map_colonnes["CA Marché produits"]]) + round(entry['total_ht_hors_remise'], 2)
                    ligne[map_colonnes["Remise Marché produits"]] = Decimal(ligne[map_colonnes["Remise Marché produits"]]) + round(entry['remise_obtenue'], 2)
                elif 'UPP' in entry['categorie']:
                    ligne[map_colonnes["CA UPP"]] = Decimal(ligne[map_colonnes["CA UPP"]]) + round(entry['total_ht_hors_remise'], 2)
                    ligne[map_colonnes["Remise UPP"]] = Decimal(ligne[map_colonnes["Remise UPP"]]) + round(entry['remise_obtenue'], 2)
                elif 'COALIA' in entry['categorie']:
                    ligne[map_colonnes["CA COALIA"]] = Decimal(ligne[map_colonnes["CA COALIA"]]) + round(entry['total_ht_hors_remise'], 2)
                    ligne[map_colonnes["Remise COALIA"]] = Decimal(ligne[map_colonnes["Remise COALIA"]]) + round(entry['remise_obtenue'], 2)

    tableau_grossiste = remplir_autres_colonnes_tab_grossiste(tableau_grossiste, map_colonnes)
    tableau_grossiste = quicksort_tableau(tableau_grossiste)

    tableau_grossiste = totaux_pourcentages_par_annee(tableau_grossiste, colonnes, map_colonnes)

    return tableau_grossiste, colonnes


def init_tableau_grossiste(map_colonnes, data):
    tableau=[]
    mois_annees = []

    for entry in data:
        mois_annee = f"{entry['mois']}/{entry['annee']}"
        if mois_annee not in mois_annees:
            mois_annees.append(mois_annee)

    for ma in mois_annees:
        nouvelle_ligne = [ma] + [0] * (len(map_colonnes) - 1)
        tableau.append(nouvelle_ligne)

    return tableau


def remplir_autres_colonnes_tab_grossiste(tableau, map_colonnes):

    try:
        data_dict_nb_boites = extract_nb_boites()

        for ligne in range(len(tableau)):
            if tableau[ligne][0] in data_dict_nb_boites:
                tableau[ligne][map_colonnes["nb de boites"]] = data_dict_nb_boites[tableau[ligne][0]]["Total_boites"]
            else:
                tableau[ligne][map_colonnes["nb de boites"]] = round(Decimal(0), 0)

        for ligne in range(len(tableau)):
            tableau[ligne][map_colonnes["CA Total"]] = round(
                Decimal(tableau[ligne][map_colonnes["CA < 450€"]])
                + Decimal(tableau[ligne][map_colonnes["CA > 450€ 15€/bt"]])
                + Decimal(tableau[ligne][map_colonnes["CA Générique"]])
                + Decimal(tableau[ligne][map_colonnes["CA Marché produits"]])
                + Decimal(tableau[ligne][map_colonnes["CA UPP"]])
                + Decimal(tableau[ligne][map_colonnes["CA COALIA"]]) 
            , 2)

        for ligne in range(len(tableau)):
            taux_de_base, taux_avantage, taux_lpp = get_taux_avantage_commercial(tableau[ligne][map_colonnes["Mois/Année"]], tableau[ligne][map_colonnes["CA Total"]])

            tableau[ligne][map_colonnes["Remise < 450€"]] = round(Decimal(tableau[ligne][map_colonnes["CA < 450€"]]) * (taux_de_base + taux_avantage), 2)
            tableau[ligne][map_colonnes["Remise > 450€ 15€/bt"]] = round(Decimal(tableau[ligne][map_colonnes["nb de boites"]]) * Decimal(15), 2)

    except Exception as e:
        logger.error(f'Erreur de traitement des autres colonnes du tableau grossiste : {e}. Traceback : {traceback.format_exc()}')

    return tableau


# -----------------------------------

# -------- TABLEAU SIMPLIFIE -------- 

# -----------------------------------


def data_dict_tab_simplifie():

    data_dict = {}
    annees = []

    data = (
        Achat.objects
        .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
        .filter(Q(fournisseur__icontains='CERP') | Q(fournisseur__icontains='PHARMAT'))
        .values('mois', 'annee', 'categorie')
        .annotate(
            total_ht_hors_remise=Sum('montant_ht_hors_remise'), 
            remise_obtenue=Sum(ExpressionWrapper(F('remise_pourcent') * F('montant_ht_hors_remise'), output_field=fields.DecimalField()))
        )
    )

    #On nettoie et organise le data dict
    for entry in data:
        mois_annee = f"{entry['mois']}/{entry['annee']}"
        categorie = entry['categorie']
        total_ht_hors_remise = entry['total_ht_hors_remise']
        remise_obtenue = entry['remise_obtenue']
        #remise_theorique_totale = entry['remise_theorique_totale']

        # Si la clé mois_annee n'existe pas encore dans le dictionnaire, créez-la
        if mois_annee not in data_dict:
            data_dict[mois_annee] = {}

        if str(entry['annee']) not in annees:
            annees.append(str(entry['annee']))

        # Remplissage du dictionnaire avec les valeurs
        data_dict[mois_annee][f"{categorie} TOTAL HT"] = total_ht_hors_remise
        data_dict[mois_annee][f"{categorie} REMISE HT"] = remise_obtenue

    return quicksort_dict(data_dict), quicksort_liste(annees)


def data_dict_tab_simplifie_full_year(annee):

    data_dict = {}

    data = (
        Achat.objects
        .annotate(annee=ExtractYear('date'))
        .filter(
            Q(fournisseur__icontains='CERP') | Q(fournisseur__icontains='PHARMAT'),
            annee = annee
        )
        .values('annee', 'categorie')
        .annotate(
            total_ht_hors_remise=Sum('montant_ht_hors_remise'), 
            remise_obtenue=Sum(ExpressionWrapper(F('remise_pourcent') * F('montant_ht_hors_remise'), output_field=fields.DecimalField()))
        )
    )

    for entry in data:
        mois_annee = str(entry['annee'])
        categorie = entry['categorie']
        total_ht_hors_remise = entry['total_ht_hors_remise']
        remise_obtenue = entry['remise_obtenue']

        if mois_annee not in data_dict:
            data_dict[mois_annee] = {}

        # Remplissage du dictionnaire avec les valeurs
        data_dict[mois_annee][f"{categorie} TOTAL HT"] = total_ht_hors_remise
        data_dict[mois_annee][f"{categorie} REMISE HT"] = remise_obtenue

    return data_dict


def init_tableau_simplifie(lignes, colonnes):
    tableau_simplifie = []
    i = 0

    for ligne in lignes:
        tableau_simplifie.append([ligne])
        for colonne in colonnes[1:]:
            if ligne != '' and colonne != '' and colonne != 'DIFFERENCE OBTENU - THEORIQUE' and ligne != "DIFFERENCES REMISES" and ligne != "TOTAL GENERAL TOUTES CATEGORIES":
                tableau_simplifie[i].append(0)
            else:
                tableau_simplifie[i].append('')
        
        i += 1

    return tableau_simplifie


def generer_tableau_simplifie(mois_annee, data_dict):

    lignes = [
        '<450€ tva 2,1% TOTAL HT = ASSIETTE GLOBALE - 9%',
        'LPP 5,5 OU 10% TOTAL HT',
        'LPP 20% TOTAL HT',
        'PARAPHARMACIE TOTAL HT',
        'SOUS TOTAL',
        'TOTAL',
        '',
        'AVANTAGE COMMERCIAL',
        '',
        'NB BOITES >450€',
        'AVOIRS EXCEPTIONNELS',
        '',
        'DIFFERENCES REMISES',
        '',
        'GENERIQUES TOTAL HT',
        'MARCHE PRODUITS TOTAL HT',
        'UPP TOTAL HT',
        'COALIA TOTAL HT',
        'PHARMAT TOTAL HT',
        '',
        'TOTAL GENERAL TOUTES CATEGORIES',
    ]

    colonnes = [
        '',
        'TOTAL THEORIQUE',
        'REMISE THEORIQUE',
        '',
        'TOTAL OBTENU',
        'REMISE OBTENUE',
        '',
        'DIFFERENCE OBTENU - THEORIQUE'
    ]

    map_lignes = {ligne: i for i, ligne in enumerate(lignes)}
    map_colonnes = {colonne: i for i, colonne in enumerate(colonnes)}

    data_dict_nb_boites = extract_nb_boites()
    entree_nb_boites = {}
    tableau_simplifie = init_tableau_simplifie(lignes, colonnes)

    data_dict_total_cerp_mois = get_data_dict_total_cerp_mois()
    try:
        taux_de_base, taux_avantage, taux_lpp = get_taux_avantage_commercial(mois_annee, data_dict_total_cerp_mois[mois_annee]["Total_cerp"])
    except KeyError:
        taux_de_base, taux_avantage, taux_lpp = 0, 0, 0

    if len(mois_annee) > 4:
        avoirs_remises = {Avoir_remises.objects.filter(mois_concerne=mois_annee).first()}
        entree_nb_boites = get_data_from_dict(data_dict_nb_boites, mois_annee)
    else:
        avoirs_remises = (
            Avoir_remises.objects
            .annotate(annee=ExtractYear('date'))
            .filter(
                mois_concerne__icontains = mois_annee
            )
        )
        entree_nb_boites["Total_boites"] = Decimal(0)
        for mois_annee_dict, valeurs in data_dict_nb_boites.items():
            if mois_annee in mois_annee_dict:
                entree_nb_boites["Total_boites"] += Decimal(valeurs["Total_boites"])

    tableau_simplifie[map_lignes["<450€ tva 2,1% TOTAL HT = ASSIETTE GLOBALE - 9%"]][map_colonnes["TOTAL THEORIQUE"]] = round(Decimal(get_data_from_dict(data_dict, mois_annee, "<450€ tva 2,1% TOTAL HT")) * Decimal(0.91), 2)
    tableau_simplifie[map_lignes["<450€ tva 2,1% TOTAL HT = ASSIETTE GLOBALE - 9%"]][map_colonnes["REMISE THEORIQUE"]] = round(Decimal(get_data_from_dict(data_dict, mois_annee, "<450€ tva 2,1% TOTAL HT")) * Decimal(0.91) * taux_de_base, 2)
    for avoir in avoirs_remises:
        if avoir:
            tableau_simplifie[map_lignes["<450€ tva 2,1% TOTAL HT = ASSIETTE GLOBALE - 9%"]][map_colonnes["TOTAL OBTENU"]] += round(avoir.specialites_pharmaceutiques_montant, 2)
            tableau_simplifie[map_lignes["<450€ tva 2,1% TOTAL HT = ASSIETTE GLOBALE - 9%"]][map_colonnes["REMISE OBTENUE"]] += round(avoir.specialites_pharmaceutiques_remise, 2)
    tableau_simplifie[map_lignes["<450€ tva 2,1% TOTAL HT = ASSIETTE GLOBALE - 9%"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]] = (
        Decimal(tableau_simplifie[map_lignes["<450€ tva 2,1% TOTAL HT = ASSIETTE GLOBALE - 9%"]][map_colonnes["REMISE OBTENUE"]])
        - Decimal(tableau_simplifie[map_lignes["<450€ tva 2,1% TOTAL HT = ASSIETTE GLOBALE - 9%"]][map_colonnes["REMISE THEORIQUE"]])
    )

    tableau_simplifie[map_lignes["LPP 5,5 OU 10% TOTAL HT"]][map_colonnes["TOTAL THEORIQUE"]] = round(Decimal(get_data_from_dict(data_dict, mois_annee, "LPP 5,5 OU 10% TOTAL HT")), 2)
    tableau_simplifie[map_lignes["LPP 5,5 OU 10% TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]] = round(Decimal(get_data_from_dict(data_dict, mois_annee, "LPP 5,5 OU 10% TOTAL HT")) * Decimal(0.91) * taux_lpp, 2)
    for avoir in avoirs_remises:
        if avoir:
            tableau_simplifie[map_lignes["LPP 5,5 OU 10% TOTAL HT"]][map_colonnes["TOTAL OBTENU"]] += round(avoir.lpp_cinq_ou_dix_montant, 2)
            tableau_simplifie[map_lignes["LPP 5,5 OU 10% TOTAL HT"]][map_colonnes["REMISE OBTENUE"]] += round(avoir.lpp_cinq_ou_dix_remise, 2)
    tableau_simplifie[map_lignes["LPP 5,5 OU 10% TOTAL HT"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]] = (
        Decimal(tableau_simplifie[map_lignes["LPP 5,5 OU 10% TOTAL HT"]][map_colonnes["REMISE OBTENUE"]])
        - Decimal(tableau_simplifie[map_lignes["LPP 5,5 OU 10% TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]])
    )

    tableau_simplifie[map_lignes["LPP 20% TOTAL HT"]][map_colonnes["TOTAL THEORIQUE"]] = round(Decimal(get_data_from_dict(data_dict, mois_annee, "LPP 20% TOTAL HT")), 2)
    tableau_simplifie[map_lignes["LPP 20% TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]] = round(Decimal(get_data_from_dict(data_dict, mois_annee, "LPP 20% TOTAL HT")) * Decimal(0.91) * taux_lpp, 2)
    for avoir in avoirs_remises:
        if avoir:
            tableau_simplifie[map_lignes["LPP 20% TOTAL HT"]][map_colonnes["TOTAL OBTENU"]] += round(avoir.lpp_vingt_montant, 2)
            tableau_simplifie[map_lignes["LPP 20% TOTAL HT"]][map_colonnes["REMISE OBTENUE"]] += round(avoir.lpp_vingt_remise, 2)
    tableau_simplifie[map_lignes["LPP 20% TOTAL HT"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]] = (
        Decimal(tableau_simplifie[map_lignes["LPP 20% TOTAL HT"]][map_colonnes["REMISE OBTENUE"]])
        - Decimal(tableau_simplifie[map_lignes["LPP 20% TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]])
    )

    tableau_simplifie[map_lignes["PARAPHARMACIE TOTAL HT"]][map_colonnes["TOTAL THEORIQUE"]] = round(Decimal(get_data_from_dict(data_dict, mois_annee, "PARAPHARMACIE TOTAL HT")), 2)
    tableau_simplifie[map_lignes["PARAPHARMACIE TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]] = round(Decimal(get_data_from_dict(data_dict, mois_annee, "PARAPHARMACIE TOTAL HT")) * Decimal(0.91) * (taux_de_base + taux_avantage), 2)
    for avoir in avoirs_remises:
        if avoir:
            tableau_simplifie[map_lignes["PARAPHARMACIE TOTAL HT"]][map_colonnes["TOTAL OBTENU"]] += round(avoir.parapharmacie_montant, 2)
            tableau_simplifie[map_lignes["PARAPHARMACIE TOTAL HT"]][map_colonnes["REMISE OBTENUE"]] += round(avoir.parapharmacie_remise, 2)
    tableau_simplifie[map_lignes["PARAPHARMACIE TOTAL HT"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]] = (
        Decimal(tableau_simplifie[map_lignes["PARAPHARMACIE TOTAL HT"]][map_colonnes["REMISE OBTENUE"]])
        - Decimal(tableau_simplifie[map_lignes["PARAPHARMACIE TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]])
    )

    tableau_simplifie[map_lignes["SOUS TOTAL"]][map_colonnes["REMISE THEORIQUE"]] = round(
        Decimal(tableau_simplifie[map_lignes["<450€ tva 2,1% TOTAL HT = ASSIETTE GLOBALE - 9%"]][map_colonnes["REMISE THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["LPP 5,5 OU 10% TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["LPP 20% TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["PARAPHARMACIE TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]])
    , 2)
    tableau_simplifie[map_lignes["SOUS TOTAL"]][map_colonnes["REMISE OBTENUE"]] = round(
        Decimal(tableau_simplifie[map_lignes["<450€ tva 2,1% TOTAL HT = ASSIETTE GLOBALE - 9%"]][map_colonnes["REMISE OBTENUE"]])
        + Decimal(tableau_simplifie[map_lignes["LPP 5,5 OU 10% TOTAL HT"]][map_colonnes["REMISE OBTENUE"]])
        + Decimal(tableau_simplifie[map_lignes["LPP 20% TOTAL HT"]][map_colonnes["REMISE OBTENUE"]])
        + Decimal(tableau_simplifie[map_lignes["PARAPHARMACIE TOTAL HT"]][map_colonnes["REMISE OBTENUE"]])
    , 2)

    tableau_simplifie[map_lignes["TOTAL"]][map_colonnes["TOTAL THEORIQUE"]] = round(
        Decimal(tableau_simplifie[map_lignes["<450€ tva 2,1% TOTAL HT = ASSIETTE GLOBALE - 9%"]][map_colonnes["TOTAL THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["LPP 5,5 OU 10% TOTAL HT"]][map_colonnes["TOTAL THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["LPP 20% TOTAL HT"]][map_colonnes["TOTAL THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["PARAPHARMACIE TOTAL HT"]][map_colonnes["TOTAL THEORIQUE"]])
    , 2)
    tableau_simplifie[map_lignes["TOTAL"]][map_colonnes["REMISE THEORIQUE"]] = round(Decimal(tableau_simplifie[map_lignes["TOTAL"]][map_colonnes["TOTAL THEORIQUE"]]) * Decimal(0.038), 2)
    tableau_simplifie[map_lignes["TOTAL"]][map_colonnes["TOTAL OBTENU"]] = round(
        Decimal(tableau_simplifie[map_lignes["<450€ tva 2,1% TOTAL HT = ASSIETTE GLOBALE - 9%"]][map_colonnes["TOTAL OBTENU"]])
        + Decimal(tableau_simplifie[map_lignes["LPP 5,5 OU 10% TOTAL HT"]][map_colonnes["TOTAL OBTENU"]])
        + Decimal(tableau_simplifie[map_lignes["LPP 20% TOTAL HT"]][map_colonnes["TOTAL OBTENU"]])
        + Decimal(tableau_simplifie[map_lignes["PARAPHARMACIE TOTAL HT"]][map_colonnes["TOTAL OBTENU"]])
    , 2)
    tableau_simplifie[map_lignes["TOTAL"]][map_colonnes["REMISE OBTENUE"]] = round(Decimal(tableau_simplifie[map_lignes["TOTAL"]][map_colonnes["TOTAL OBTENU"]]) * Decimal(0.038), 2)
    tableau_simplifie[map_lignes["TOTAL"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]] = (
        Decimal(tableau_simplifie[map_lignes["<450€ tva 2,1% TOTAL HT = ASSIETTE GLOBALE - 9%"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["LPP 5,5 OU 10% TOTAL HT"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["LPP 20% TOTAL HT"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["PARAPHARMACIE TOTAL HT"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]])
    )

    tableau_simplifie[map_lignes["AVANTAGE COMMERCIAL"]][map_colonnes["REMISE THEORIQUE"]] = (
        Decimal(tableau_simplifie[map_lignes["TOTAL"]][map_colonnes["REMISE THEORIQUE"]])
        - Decimal(tableau_simplifie[map_lignes["SOUS TOTAL"]][map_colonnes["REMISE THEORIQUE"]])
    )
    tableau_simplifie[map_lignes["AVANTAGE COMMERCIAL"]][map_colonnes["REMISE OBTENUE"]] = (
        Decimal(tableau_simplifie[map_lignes["TOTAL"]][map_colonnes["REMISE OBTENUE"]])
        - Decimal(tableau_simplifie[map_lignes["SOUS TOTAL"]][map_colonnes["REMISE OBTENUE"]])
    )
    tableau_simplifie[map_lignes["AVANTAGE COMMERCIAL"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]] = (
        Decimal(tableau_simplifie[map_lignes["AVANTAGE COMMERCIAL"]][map_colonnes["REMISE OBTENUE"]])
        - Decimal(tableau_simplifie[map_lignes["AVANTAGE COMMERCIAL"]][map_colonnes["REMISE THEORIQUE"]])
    )

    if entree_nb_boites:
        tableau_simplifie[map_lignes["NB BOITES >450€"]][map_colonnes["TOTAL THEORIQUE"]] = entree_nb_boites["Total_boites"]
    tableau_simplifie[map_lignes["AVOIRS EXCEPTIONNELS"]][map_colonnes["REMISE THEORIQUE"]] = Decimal(tableau_simplifie[map_lignes["NB BOITES >450€"]][map_colonnes["TOTAL THEORIQUE"]]) * Decimal(15)
    for avoir in avoirs_remises:
        if avoir:
            tableau_simplifie[map_lignes["AVOIRS EXCEPTIONNELS"]][map_colonnes["REMISE OBTENUE"]] += round(avoir.avoirs_exceptionnels, 0)
    tableau_simplifie[map_lignes["NB BOITES >450€"]][map_colonnes["TOTAL OBTENU"]] = round(Decimal(tableau_simplifie[map_lignes["AVOIRS EXCEPTIONNELS"]][map_colonnes["REMISE OBTENUE"]]) / Decimal(15), 0)
    tableau_simplifie[map_lignes["AVOIRS EXCEPTIONNELS"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]] = (
        Decimal(tableau_simplifie[map_lignes["AVOIRS EXCEPTIONNELS"]][map_colonnes["REMISE OBTENUE"]])
        - Decimal(tableau_simplifie[map_lignes["AVOIRS EXCEPTIONNELS"]][map_colonnes["REMISE THEORIQUE"]])
    )

    tableau_simplifie[map_lignes["DIFFERENCES REMISES"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]] = (
        Decimal(tableau_simplifie[map_lignes["TOTAL"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["AVANTAGE COMMERCIAL"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["AVOIRS EXCEPTIONNELS"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]])
    )

    tableau_simplifie[map_lignes["GENERIQUES TOTAL HT"]][map_colonnes["TOTAL THEORIQUE"]] = round(
        Decimal(get_data_from_dict(data_dict, mois_annee, "GENERIQUE 2,1% TOTAL HT"))
        + Decimal(get_data_from_dict(data_dict, mois_annee, "GENERIQUE 5,5% TOTAL HT"))
        + Decimal(get_data_from_dict(data_dict, mois_annee, "GENERIQUE 10% TOTAL HT"))
        + Decimal(get_data_from_dict(data_dict, mois_annee, "GENERIQUE 20% TOTAL HT"))
    , 2)
    tableau_simplifie[map_lignes["GENERIQUES TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]] = round(
        Decimal(get_data_from_dict(data_dict, mois_annee, "GENERIQUE 2,1% REMISE HT"))
        + Decimal(get_data_from_dict(data_dict, mois_annee, "GENERIQUE 5,5% REMISE HT"))
        + Decimal(get_data_from_dict(data_dict, mois_annee, "GENERIQUE 10% REMISE HT"))
        + Decimal(get_data_from_dict(data_dict, mois_annee, "GENERIQUE 20% REMISE HT"))
    , 2)
    for avoir in avoirs_remises:
        if avoir:
            tableau_simplifie[map_lignes["GENERIQUES TOTAL HT"]][map_colonnes["TOTAL OBTENU"]] += round(avoir.generiques_montant, 2)
            tableau_simplifie[map_lignes["GENERIQUES TOTAL HT"]][map_colonnes["REMISE OBTENUE"]] += round(avoir.generiques_remise, 2)
    tableau_simplifie[map_lignes["GENERIQUES TOTAL HT"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]] = (
        Decimal(tableau_simplifie[map_lignes["GENERIQUES TOTAL HT"]][map_colonnes["REMISE OBTENUE"]])
        - Decimal(tableau_simplifie[map_lignes["GENERIQUES TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]])
    )

    tableau_simplifie[map_lignes["MARCHE PRODUITS TOTAL HT"]][map_colonnes["TOTAL THEORIQUE"]] = round(Decimal(get_data_from_dict(data_dict, mois_annee, "MARCHE PRODUITS TOTAL HT")), 2)
    tableau_simplifie[map_lignes["MARCHE PRODUITS TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]] = round(Decimal(get_data_from_dict(data_dict, mois_annee, "MARCHE PRODUITS REMISE HT")), 2)
    for avoir in avoirs_remises:
        if avoir:
            tableau_simplifie[map_lignes["MARCHE PRODUITS TOTAL HT"]][map_colonnes["TOTAL OBTENU"]] += round(avoir.marche_produits_montant, 2)
            tableau_simplifie[map_lignes["MARCHE PRODUITS TOTAL HT"]][map_colonnes["REMISE OBTENUE"]] += round(avoir.marche_produits_remise, 2)
    tableau_simplifie[map_lignes["MARCHE PRODUITS TOTAL HT"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]] = (
        Decimal(tableau_simplifie[map_lignes["MARCHE PRODUITS TOTAL HT"]][map_colonnes["REMISE OBTENUE"]])
        - Decimal(tableau_simplifie[map_lignes["MARCHE PRODUITS TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]])
    )

    tableau_simplifie[map_lignes["UPP TOTAL HT"]][map_colonnes["TOTAL THEORIQUE"]] = round(Decimal(get_data_from_dict(data_dict, mois_annee, "UPP TOTAL HT")), 2)
    tableau_simplifie[map_lignes["UPP TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]] = round(Decimal(get_data_from_dict(data_dict, mois_annee, "UPP REMISE HT")), 2)
    for avoir in avoirs_remises:
        if avoir:
            tableau_simplifie[map_lignes["UPP TOTAL HT"]][map_colonnes["TOTAL OBTENU"]] += round(avoir.upp_montant, 2)
            tableau_simplifie[map_lignes["UPP TOTAL HT"]][map_colonnes["REMISE OBTENUE"]] += round(avoir.upp_remise, 2)
    tableau_simplifie[map_lignes["UPP TOTAL HT"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]] = (
        Decimal(tableau_simplifie[map_lignes["UPP TOTAL HT"]][map_colonnes["REMISE OBTENUE"]])
        - Decimal(tableau_simplifie[map_lignes["UPP TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]])
    )

    tableau_simplifie[map_lignes["COALIA TOTAL HT"]][map_colonnes["TOTAL THEORIQUE"]] = round(Decimal(get_data_from_dict(data_dict, mois_annee, "COALIA TOTAL HT")), 2)
    tableau_simplifie[map_lignes["COALIA TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]] = round(Decimal(get_data_from_dict(data_dict, mois_annee, "COALIA REMISE HT")), 2)
    for avoir in avoirs_remises:
        if avoir:
            tableau_simplifie[map_lignes["COALIA TOTAL HT"]][map_colonnes["TOTAL OBTENU"]] += round(avoir.coalia_montant, 2)
            tableau_simplifie[map_lignes["COALIA TOTAL HT"]][map_colonnes["REMISE OBTENUE"]] += round(avoir.coalia_remise, 2)
    tableau_simplifie[map_lignes["COALIA TOTAL HT"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]] = (
        Decimal(tableau_simplifie[map_lignes["COALIA TOTAL HT"]][map_colonnes["REMISE OBTENUE"]])
        - Decimal(tableau_simplifie[map_lignes["COALIA TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]])
    )

    tableau_simplifie[map_lignes["PHARMAT TOTAL HT"]][map_colonnes["TOTAL THEORIQUE"]] = round(Decimal(get_data_from_dict(data_dict, mois_annee, "PHARMAT TOTAL HT")), 2)
    tableau_simplifie[map_lignes["PHARMAT TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]] = round(Decimal(get_data_from_dict(data_dict, mois_annee, "PHARMAT REMISE HT")), 2)
    for avoir in avoirs_remises:
        if avoir:
            tableau_simplifie[map_lignes["PHARMAT TOTAL HT"]][map_colonnes["TOTAL OBTENU"]] += round(avoir.pharmat_montant, 2)
            tableau_simplifie[map_lignes["PHARMAT TOTAL HT"]][map_colonnes["REMISE OBTENUE"]] += round(avoir.pharmat_remise, 2)
    tableau_simplifie[map_lignes["PHARMAT TOTAL HT"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]] = (
        Decimal(tableau_simplifie[map_lignes["PHARMAT TOTAL HT"]][map_colonnes["REMISE OBTENUE"]])
        - Decimal(tableau_simplifie[map_lignes["PHARMAT TOTAL HT"]][map_colonnes["REMISE THEORIQUE"]])
    )

    tableau_simplifie[map_lignes["TOTAL GENERAL TOUTES CATEGORIES"]][map_colonnes["TOTAL THEORIQUE"]] = round(
        Decimal(tableau_simplifie[map_lignes["TOTAL"]][map_colonnes["TOTAL THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["GENERIQUES TOTAL HT"]][map_colonnes["TOTAL THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["MARCHE PRODUITS TOTAL HT"]][map_colonnes["TOTAL THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["UPP TOTAL HT"]][map_colonnes["TOTAL THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["COALIA TOTAL HT"]][map_colonnes["TOTAL THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["PHARMAT TOTAL HT"]][map_colonnes["TOTAL THEORIQUE"]])
    , 2)

    tableau_simplifie[map_lignes["TOTAL GENERAL TOUTES CATEGORIES"]][map_colonnes["TOTAL OBTENU"]] = round(
        Decimal(tableau_simplifie[map_lignes["TOTAL"]][map_colonnes["TOTAL OBTENU"]])
        + Decimal(tableau_simplifie[map_lignes["GENERIQUES TOTAL HT"]][map_colonnes["TOTAL OBTENU"]])
        + Decimal(tableau_simplifie[map_lignes["MARCHE PRODUITS TOTAL HT"]][map_colonnes["TOTAL OBTENU"]])
        + Decimal(tableau_simplifie[map_lignes["UPP TOTAL HT"]][map_colonnes["TOTAL OBTENU"]])
        + Decimal(tableau_simplifie[map_lignes["COALIA TOTAL HT"]][map_colonnes["TOTAL OBTENU"]])
        + Decimal(tableau_simplifie[map_lignes["PHARMAT TOTAL HT"]][map_colonnes["TOTAL OBTENU"]])
    , 2)

    tableau_simplifie[map_lignes["TOTAL GENERAL TOUTES CATEGORIES"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]] = (
        Decimal(tableau_simplifie[map_lignes["DIFFERENCES REMISES"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["GENERIQUES TOTAL HT"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["MARCHE PRODUITS TOTAL HT"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["UPP TOTAL HT"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["COALIA TOTAL HT"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]])
        + Decimal(tableau_simplifie[map_lignes["PHARMAT TOTAL HT"]][map_colonnes["DIFFERENCE OBTENU - THEORIQUE"]])
    )

    return tableau_simplifie, colonnes


# -----------------------------------

# -------- TABLEAU HUITAINE CERP ----

# -----------------------------------


def base_tableau_huitaine_cerp(map_colonnes, filtre_annee, filtre_mois):
    tableau = []
    mois_annees = []

    data_mois_annees = (
        Releve_CERP.objects
        .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
        .filter(
            filtre_annee,
            filtre_mois,
            annee__gte = 2022,
        )
        .values('mois', 'annee')
    )

    for entry in data_mois_annees:
        mois_annee = f"{entry['mois']}/{entry['annee']}"
        if mois_annee not in mois_annees:
            mois_annees.append(mois_annee)

    for ma in mois_annees:
        nouvelle_ligne = [ma] + [0] * (len(map_colonnes) - 1)
        tableau.append(nouvelle_ligne)

    return tableau


def generer_tableau_huitaine_cerp(show_decades, filtre_annee, filtre_mois):
    tableau_huitaine_cerp = []

    colonnes = [
        "Huitaine",
        "Total TTC",
        "Cumul mois",
    ]

    map_colonnes = {colonne: i for i, colonne in enumerate(colonnes)}

    releves = (
        Releve_CERP.objects
        .annotate(mois=ExtractMonth('huitaine'), annee=ExtractYear('huitaine'))
        .filter(
            filtre_annee,
            filtre_mois,
            annee__gte = 2022,
        )
    )

    for releve in releves:
        tableau_huitaine_cerp.append([releve.huitaine, round(releve.total_ttc, 2), 0])

    tableau_huitaine_cerp = quicksort_liste(tableau_huitaine_cerp)

    cumulative_sums = defaultdict(int)

    for index, huitaine in enumerate(tableau_huitaine_cerp):
        if isinstance(huitaine[map_colonnes["Huitaine"]], date):
            month = huitaine[map_colonnes["Huitaine"]].strftime("%m/%Y")
            cumulative_sums[month] += huitaine[map_colonnes["Total TTC"]]
            huitaine[map_colonnes["Cumul mois"]] = cumulative_sums[month]

    if filtre_mois.children == []:
        tableau_huitaine_cerp = totaux_pourcentages_par_annee(tableau_huitaine_cerp, colonnes, map_colonnes)

    for index, huitaine in enumerate(tableau_huitaine_cerp):
        if isinstance(huitaine[map_colonnes["Huitaine"]], date):
            month = huitaine[map_colonnes["Huitaine"]].strftime("%m/%Y")
            if index < len(tableau_huitaine_cerp) - 1:
                if isinstance(tableau_huitaine_cerp[index + 1][map_colonnes["Huitaine"]], date):
                    if tableau_huitaine_cerp[index + 1][map_colonnes["Huitaine"]].month != huitaine[map_colonnes["Huitaine"]].month:
                            tableau_huitaine_cerp.insert(index + 1, [f'=> {month}', cumulative_sums[month], ""])
                else:
                    tableau_huitaine_cerp.insert(index + 1, [f'=> {month}', cumulative_sums[month], ""])

    if not show_decades:
        decadeless_huitaine_cerp = []
        for ligne in tableau_huitaine_cerp:
            if not isinstance(ligne[map_colonnes["Huitaine"]], date):
                decadeless_huitaine_cerp.append(ligne)

    for huitaine in tableau_huitaine_cerp:
        if isinstance(huitaine[map_colonnes["Huitaine"]], date):
            huitaine[map_colonnes["Huitaine"]] = huitaine[map_colonnes["Huitaine"]].strftime("%d/%m/%Y")

    return (tableau_huitaine_cerp if show_decades else decadeless_huitaine_cerp), colonnes


# -----------------------------------

# -------- TABLEAU GENERIQUES ------- 

# -----------------------------------


def generer_tableau_generiques(fournisseur_generique):
    
    colonnes = [
        "Mois/Année",
        "GROSSISTE 2,1% MONTANT HT",
        "GROSSISTE 5,5% MONTANT HT",
        "GROSSISTE 10% MONTANT HT",
        "GROSSISTE 20% MONTANT HT",
        "GROSSISTE TOTAL HT",
        "GROSSISTE REMISE THEORIQUE",
        "GROSSISTE REMISE OBTENUE",
        "DIFFERENCE REMISE GROSSISTE",
        "DIRECT 2,1% MONTANT HT",
        "DIRECT 5,5% MONTANT HT",
        "DIRECT 10% MONTANT HT",
        "DIRECT 20% MONTANT HT",
        "DIRECT TOTAL HT",
        "DIRECT REMISE THEORIQUE",
        "DIRECT REMISE OBTENUE",
        "DIFFERENCE REMISE DIRECT",
        "TOTAL GENERAL HT (GENERIQUES REMBOURSES)",
        "DIRECT NON GENERIQUES",
        "DIRECT NON REMBOURSABLES",
        "DIRECT OTC",
        "DIRECT NON GENERIQUES + OTC + NON RBS",
    ]

    map_colonnes = {colonne: i for i, colonne in enumerate(colonnes)}
    tableau_generiques = mois_annees_tab_generiques(map_colonnes, fournisseur_generique)

    # Récupérer les achats qui correspondent aux critères spécifiés
    achats_labo = (
        Achat.objects
        .filter(
            Q(produit__fournisseur_generique=fournisseur_generique) | Q(fournisseur=fournisseur_generique),
            Q(categorie__icontains="GENERIQUE") | Q(categorie__icontains="DIRECT LABO"),
        )
        .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
        .values('mois', 'annee', 'categorie', 'fournisseur')
        .annotate(
            total_ht_hors_remise=Sum('montant_ht_hors_remise'),
            remise_theorique_totale=Sum('remise_theorique_totale'),
            remise_obtenue=Sum(ExpressionWrapper(F('remise_pourcent') * F('montant_ht_hors_remise'), output_field=fields.DecimalField()))
        )
    )

    for entry in achats_labo:
        mois_annee = f"{entry['mois']}/{entry['annee']}"
        for ligne in tableau_generiques:
            if ligne[0] == mois_annee:
                if 'CERP' in entry['fournisseur']:
                    if '2,1%' in entry['categorie']:
                        ligne[map_colonnes["GROSSISTE 2,1% MONTANT HT"]] = Decimal(ligne[map_colonnes["GROSSISTE 2,1% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '5,5%' in entry['categorie']:
                        ligne[map_colonnes["GROSSISTE 5,5% MONTANT HT"]] = Decimal(ligne[map_colonnes["GROSSISTE 5,5% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '10%' in entry['categorie']:
                        ligne[map_colonnes["GROSSISTE 10% MONTANT HT"]] = Decimal(ligne[map_colonnes["GROSSISTE 10% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '20%' in entry['categorie']:
                        ligne[map_colonnes["GROSSISTE 20% MONTANT HT"]] = Decimal(ligne[map_colonnes["GROSSISTE 20% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    
                    ligne[map_colonnes["GROSSISTE REMISE THEORIQUE"]] = Decimal(ligne[map_colonnes["GROSSISTE REMISE THEORIQUE"]]) + round(entry['remise_theorique_totale'], 2)
                    ligne[map_colonnes["GROSSISTE REMISE OBTENUE"]] = Decimal(ligne[map_colonnes["GROSSISTE REMISE OBTENUE"]]) + round(entry['remise_obtenue'], 2)

                elif entry['fournisseur'] != "":
                    if '2,1%' in entry['categorie']:
                        ligne[map_colonnes["DIRECT 2,1% MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT 2,1% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '5,5%' in entry['categorie']:
                        ligne[map_colonnes["DIRECT 5,5% MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT 5,5% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '10%' in entry['categorie']:
                        ligne[map_colonnes["DIRECT 10% MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT 10% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '20%' in entry['categorie']:
                        ligne[map_colonnes["DIRECT 20% MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT 20% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif 'NON GENERIQUE' in entry['categorie']:
                        ligne[map_colonnes["DIRECT NON GENERIQUES"]] = Decimal(ligne[map_colonnes["DIRECT NON GENERIQUES"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif 'NON REMBOURSABLE' in entry['categorie']:
                        ligne[map_colonnes["DIRECT NON REMBOURSABLES"]] = Decimal(ligne[map_colonnes["DIRECT NON REMBOURSABLES"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif 'OTC' in entry['categorie']:
                        ligne[map_colonnes["DIRECT OTC"]] = Decimal(ligne[map_colonnes["DIRECT OTC"]]) + round(entry['total_ht_hors_remise'], 2)
                    
                    ligne[map_colonnes["DIRECT REMISE THEORIQUE"]] = Decimal(ligne[map_colonnes["DIRECT REMISE THEORIQUE"]]) + round(entry['remise_theorique_totale'], 2)
                    ligne[map_colonnes["DIRECT REMISE OBTENUE"]] = Decimal(ligne[map_colonnes["DIRECT REMISE OBTENUE"]]) + round(entry['remise_obtenue'], 2)

    #print(tableau_generiques)

    tableau_generiques = quicksort_tableau(tableau_generiques)

    tableau_generiques = colonnes_totaux_generiques(tableau_generiques, map_colonnes)
    tableau_generiques = totaux_pourcentages_par_annee(tableau_generiques, colonnes, map_colonnes)

    return tableau_generiques, colonnes, achats_labo


def mois_annees_tab_generiques(map_colonnes, fournisseur_generique):
    tableau=[]
    mois_annees = []

    data_mois_annees = (
        Achat.objects
        .filter(categorie__startswith='GENERIQUE')
        .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
        .values('mois', 'annee')
    )

    for entry in data_mois_annees:
        mois_annee = f"{entry['mois']}/{entry['annee']}"
        if mois_annee not in mois_annees:
            mois_annees.append(mois_annee)

    for ma in mois_annees:
        nouvelle_ligne = [ma] + [0] * (len(map_colonnes) - 1)
        tableau.append(nouvelle_ligne)

    return tableau


def colonnes_totaux_generiques(tableau, map_colonnes):

    for ligne in range(len(tableau)):
        tableau[ligne][map_colonnes["GROSSISTE TOTAL HT"]] = (
            tableau[ligne][map_colonnes["GROSSISTE 2,1% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 5,5% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 10% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 20% MONTANT HT"]]
        )
        
        tableau[ligne][map_colonnes["DIFFERENCE REMISE GROSSISTE"]] = (
            tableau[ligne][map_colonnes["GROSSISTE REMISE OBTENUE"]] 
            - tableau[ligne][map_colonnes["GROSSISTE REMISE THEORIQUE"]]
        )
        tableau[ligne][map_colonnes["DIFFERENCE REMISE DIRECT"]] = (
            tableau[ligne][map_colonnes["DIRECT REMISE OBTENUE"]]
            - tableau[ligne][map_colonnes["DIRECT REMISE THEORIQUE"]]
        )

        tableau[ligne][map_colonnes["DIRECT TOTAL HT"]] = (
            tableau[ligne][map_colonnes["DIRECT 2,1% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 5,5% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 10% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 20% MONTANT HT"]]
        )

        tableau[ligne][map_colonnes["TOTAL GENERAL HT (GENERIQUES REMBOURSES)"]] = (
            tableau[ligne][map_colonnes["GROSSISTE TOTAL HT"]]
            + tableau[ligne][map_colonnes["DIRECT TOTAL HT"]]
        )
                
        tableau[ligne][map_colonnes["DIRECT NON GENERIQUES + OTC + NON RBS"]] = (
            tableau[ligne][map_colonnes["DIRECT NON GENERIQUES"]]
            + tableau[ligne][map_colonnes["DIRECT NON REMBOURSABLES"]]
            + tableau[ligne][map_colonnes["DIRECT OTC"]]
        )

    return tableau


# -----------------------------------

# -------- TABLEAU TEVA -------- 

# -----------------------------------


def mois_annees_tab_teva(map_colonnes):
    tableau=[]
    mois_annees = []

    data_mois_annees = (
        Achat.objects
        .filter(
            categorie__startswith='GENERIQUE',
            produit__fournisseur_generique='TEVA',
        )
        .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
        .values('mois', 'annee')
    )

    for entry in data_mois_annees:
        mois_annee = f"{entry['mois']}/{entry['annee']}"
        if mois_annee not in mois_annees:
            mois_annees.append(mois_annee)

    for ma in mois_annees:
        nouvelle_ligne = [ma] + [0] * (len(map_colonnes) - 1)
        tableau.append(nouvelle_ligne)

    return tableau


def totaux_tableau_teva(tableau, map_colonnes):

    for ligne in range(len(tableau)):
        tableau[ligne][map_colonnes["GROSSISTE TOTAL HT"]] = (
            tableau[ligne][map_colonnes["GROSSISTE 0% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 2,5% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 10% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 20% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 30% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 40% MONTANT HT"]]
        )
        tableau[ligne][map_colonnes["DIFFERENCE REMISE GROSSISTE"]] = (
            tableau[ligne][map_colonnes["GROSSISTE REMISE OBTENUE"]] 
            - tableau[ligne][map_colonnes["GROSSISTE REMISE THEORIQUE"]]
        )

        tableau[ligne][map_colonnes["DIRECT TOTAL HT"]] = (
            tableau[ligne][map_colonnes["DIRECT 0% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 2,5% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 10% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 20% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 30% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 40% MONTANT HT"]]
        )
        tableau[ligne][map_colonnes["DIFFERENCE REMISE DIRECT"]] = (
            tableau[ligne][map_colonnes["DIRECT REMISE OBTENUE"]]
            - tableau[ligne][map_colonnes["DIRECT REMISE THEORIQUE"]]
        )

        tableau[ligne][map_colonnes["TOTAL GENERAL HT"]] = (
            tableau[ligne][map_colonnes["GROSSISTE TOTAL HT"]]
            + tableau[ligne][map_colonnes["DIRECT TOTAL HT"]]
        )

        tableau[ligne][map_colonnes["TOTAL GENERAL HT (HORS 0%)"]] = (
            tableau[ligne][map_colonnes["GROSSISTE 2,5% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 10% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 20% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 30% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 40% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 2,5% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 10% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 20% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 30% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 40% MONTANT HT"]]
        )

        if tableau[ligne][map_colonnes["TOTAL GENERAL HT (HORS 0%)"]] > Decimal(0):
            tableau[ligne][map_colonnes["% REMISE THEORIQUE"]] = round(
                Decimal(tableau[ligne][map_colonnes["TOTAL REMISE THEORIQUE HT (HORS 0%)"]])
                / Decimal(tableau[ligne][map_colonnes["TOTAL GENERAL HT (HORS 0%)"]])
                * 100
            , 2)
            tableau[ligne][map_colonnes["% REMISE OBTENUE"]] = round(
                Decimal(tableau[ligne][map_colonnes["TOTAL REMISE OBTENUE HT (HORS 0%)"]])
                / Decimal(tableau[ligne][map_colonnes["TOTAL GENERAL HT (HORS 0%)"]])
                * 100
            , 2)
        else:
            tableau[ligne][map_colonnes["% REMISE THEORIQUE"]] = "NA"
            tableau[ligne][map_colonnes["% REMISE OBTENUE"]] = "NA"

    return tableau


def traitement_ratrappage_remises_teva(tableau, map_colonnes):

    for ligne in range(len(tableau)):
        if int(tableau[ligne][map_colonnes["Mois/Année"]][-4:]) == 2023:
            tableau[ligne][map_colonnes["REMISE MENSUELLE FIXE"]] = Decimal(1522.00)
        
        if int(tableau[ligne][map_colonnes["Mois/Année"]][-4:]) <= 2023:
            if tableau[ligne][map_colonnes["% REMISE THEORIQUE"]] > Decimal(0):
                tableau[ligne][map_colonnes["RATTRAPAGE THEORIQUE"]] = round(
                    (Decimal(37) - tableau[ligne][map_colonnes["% REMISE THEORIQUE"]]) / 100
                    * tableau[ligne][map_colonnes["TOTAL GENERAL HT (HORS 0%)"]]
                , 2)
            if tableau[ligne][map_colonnes["% REMISE OBTENUE"]] > Decimal(0):
                tableau[ligne][map_colonnes["RATTRAPAGE OBTENU"]] = round(
                    (Decimal(37) - tableau[ligne][map_colonnes["% REMISE OBTENUE"]]) / 100
                    * tableau[ligne][map_colonnes["TOTAL GENERAL HT (HORS 0%)"]]
                , 2)
            tableau[ligne][map_colonnes["REMISE TOTALE"]] = round(
                tableau[ligne][map_colonnes["TOTAL REMISE OBTENUE HT (HORS 0%)"]]
                + tableau[ligne][map_colonnes["RATTRAPAGE OBTENU"]]
                + tableau[ligne][map_colonnes["REMISE MENSUELLE FIXE"]]
            , 2)
            if tableau[ligne][map_colonnes["TOTAL GENERAL HT (HORS 0%)"]] > Decimal(0):
                tableau[ligne][map_colonnes["% DE REMISE TOTALE"]] = round(
                    tableau[ligne][map_colonnes["REMISE TOTALE"]]
                    / tableau[ligne][map_colonnes["TOTAL GENERAL HT (HORS 0%)"]]
                    * 100
                , 2)
            else:
                tableau[ligne][map_colonnes["% DE REMISE TOTALE"]] = "NA"
        elif int(tableau[ligne][map_colonnes["Mois/Année"]][-4:]) >= 2024:
            tableau[ligne][map_colonnes["TOTAL GENERAL HT (HORS 0%)"]] = ""
            tableau[ligne][map_colonnes["TOTAL REMISE THEORIQUE HT (HORS 0%)"]] = ""
            tableau[ligne][map_colonnes["TOTAL REMISE OBTENUE HT (HORS 0%)"]] = ""
            tableau[ligne][map_colonnes["% REMISE THEORIQUE"]] = ""
            tableau[ligne][map_colonnes["% REMISE OBTENUE"]] = ""
            if int(tableau[ligne][map_colonnes["Mois/Année"]][:-5]) % 3 == 0:
                # tableau[ligne][map_colonnes["RATTRAPAGE THEORIQUE"]] = round(
                #     Decimal(0.17) * (tableau[ligne][map_colonnes["GROSSISTE 0% MONTANT HT"]] + tableau[ligne][map_colonnes["DIRECT 0% MONTANT HT"]])
                #     + (Decimal(0.17) - Decimal(0.025)) * (tableau[ligne][map_colonnes["GROSSISTE 2,5% MONTANT HT"]] + tableau[ligne][map_colonnes["DIRECT 2,5% MONTANT HT"]])
                #     + (Decimal(0.4) - Decimal(0.1)) * (tableau[ligne][map_colonnes["GROSSISTE 10% MONTANT HT"]] + tableau[ligne][map_colonnes["DIRECT 10% MONTANT HT"]])
                #     + (Decimal(0.4) - Decimal(0.2)) * (tableau[ligne][map_colonnes["GROSSISTE 20% MONTANT HT"]] + tableau[ligne][map_colonnes["DIRECT 20% MONTANT HT"]])
                #     + (Decimal(0.4) - Decimal(0.3)) * (tableau[ligne][map_colonnes["GROSSISTE 30% MONTANT HT"]] + tableau[ligne][map_colonnes["DIRECT 30% MONTANT HT"]])
                # , 2)
                tableau[ligne][map_colonnes["RATTRAPAGE THEORIQUE"]] = round(
                    (Decimal(0.195) - Decimal(0.025)) * (tableau[ligne][map_colonnes["GROSSISTE 2,5% MONTANT HT"]] + tableau[ligne][map_colonnes["DIRECT 2,5% MONTANT HT"]])
                    + (Decimal(0.3) - Decimal(0.1)) * (tableau[ligne][map_colonnes["GROSSISTE 10% MONTANT HT"]] + tableau[ligne][map_colonnes["DIRECT 10% MONTANT HT"]])
                    + (Decimal(0.3) - Decimal(0.2)) * (tableau[ligne][map_colonnes["GROSSISTE 20% MONTANT HT"]] + tableau[ligne][map_colonnes["DIRECT 20% MONTANT HT"]])
                    + (Decimal(0.195) - Decimal(0.025)) * (tableau[ligne - 1][map_colonnes["GROSSISTE 2,5% MONTANT HT"]] + tableau[ligne - 1][map_colonnes["DIRECT 2,5% MONTANT HT"]])
                    + (Decimal(0.3) - Decimal(0.1)) * (tableau[ligne - 1][map_colonnes["GROSSISTE 10% MONTANT HT"]] + tableau[ligne - 1][map_colonnes["DIRECT 10% MONTANT HT"]])
                    + (Decimal(0.3) - Decimal(0.2)) * (tableau[ligne - 1][map_colonnes["GROSSISTE 20% MONTANT HT"]] + tableau[ligne - 1][map_colonnes["DIRECT 20% MONTANT HT"]])
                    + (Decimal(0.195) - Decimal(0.025)) * (tableau[ligne - 2][map_colonnes["GROSSISTE 2,5% MONTANT HT"]] + tableau[ligne - 2][map_colonnes["DIRECT 2,5% MONTANT HT"]])
                    + (Decimal(0.3) - Decimal(0.1)) * (tableau[ligne - 2][map_colonnes["GROSSISTE 10% MONTANT HT"]] + tableau[ligne - 2][map_colonnes["DIRECT 10% MONTANT HT"]])
                    + (Decimal(0.3) - Decimal(0.2)) * (tableau[ligne - 2][map_colonnes["GROSSISTE 20% MONTANT HT"]] + tableau[ligne - 2][map_colonnes["DIRECT 20% MONTANT HT"]])
                , 2)
            else:
                tableau[ligne][map_colonnes["RATTRAPAGE THEORIQUE"]] = 0

            tableau[ligne][map_colonnes["RATTRAPAGE OBTENU"]] = "NA"

    return tableau


def rattrappage_declare(tableau, map_colonnes):

    avoirs = Avoir_ratrappage_teva.objects.all()

    for ligne in range(len(tableau)):
        for avoir in avoirs:
            if tableau[ligne][map_colonnes["Mois/Année"]] == avoir.mois_concerne:
                tableau[ligne][map_colonnes["RATTRAPPAGE DECLARÉ PAR TEVA"]] = round(avoir.montant_ratrappage, 2)

    return tableau


def generer_tableau_teva():
    colonnes = [
        "Mois/Année",
        "GROSSISTE 0% MONTANT HT",
        "GROSSISTE 2,5% MONTANT HT",
        "GROSSISTE 10% MONTANT HT",
        "GROSSISTE 20% MONTANT HT",
        "GROSSISTE 30% MONTANT HT",
        "GROSSISTE 40% MONTANT HT",
        "GROSSISTE TOTAL HT",
        "GROSSISTE REMISE THEORIQUE",
        "GROSSISTE REMISE OBTENUE",
        "DIFFERENCE REMISE GROSSISTE",
        "DIRECT 0% MONTANT HT",
        "DIRECT 2,5% MONTANT HT",
        "DIRECT 10% MONTANT HT",
        "DIRECT 20% MONTANT HT",
        "DIRECT 30% MONTANT HT",
        "DIRECT 40% MONTANT HT",
        "DIRECT TOTAL HT",
        "DIRECT REMISE THEORIQUE",
        "DIRECT REMISE OBTENUE",
        "DIFFERENCE REMISE DIRECT",
        "TOTAL GENERAL HT",
        "TOTAL GENERAL HT (HORS 0%)",
        "TOTAL REMISE THEORIQUE HT (HORS 0%)",
        "% REMISE THEORIQUE",
        "TOTAL REMISE OBTENUE HT (HORS 0%)",
        "% REMISE OBTENUE",
        "RATTRAPAGE THEORIQUE",
        "RATTRAPAGE OBTENU",
        "REMISE MENSUELLE FIXE",
        "RATTRAPPAGE DECLARÉ PAR TEVA",
        "REMISE TOTALE",
        "% DE REMISE TOTALE"
    ]

    map_colonnes = {colonne: i for i, colonne in enumerate(colonnes)}
    tableau_teva = mois_annees_tab_teva(map_colonnes)

    # Récupérer les achats qui correspondent aux critères spécifiés
    achats_labo = (
        Achat.objects
        .filter(
            produit__fournisseur_generique='TEVA',
            categorie__startswith='GENERIQUE',
            categorie_remise__startswith='TEVA'
        )
        .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
        .values('mois', 'annee', 'categorie_remise', 'fournisseur')
        .annotate(
            total_ht_hors_remise=Sum('montant_ht_hors_remise'),
            remise_theorique_totale=Sum('remise_theorique_totale'),
            remise_obtenue=Sum(ExpressionWrapper(F('remise_pourcent') * F('montant_ht_hors_remise'), output_field=fields.DecimalField()))
        )
    )

    for entry in achats_labo:
        mois_annee = f"{entry['mois']}/{entry['annee']}"
        for ligne in tableau_teva:
            if ligne[0] == mois_annee:
                if 'CERP' in entry['fournisseur']:
                    if ' 0%' in entry['categorie_remise']:
                        ligne[map_colonnes["GROSSISTE 0% MONTANT HT"]] = Decimal(ligne[map_colonnes["GROSSISTE 0% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '2,5%' in entry['categorie_remise']:
                        ligne[map_colonnes["GROSSISTE 2,5% MONTANT HT"]] = Decimal(ligne[map_colonnes["GROSSISTE 2,5% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '10%' in entry['categorie_remise']:
                        ligne[map_colonnes["GROSSISTE 10% MONTANT HT"]] = Decimal(ligne[map_colonnes["GROSSISTE 10% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '20%' in entry['categorie_remise']:
                        ligne[map_colonnes["GROSSISTE 20% MONTANT HT"]] = Decimal(ligne[map_colonnes["GROSSISTE 20% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '30%' in entry['categorie_remise']:
                        ligne[map_colonnes["GROSSISTE 30% MONTANT HT"]] = Decimal(ligne[map_colonnes["GROSSISTE 30% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '40%' in entry['categorie_remise']:
                        ligne[map_colonnes["GROSSISTE 40% MONTANT HT"]] = Decimal(ligne[map_colonnes["GROSSISTE 40% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    
                    ligne[map_colonnes["GROSSISTE REMISE THEORIQUE"]] = Decimal(ligne[map_colonnes["GROSSISTE REMISE THEORIQUE"]]) + round(entry['remise_theorique_totale'], 2)
                    ligne[map_colonnes["GROSSISTE REMISE OBTENUE"]] = Decimal(ligne[map_colonnes["GROSSISTE REMISE OBTENUE"]]) + round(entry['remise_obtenue'], 2)

                elif entry['fournisseur'] == "TEVA":
                    if ' 0%' in entry['categorie_remise']:
                        ligne[map_colonnes["DIRECT 0% MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT 0% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '2,5%' in entry['categorie_remise']:
                        ligne[map_colonnes["DIRECT 2,5% MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT 2,5% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '10%' in entry['categorie_remise']:
                        ligne[map_colonnes["DIRECT 10% MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT 10% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '20%' in entry['categorie_remise']:
                        ligne[map_colonnes["DIRECT 20% MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT 20% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '30%' in entry['categorie_remise']:
                        ligne[map_colonnes["DIRECT 30% MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT 30% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '40%' in entry['categorie_remise']:
                        ligne[map_colonnes["DIRECT 40% MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT 40% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    
                    ligne[map_colonnes["DIRECT REMISE THEORIQUE"]] = Decimal(ligne[map_colonnes["DIRECT REMISE THEORIQUE"]]) + round(entry['remise_theorique_totale'], 2)
                    ligne[map_colonnes["DIRECT REMISE OBTENUE"]] = Decimal(ligne[map_colonnes["DIRECT REMISE OBTENUE"]]) + round(entry['remise_obtenue'], 2)

                if any(element in entry['categorie_remise'] for element in ['2,5%', '10%', '20%', '30%', '40%']):
                    ligne[map_colonnes["TOTAL REMISE THEORIQUE HT (HORS 0%)"]] = Decimal(ligne[map_colonnes["TOTAL REMISE THEORIQUE HT (HORS 0%)"]]) + round(entry['remise_theorique_totale'], 2)
                    ligne[map_colonnes["TOTAL REMISE OBTENUE HT (HORS 0%)"]] = Decimal(ligne[map_colonnes["TOTAL REMISE OBTENUE HT (HORS 0%)"]]) + round(entry['remise_obtenue'], 2)

    tableau_teva = quicksort_tableau(tableau_teva)
    tableau_teva = totaux_tableau_teva(tableau_teva, map_colonnes)
    tableau_teva = traitement_ratrappage_remises_teva(tableau_teva, map_colonnes)
    tableau_teva = rattrappage_declare(tableau_teva, map_colonnes)

    #tableau_teva = colonnes_totaux_generiques(tableau_teva, map_colonnes)
    tableau_teva = totaux_pourcentages_par_annee(tableau_teva, colonnes, map_colonnes)

    return tableau_teva, colonnes


# -----------------------------------

# -------- TABLEAU EG -------- 

# -----------------------------------


def mois_annees_tab_eg(map_colonnes):
    tableau=[]
    mois_annees = []

    data_mois_annees = (
        Achat.objects
        .filter(
            categorie__startswith='GENERIQUE',
            produit__fournisseur_generique='EG',
        )
        .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
        .values('mois', 'annee')
    )

    for entry in data_mois_annees:
        mois_annee = f"{entry['mois']}/{entry['annee']}"
        if mois_annee not in mois_annees:
            mois_annees.append(mois_annee)

    for ma in mois_annees:
        nouvelle_ligne = [ma] + [0] * (len(map_colonnes) - 1)
        tableau.append(nouvelle_ligne)

    return tableau


def totaux_tableau_eg(tableau, map_colonnes):

    for ligne in range(len(tableau)):
        tableau[ligne][map_colonnes["GROSSISTE TOTAL HT"]] = (
            tableau[ligne][map_colonnes["GROSSISTE 0% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 2,5% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 5% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 10% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 15% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 20% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 30% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 40% MONTANT HT"]]
        )
        tableau[ligne][map_colonnes["DIFFERENCE REMISE GROSSISTE"]] = (
            tableau[ligne][map_colonnes["GROSSISTE REMISE OBTENUE"]] 
            - tableau[ligne][map_colonnes["GROSSISTE REMISE THEORIQUE"]]
        )

        tableau[ligne][map_colonnes["DIRECT TOTAL HT"]] = (
            tableau[ligne][map_colonnes["DIRECT 0% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 2,5% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 5% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 10% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 15% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 20% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 30% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 40% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT NON GENERIQUES"]]
            + tableau[ligne][map_colonnes["DIRECT NON REMBOURSABLES"]]
            + tableau[ligne][map_colonnes["DIRECT OTC"]]
        )
        tableau[ligne][map_colonnes["DIFFERENCE REMISE DIRECT"]] = (
            tableau[ligne][map_colonnes["DIRECT REMISE OBTENUE"]]
            - tableau[ligne][map_colonnes["DIRECT REMISE THEORIQUE"]]
        )

        tableau[ligne][map_colonnes["TOTAL GENERAL HT"]] = (
            tableau[ligne][map_colonnes["GROSSISTE TOTAL HT"]]
            + tableau[ligne][map_colonnes["DIRECT TOTAL HT"]]
        )

        tableau[ligne][map_colonnes["TOTAL GENERIQUES >20% + OTC + NON GEN + NON RBS"]] = (
            tableau[ligne][map_colonnes["GROSSISTE 20% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 30% MONTANT HT"]]
            + tableau[ligne][map_colonnes["GROSSISTE 40% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 20% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 30% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT 40% MONTANT HT"]]
            + tableau[ligne][map_colonnes["DIRECT NON GENERIQUES"]]
            + tableau[ligne][map_colonnes["DIRECT NON REMBOURSABLES"]]
            + tableau[ligne][map_colonnes["DIRECT OTC"]]
        )

    return tableau


def traitement_remises_supp_eg(tableau, map_colonnes):

    for ligne in range(len(tableau)):
        tableau[ligne][map_colonnes["4% SUPPLEMENTAIRES THEORIQUES"]] = round(
            tableau[ligne][map_colonnes["TOTAL GENERIQUES >20% + OTC + NON GEN + NON RBS"]] * Decimal(0.04)
        , 2)

    return tableau


def generer_tableau_eg():
    colonnes = [
        "Mois/Année",
        "GROSSISTE 0% MONTANT HT",
        "GROSSISTE 2,5% MONTANT HT",
        "GROSSISTE 5% MONTANT HT",
        "GROSSISTE 10% MONTANT HT",
        "GROSSISTE 15% MONTANT HT",
        "GROSSISTE 20% MONTANT HT",
        "GROSSISTE 30% MONTANT HT",
        "GROSSISTE 40% MONTANT HT",
        "GROSSISTE TOTAL HT",
        "GROSSISTE REMISE THEORIQUE",
        "GROSSISTE REMISE OBTENUE",
        "DIFFERENCE REMISE GROSSISTE",
        "DIRECT 0% MONTANT HT",
        "DIRECT 2,5% MONTANT HT",
        "DIRECT 5% MONTANT HT",
        "DIRECT 10% MONTANT HT",
        "DIRECT 15% MONTANT HT",
        "DIRECT 20% MONTANT HT",
        "DIRECT 30% MONTANT HT",
        "DIRECT 40% MONTANT HT",
        "DIRECT NON GENERIQUES",
        "DIRECT NON REMBOURSABLES",
        "DIRECT OTC",
        "DIRECT TOTAL HT",
        "DIRECT REMISE THEORIQUE",
        "DIRECT REMISE OBTENUE",
        "DIFFERENCE REMISE DIRECT",
        "TOTAL GENERAL HT",
        "TOTAL GENERIQUES >20% + OTC + NON GEN + NON RBS",
        "4% SUPPLEMENTAIRES THEORIQUES"
    ]

    map_colonnes = {colonne: i for i, colonne in enumerate(colonnes)}
    tableau_eg = mois_annees_tab_eg(map_colonnes)

    # Récupérer les achats qui correspondent aux critères spécifiés
    achats_labo = (
        Achat.objects
        .filter(
            produit__fournisseur_generique='EG',
            categorie__startswith='GENERIQUE',
            categorie_remise__startswith='EG'
        )
        .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
        .values('mois', 'annee', 'categorie_remise', 'fournisseur')
        .annotate(
            total_ht_hors_remise=Sum('montant_ht_hors_remise'),
            remise_theorique_totale=Sum('remise_theorique_totale'),
            remise_obtenue=Sum(ExpressionWrapper(F('remise_pourcent') * F('montant_ht_hors_remise'), output_field=fields.DecimalField()))
        )
    )

    for entry in achats_labo:
        mois_annee = f"{entry['mois']}/{entry['annee']}"
        for ligne in tableau_eg:
            if ligne[0] == mois_annee:
                if 'CERP' in entry['fournisseur']:
                    if ' 0%' in entry['categorie_remise']:
                        ligne[map_colonnes["GROSSISTE 0% MONTANT HT"]] = Decimal(ligne[map_colonnes["GROSSISTE 0% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '2,5%' in entry['categorie_remise']:
                        ligne[map_colonnes["GROSSISTE 2,5% MONTANT HT"]] = Decimal(ligne[map_colonnes["GROSSISTE 2,5% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '5%' in entry['categorie_remise']:
                        ligne[map_colonnes["GROSSISTE 5% MONTANT HT"]] = Decimal(ligne[map_colonnes["GROSSISTE 5% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '10%' in entry['categorie_remise']:
                        ligne[map_colonnes["GROSSISTE 10% MONTANT HT"]] = Decimal(ligne[map_colonnes["GROSSISTE 10% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '15%' in entry['categorie_remise']:
                        ligne[map_colonnes["GROSSISTE 15% MONTANT HT"]] = Decimal(ligne[map_colonnes["GROSSISTE 15% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '20%' in entry['categorie_remise']:
                        ligne[map_colonnes["GROSSISTE 20% MONTANT HT"]] = Decimal(ligne[map_colonnes["GROSSISTE 20% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '30%' in entry['categorie_remise']:
                        ligne[map_colonnes["GROSSISTE 30% MONTANT HT"]] = Decimal(ligne[map_colonnes["GROSSISTE 30% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '40%' in entry['categorie_remise']:
                        ligne[map_colonnes["GROSSISTE 40% MONTANT HT"]] = Decimal(ligne[map_colonnes["GROSSISTE 40% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    
                    ligne[map_colonnes["GROSSISTE REMISE THEORIQUE"]] = Decimal(ligne[map_colonnes["GROSSISTE REMISE THEORIQUE"]]) + round(entry['remise_theorique_totale'], 2)
                    ligne[map_colonnes["GROSSISTE REMISE OBTENUE"]] = Decimal(ligne[map_colonnes["GROSSISTE REMISE OBTENUE"]]) + round(entry['remise_obtenue'], 2)

                elif entry['fournisseur'] == "EG":
                    if ' 0%' in entry['categorie_remise']:
                        ligne[map_colonnes["DIRECT 0% MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT 0% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '2,5%' in entry['categorie_remise']:
                        ligne[map_colonnes["DIRECT 2,5% MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT 2,5% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '5%' in entry['categorie_remise']:
                        ligne[map_colonnes["DIRECT 5% MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT 5% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '10%' in entry['categorie_remise']:
                        ligne[map_colonnes["DIRECT 10% MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT 10% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '15%' in entry['categorie_remise']:
                        ligne[map_colonnes["DIRECT 15% MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT 15% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '20%' in entry['categorie_remise']:
                        ligne[map_colonnes["DIRECT 20% MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT 20% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '30%' in entry['categorie_remise']:
                        ligne[map_colonnes["DIRECT 30% MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT 30% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif '40%' in entry['categorie_remise']:
                        ligne[map_colonnes["DIRECT 40% MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT 40% MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    
                    ligne[map_colonnes["DIRECT REMISE THEORIQUE"]] = Decimal(ligne[map_colonnes["DIRECT REMISE THEORIQUE"]]) + round(entry['remise_theorique_totale'], 2)
                    ligne[map_colonnes["DIRECT REMISE OBTENUE"]] = Decimal(ligne[map_colonnes["DIRECT REMISE OBTENUE"]]) + round(entry['remise_obtenue'], 2)

    achats_autres = (
        Achat.objects
        .filter(
            categorie__icontains='DIRECT LABO',
            produit__fournisseur_generique='EG'
        )
        .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
        .values('mois', 'annee', 'categorie', 'fournisseur')
        .annotate(
            total_ht_hors_remise=Sum('montant_ht_hors_remise'),
            remise_theorique_totale=Sum('remise_theorique_totale'),
            remise_obtenue=Sum(ExpressionWrapper(F('remise_pourcent') * F('montant_ht_hors_remise'), output_field=fields.DecimalField()))
        )
    )

    for entry in achats_autres:
        mois_annee = f"{entry['mois']}/{entry['annee']}"
        for ligne in tableau_eg:
            if ligne[0] == mois_annee:
                if entry['fournisseur'] == "EG":
                    if 'NON GENERIQUE' in entry['categorie']:
                        ligne[map_colonnes["DIRECT NON GENERIQUES"]] = Decimal(ligne[map_colonnes["DIRECT NON GENERIQUES"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif 'NON REMBOURSABLE' in entry['categorie']:
                        ligne[map_colonnes["DIRECT NON REMBOURSABLES"]] = Decimal(ligne[map_colonnes["DIRECT NON REMBOURSABLES"]]) + round(entry['total_ht_hors_remise'], 2)
                    elif 'OTC' in entry['categorie']:
                        ligne[map_colonnes["DIRECT OTC"]] = Decimal(ligne[map_colonnes["DIRECT OTC"]]) + round(entry['total_ht_hors_remise'], 2)


    tableau_eg = quicksort_tableau(tableau_eg)
    tableau_eg = totaux_tableau_eg(tableau_eg, map_colonnes)
    tableau_eg = traitement_remises_supp_eg(tableau_eg, map_colonnes)

    tableau_eg = totaux_pourcentages_par_annee(tableau_eg, colonnes, map_colonnes)

    return tableau_eg, colonnes


# -----------------------------------

# -------- TABLEAU ALLIANCE -------- 

# -----------------------------------


def mois_annees_tab_alliance(map_colonnes, filtre_annee, filtre_mois):
    tableau = []
    mois_annees = []

    data_mois_annees = (
        Releve_alliance.objects
        .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
        .filter(
            filtre_annee,
            filtre_mois,
            annee__gte = 2022,
        )
        .values('mois', 'annee')
    )

    for entry in data_mois_annees:
        mois_annee = f"{entry['mois']}/{entry['annee']}"
        if mois_annee not in mois_annees:
            mois_annees.append(mois_annee)

    for ma in mois_annees:
        nouvelle_ligne = [ma] + [0] * (len(map_colonnes) - 1)
        tableau.append(nouvelle_ligne)

    return tableau


def generer_tableau_alliance(show_decades, filtre_annee, filtre_mois):
    colonnes = [
        "Mois/Année",
        "Montant grossiste",
        "Montant short list",
        "Avantages commerciaux",
        "Frais generaux",
        "Facturation services",
        "Net à payer",
    ]

    map_colonnes = {colonne: i for i, colonne in enumerate(colonnes)}
    tableau_alliance = mois_annees_tab_alliance(map_colonnes, filtre_annee, filtre_mois)

    releves = (
        Releve_alliance.objects
        .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
        .filter(
            filtre_annee,
            filtre_mois,
            annee__gte = 2022,
        )
        .values('mois', 'annee')
        .annotate(
            net_a_payer=Sum('net_a_payer'),
            montant_grossiste=Sum('montant_grossiste'),
            montant_short_list=Sum('montant_short_list'),
            avantages_commerciaux=Sum('avantages_commerciaux'),
            frais_generaux=Sum('frais_generaux'),
            facturation_services=Sum('facturation_services'),
        )
    )

    for entry in releves:
        mois_annee = f"{entry['mois']}/{entry['annee']}"
        for ligne in tableau_alliance:
            if ligne[0] == mois_annee:
                ligne[map_colonnes["Net à payer"]] = round(entry['net_a_payer'], 2)
                ligne[map_colonnes["Montant grossiste"]] = round(entry['montant_grossiste'], 2)
                ligne[map_colonnes["Montant short list"]] = round(entry['montant_short_list'], 2)
                ligne[map_colonnes["Avantages commerciaux"]] = round(entry['avantages_commerciaux'], 2)
                ligne[map_colonnes["Frais generaux"]] = round(entry['frais_generaux'], 2)
                ligne[map_colonnes["Facturation services"]] = round(entry['facturation_services'], 2)

    tableau_alliance = quicksort_tableau(tableau_alliance)
    if filtre_mois.children == []:
        tableau_alliance = totaux_pourcentages_par_annee(tableau_alliance, colonnes, map_colonnes)

    if show_decades:
        tableau_alliance = ajouter_decades(tableau_alliance, map_colonnes, filtre_annee, filtre_mois)

    return tableau_alliance, colonnes


def ajouter_decades(tableau_alliance, map_colonnes, filtre_annee, filtre_mois):
    
    tableau_decades = []

    releves = (
        Releve_alliance.objects
        .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
        .filter(
            filtre_annee,
            filtre_mois,
            annee__gte = 2022,
        )
    )

    for entry in releves:
        nouvelle_ligne = [0] * (len(map_colonnes))
        tableau_decades.append(nouvelle_ligne)

    i = 0

    for entry in releves:
        ligne = tableau_decades[i]
        ligne[map_colonnes["Mois/Année"]] = entry.date.strftime('%d/%m/%Y')
        ligne[map_colonnes["Net à payer"]] = round(entry.net_a_payer, 2)
        ligne[map_colonnes["Montant grossiste"]] = round(entry.montant_grossiste, 2)
        ligne[map_colonnes["Montant short list"]] = round(entry.montant_short_list, 2)
        ligne[map_colonnes["Avantages commerciaux"]] = round(entry.avantages_commerciaux, 2)
        ligne[map_colonnes["Frais generaux"]] = round(entry.frais_generaux, 2)
        ligne[map_colonnes["Facturation services"]] = round(entry.facturation_services, 2)
        i += 1

    tableau_decades = quicksort_tableau_dates_classiques(tableau_decades)
    tableau_merged = []

    for mois in tableau_alliance:
        if "TOTAL" not in mois[0] and mois[0] != "" and mois[0] != "Mois/Année":
            mois_annee_date = convert_date(mois[0])
            
            for semaine in tableau_decades:
                semaine_date = convert_date(semaine[0])
                if semaine_date.year == mois_annee_date.year and semaine_date.month == mois_annee_date.month:
                    tableau_merged.append(semaine)

            tableau_merged.append(mois)
            tableau_merged[-1][0] = "=> " + tableau_merged[-1][0]
        else:
            tableau_merged.append(mois)
            
    return tableau_merged


# -----------------------------------

# -------- TABLEAU CERP + ALLIANCE --

# -----------------------------------


def mois_annees_tab_cerp_alliance(map_colonnes, filtre_annee, filtre_mois):
    tableau = []
    mois_annees = []

    data_mois_annees = (
        Achat.objects
        .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
        .filter(
            filtre_annee,
            filtre_mois,
            annee__gte = 2022,
        )
        .values('mois', 'annee')
    )

    for entry in data_mois_annees:
        mois_annee = f"{entry['mois']}/{entry['annee']}"
        if mois_annee not in mois_annees:
            mois_annees.append(mois_annee)

    for ma in mois_annees:
        nouvelle_ligne = [ma] + [0] * (len(map_colonnes) - 1)
        tableau.append(nouvelle_ligne)

    return tableau


def generer_tableau_cerp_alliance(filtre_annee, filtre_mois):
    colonnes = [
        "Mois/Année",
        "Montant CERP (Total TTC)",
        "Montant Alliance (Net à payer)",
        "TOTAL",
    ]

    map_colonnes = {colonne: i for i, colonne in enumerate(colonnes)}
    tableau_cerp_alliance = mois_annees_tab_cerp_alliance(map_colonnes, filtre_annee, filtre_mois)

    releves_cerp = (
        Releve_CERP.objects
        .annotate(mois=ExtractMonth('huitaine'), annee=ExtractYear('huitaine'))
        .filter(
            filtre_annee,
            filtre_mois,
            annee__gte = 2022,
        )
        .values('mois', 'annee')
        .annotate(
            total_ttc=Sum('total_ttc')
        )
    )

    releves_alliance = (
        Releve_alliance.objects
        .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
        .filter(
            filtre_annee,
            filtre_mois,
            annee__gte = 2022,
        )
        .values('mois', 'annee')
        .annotate(
            net_a_payer=Sum('net_a_payer'),
        )
    )

    for entry in releves_cerp:
        mois_annee = f"{entry['mois']}/{entry['annee']}"
        for ligne in tableau_cerp_alliance:
            if ligne[0] == mois_annee:
                ligne[map_colonnes["Montant CERP (Total TTC)"]] = round(entry['total_ttc'], 2)

    for entry in releves_alliance:
        mois_annee = f"{entry['mois']}/{entry['annee']}"
        for ligne in tableau_cerp_alliance:
            if ligne[0] == mois_annee:
                ligne[map_colonnes["Montant Alliance (Net à payer)"]] = round(entry['net_a_payer'], 2)

    for ligne in tableau_cerp_alliance:
        ligne[map_colonnes["TOTAL"]] = ligne[map_colonnes["Montant CERP (Total TTC)"]] + ligne[map_colonnes["Montant Alliance (Net à payer)"]]

    tableau_cerp_alliance = quicksort_tableau(tableau_cerp_alliance)
    if filtre_mois.children == []:
        tableau_alliance = totaux_pourcentages_par_annee(tableau_cerp_alliance, colonnes, map_colonnes)

    return tableau_alliance, colonnes