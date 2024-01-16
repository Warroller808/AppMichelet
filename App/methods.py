import os
import pdfplumber
import logging
import traceback
from datetime import datetime
from django.db import models
from django.conf import settings
from django.db.models import Sum, F, Q, ExpressionWrapper, fields, Subquery
from django.db.models.functions import ExtractMonth, ExtractYear, Cast, Concat
from decimal import Decimal
from .constants import DL_FOLDER_PATH_MANUAL, DL_FOLDER_PATH_AUTO
from .utils import *
from .models import Achat, Produit_catalogue, Avoir_remises


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
        logger.error(f'Erreur dans l\'exécution de process factures. Erreur : {e}')
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
                logger.error(f'({round(num_page / len(pdf.pages) * 100, 0)}%) {facture_name} - {num_page} en cours de traitement...')

            texte_page = page.extract_text()
            tables_page = []
            tables_page_2 = page.extract_tables()

            #print(texte_page)

            try:
                format, fournisseur = extraire_format_fournisseur(texte_page)
                format_inst = Format_facture.objects.get(pk=format)
                if format_inst.regex_date == "NA":
                    events.append(f'Facture ignorée, page {num_page + 1}')
                    continue
                tables_page = page.extract_tables(table_settings=format_inst.table_settings)

                date = datetime.strptime(extraire_date(format, texte_page), '%d/%m/%Y').date()
                numero_facture = extraire_numero_facture(format, texte_page)

                if not date or not numero_facture:
                    logger.error(f'Erreur de récupération de la date ou du numéro de facture donc page ignorée. Date : {date}, numéro de facture : {numero_facture}, format de facture : {format}')
                    continue

                texte_page_tout.append(texte_page)
                tables_page_toutes.append(tables_page)

            except:
                events.append(f'Format de facture non reconnu, page {num_page + 1}')
                texte_page_tout.append(texte_page)
                tables_page_toutes.append(tables_page)
                continue

            if format != "AVOIR REMISES CERP":
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
                if not Avoir_remises.objects.filter(numero=numero_facture):
                    success = process_avoir_remises(format, tables_page, numero_facture, date)

                    if success:
                        events.append(f'L\'avoir de remises {facture_name} - {numero_facture}, page {num_page +1} a été traité et sauvegardé')
                    else:
                        events.append(f'L\'avoir de remises {facture_name} - {numero_facture}, page {num_page +1} a rencontré une erreur de traitement, il n\'a pas été sauvegardé')
                else:
                    events.append(f'L\'avoir de remises {facture_name} - {numero_facture}, page {num_page +1} a déjà été traité par le passé, il n\'a donc pas été traité à nouveau')
            
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
            generique = (produit.type == "GENERIQUE")
            marche_produits = (produit.type == "MARCHE PRODUITS")
            pharmupp = produit.pharmupp
            lpp = produit.lpp
            # SI LA TVA MANQUE ON L'AJOUTE AVANT LA CATEGORISATION
            if dictligne["tva"] != 0:
                if produit.tva == 0:
                    produit.tva = dictligne["tva"]
                    produit.save()
            # SI FACTURE COALIA, LE PRODUIT EST MARQUE COMME VENDU CHEZ COALIA POUR LES FUTURS UPP
            if dictligne("fournisseur") == "CERP COALIA" and not produit.coalia:
                produit.coalia = True
                produit.save()

            coalia = produit.coalia
                    
        except:
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

            if new_categorie == "COALIA":
                new_coalia = True
            elif new_categorie.split()[0].upper() == "GENERIQUE":
                new_fournisseur_generique = determiner_fournisseur_generique(dictligne["designation"], dictligne["fournisseur"])
                new_type = "GENERIQUE"

            nouveau_produit = Produit_catalogue(
                code = dictligne["code"],
                annee = int(dictligne["date"].year),
                designation = dictligne["designation"],
                type = new_type,
                fournisseur_generique = new_fournisseur_generique,
                coalia = new_coalia,
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
                elif new_categorie == "MARCHE PRODUITS":
                    produit.type = new_categorie
                    produit.save()
            if new_categorie.split()[0].upper() == "GENERIQUE" and produit.fournisseur_generique == "":
                produit.fournisseur_generique = determiner_fournisseur_generique(dictligne["designation"], dictligne["fournisseur"])
                produit.save()

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
            categorie = new_categorie
        )
        
        #ON CALCULE LA REMISE THEORIQUE
        nouvel_achat = calculer_remise_theorique(produit, nouvel_achat)

        nouvel_achat.save()

    return events


def generer_tableau_synthese():

    # if categoriser():
    #     print("Catégorisation effectuée")

    tableau_synthese_assiette_globale = []
    tableau_synthese_autres = []
    data_dict = {}

    categories_assiette_globale = [
        'Mois/Année',
        '<450€ tva 2,1% TOTAL HT = ASSIETTE GLOBALE',
        'ASSIETTE GLOBALE -9%',
        'NB BOITES >450€',
        'REMISE THEORIQUE >450€',
        'PARAPHARMACIE TOTAL HT',
        'LPP 5,5 OU 10% TOTAL HT', 'LPP 20% TOTAL HT',
        'ASSIETTE GLOBALE REMISE TOTALE GROSSISTE THEORIQUE',
        'REMISE OBTENUE ASSIETTE GLOBALE',
        'REMISE OBTENUE LPP',
        'REMISE OBTENUE PARAPHARMACIE',
        'REMISE OBTENUE AVANTAGE COMMERCIAL',
        'REMISE OBTENUE TOTAL',
    ]
    categories_autres = [
        'Mois/Année',
        'GENERIQUE 2,1% TOTAL HT',
        'GENERIQUE 5,5% TOTAL HT',
        'GENERIQUE 10% TOTAL HT',
        'GENERIQUE 20% TOTAL HT',
        "GENERIQUE TOTAL HT",
        "NON GENERIQUE DIRECT LABO TOTAL HT",
        'MARCHE PRODUITS TOTAL HT',
        'MARCHE PRODUITS REMISE OBTENUE HT',
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

        #pour chaque catégorie connue, on ajoute la somme dans le tableau
        tableau_synthese_assiette_globale = remplir_valeurs_categories(data_dict, tableau_synthese_assiette_globale, categories_assiette_globale)
        tableau_synthese_autres = remplir_valeurs_categories(data_dict, tableau_synthese_autres, categories_autres)

        #REMPLISSAGE DES COLONNES ASSIETTE GLOBALE
        tableau_synthese_assiette_globale = traitement_colonnes_assiette_globale(tableau_synthese_assiette_globale, map_assglob)
        tableau_synthese_autres = traitement_totaux_autres(tableau_synthese_assiette_globale, tableau_synthese_autres, map_assglob, map_autres)

        #REMPLISSAGE REMISES OBTENUES ASSIETTE GLOBALE
        tableau_synthese_assiette_globale = remplir_remises_obtenues(tableau_synthese_assiette_globale, map_assglob)

        #LIGNES DE TOTAUX PAR ANNEE
        tableau_synthese_assiette_globale = totaux_pourcentages_par_annee(tableau_synthese_assiette_globale, categories_assiette_globale)
        tableau_synthese_autres = totaux_pourcentages_par_annee(tableau_synthese_autres, categories_autres)

        return tableau_synthese_assiette_globale, categories_assiette_globale, tableau_synthese_autres, categories_autres
    
    except Exception as e:
        logger.error(f"Erreur de génération du tableau synthèse, erreur {e}. Traceback : {traceback.format_exc()}")
        return tableau_synthese_assiette_globale, categories_assiette_globale, tableau_synthese_autres, categories_autres
    

def remplir_valeurs_categories(data_dict, tableau, categories):

    i = 0

    for mois_annee, values in data_dict.items():
        tableau.append([mois_annee])
        #On parcourt les colonnes grace à la liste des titres de colonne
        for cat in categories[1:]:
            #Si la colonne n'est jamais trouvée, on met la valeur à 0
            found = False
            print(cat)
            if "TOTAL HT" in cat:
                for categorie, montant in values.items():
                    if categorie in cat:
                        tableau[i].append(round(montant, 2))
                        found = True
            elif "REMISE OBTENUE HT" in cat:
                for categorie, montant in values.items():
                    if categorie in cat:
                        print(categorie)
                        tableau[i].append(round(montant, 2))
                        found = True
            if not found:
                tableau[i].append(0.00)
        i += 1

    tableau = quicksort_tableau(tableau)

    return tableau


def traitement_colonnes_assiette_globale(tableau, map_assglob):

    data_dict_nb_boites = {}

    try:
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

        for ligne in range(len(tableau)):
            if tableau[ligne][0] in data_dict_nb_boites:
                tableau[ligne][map_assglob["NB BOITES >450€"]] = data_dict_nb_boites[tableau[ligne][0]]["Total_boites"]
            else:
                tableau[ligne][map_assglob["NB BOITES >450€"]] = round(Decimal(0), 0)

        for ligne in range(len(tableau)):
            tableau[ligne][map_assglob["ASSIETTE GLOBALE -9%"]] = round(Decimal(tableau[ligne][map_assglob["<450€ tva 2,1% TOTAL HT = ASSIETTE GLOBALE"]]) * Decimal(0.91), 2)
            tableau[ligne][map_assglob["REMISE THEORIQUE >450€"]] = round(Decimal(tableau[ligne][map_assglob["NB BOITES >450€"]]) * Decimal(15), 2)

            remise_totale = round(Decimal(tableau[ligne][map_assglob["ASSIETTE GLOBALE -9%"]]) * Decimal(0.025), 2)
            remise_totale += round(Decimal(tableau[ligne][map_assglob["REMISE THEORIQUE >450€"]]), 2)
            remise_totale += round(Decimal(tableau[ligne][map_assglob["PARAPHARMACIE TOTAL HT"]]) * Decimal(0.038), 2)
            remise_totale += round((Decimal(tableau[ligne][map_assglob["LPP 5,5 OU 10% TOTAL HT"]]) + Decimal(tableau[ligne][map_assglob["LPP 20% TOTAL HT"]])) * Decimal(0.038), 2)
            remise_totale += round(Decimal(tableau[ligne][map_assglob["ASSIETTE GLOBALE -9%"]]) * Decimal(0.013), 2)
            tableau[ligne][map_assglob["ASSIETTE GLOBALE REMISE TOTALE GROSSISTE THEORIQUE"]] = remise_totale

    except Exception as e:
        logger.error(f'Erreur de traitement des colonnes assiette globale : {e}. Traceback : {traceback.format_exc()}')

    return tableau


def remplir_remises_obtenues(tableau, map_assglob):

    for ligne in range(len(tableau)):
        avoir_remises = Avoir_remises.objects.filter(mois_concerne=tableau[ligne][0]).first()
        if not avoir_remises is None:
            tableau[ligne][map_assglob["REMISE OBTENUE ASSIETTE GLOBALE"]] = round(avoir_remises.specialites_pharmaceutiques, 2)
            tableau[ligne][map_assglob["REMISE OBTENUE LPP"]] = round(avoir_remises.lpp, 2)
            tableau[ligne][map_assglob["REMISE OBTENUE PARAPHARMACIE"]] = round(avoir_remises.parapharmacie, 2)
            tableau[ligne][map_assglob["REMISE OBTENUE AVANTAGE COMMERCIAL"]] = round(avoir_remises.avantage_commercial, 2)

            tableau[ligne][map_assglob["REMISE OBTENUE TOTAL"]] = tableau[ligne][map_assglob["REMISE OBTENUE ASSIETTE GLOBALE"]] 
            tableau[ligne][map_assglob["REMISE OBTENUE TOTAL"]] += tableau[ligne][map_assglob["REMISE OBTENUE LPP"]]
            tableau[ligne][map_assglob["REMISE OBTENUE TOTAL"]] += tableau[ligne][map_assglob["REMISE OBTENUE PARAPHARMACIE"]] 
            tableau[ligne][map_assglob["REMISE OBTENUE TOTAL"]] += tableau[ligne][map_assglob["REMISE OBTENUE AVANTAGE COMMERCIAL"]]

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
        total_general += Decimal(tableau_assiette_globale[ligne][map_assglob["PARAPHARMACIE TOTAL HT"]])
        total_general += Decimal(tableau_assiette_globale[ligne][map_assglob["LPP 5,5 OU 10% TOTAL HT"]]) 
        total_general += Decimal(tableau_assiette_globale[ligne][map_assglob["LPP 20% TOTAL HT"]])
        total_general += Decimal(tableau_autres[ligne][map_autres["GENERIQUE TOTAL HT"]]) 
        total_general += Decimal(tableau_autres[ligne][map_autres["NON GENERIQUE DIRECT LABO TOTAL HT"]])
        total_general += Decimal(tableau_autres[ligne][map_autres["MARCHE PRODUITS TOTAL HT"]]) 
        total_general += Decimal(tableau_autres[ligne][map_autres["UPP TOTAL HT"]])
        total_general += Decimal(tableau_autres[ligne][map_autres["COALIA TOTAL HT"]]) 
        total_general += Decimal(tableau_autres[ligne][map_autres["PHARMAT TOTAL HT"]])
        tableau_autres[ligne][-1] = total_general
    
    return tableau_autres


def totaux_pourcentages_par_annee(tableau, categories):
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
                if tableau[ligne - 1][0] != "":
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
                
            elif tableau[ligne - 1][0] != "":
                if convert_date(tableau[ligne][0]).year != convert_date(tableau[ligne - 1][0]).year:
                    traitement = True
                    #print("comparaison de dates")
            else:
                pass
                #print("ne correspond à aucun cas")
            
            #print(traitement)
            if traitement:
                # ici, ligne est la ligne juste après le changement de date, donc on va insérer les totaux avant
                # Ligne de totaux initialisée avec un vide pour la colonne mois annee
                totaux = [f'TOTAL {convert_date(tableau[ligne - 1][0]).year}']
                for colonne in range(1, len(tableau[0])):
                    total = Decimal(0)
                    for ligne_annee in range(ligne_annee_precedente + 1, ligne):
                        total += Decimal(tableau[ligne_annee][colonne])
                    totaux.append(round(total, 2))

                #print(f'totaux calculés entre {ligne_annee_precedente + 1} et {ligne - 1}')

                #ligne de pourcentages initialisée avec un vide pour la colonne mois annee
                pourcentages = calcul_pourcentages(len(tableau[0]), totaux, categories)

                tableau.insert(ligne, totaux)
                tableau.insert(ligne + 1, pourcentages)
                #print(f'totaux inseres en {ligne} et pourcentages en {ligne + 1}')
                if not double_traitement:
                    ligne_annee_precedente = ligne + 1
                    ligne += 2
                else:
                    ligne_annee_precedente = ligne + 1
                    ligne += 1
            else:
                ligne += 1
        else:
            ligne += 1

    return tableau


def calcul_pourcentages(taille_tableau, totaux, categories):

    pourcentages = ['']
    for colonne in range(1, taille_tableau):
        if "REMISE OBTENUE TOTAL" in categories[colonne]:
            if totaux[colonne - 5] != 0:
                pourcentages.append(f'{round(totaux[colonne] / totaux[colonne - 5] * 100, 2)} %')
            else:
                pourcentages.append('NA')
        elif "GROSSISTE REMISE OBTENUE" in categories[colonne]:
            if totaux[colonne - 1] != 0:
                pourcentages.append(f'{round(totaux[colonne] / totaux[colonne - 1] * 100, 2)} %')
            else:
                pourcentages.append('NA')
        elif "DIRECT REMISE OBTENUE" in categories[colonne]:
            if totaux[colonne - 1] != 0:
                pourcentages.append(f'{round(totaux[colonne] / totaux[colonne - 1] * 100, 2)} %')
            else:
                pourcentages.append('NA')
        elif "REMISE OBTENUE HT" in categories[colonne]:
            if totaux[colonne - 1] != 0:
                pourcentages.append(f'{round(totaux[colonne] / totaux[colonne - 1] * 100, 2)} %')
            else:
                pourcentages.append('NA')
        else:
            pourcentages.append('')
    
    return pourcentages

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
        "DIRECT 2,1% MONTANT HT",
        "DIRECT 5,5% MONTANT HT",
        "DIRECT 10% MONTANT HT",
        "DIRECT 20% MONTANT HT",
        "DIRECT NON GENERIQUES MONTANT HT",
        "DIRECT TOTAL HT",
        "DIRECT REMISE THEORIQUE",
        "DIRECT REMISE OBTENUE",
        "TOTAL GENERAL HT"
    ]

    tableau_generiques = mois_annees_tab_generiques(len(colonnes))
    map_colonnes = {colonne: i for i, colonne in enumerate(colonnes)}

    # Récupérer les achats qui correspondent aux critères spécifiés
    achats_labo = (
        Achat.objects
        .filter(
            produit__fournisseur_generique=fournisseur_generique,
            categorie__icontains="GENERIQUE",
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
                        ligne[map_colonnes["DIRECT NON GENERIQUES MONTANT HT"]] = Decimal(ligne[map_colonnes["DIRECT NON GENERIQUES MONTANT HT"]]) + round(entry['total_ht_hors_remise'], 2)
                    
                    ligne[map_colonnes["DIRECT REMISE THEORIQUE"]] = Decimal(ligne[map_colonnes["DIRECT REMISE THEORIQUE"]]) + round(entry['remise_theorique_totale'], 2)
                    ligne[map_colonnes["DIRECT REMISE OBTENUE"]] = Decimal(ligne[map_colonnes["DIRECT REMISE OBTENUE"]]) + round(entry['remise_obtenue'], 2)

    #print(tableau_generiques)

    tableau_generiques = quicksort_tableau(tableau_generiques)

    tableau_generiques = colonnes_totaux_generiques(tableau_generiques, map_colonnes)
    tableau_generiques = totaux_pourcentages_par_annee(tableau_generiques, colonnes)

    return tableau_generiques, colonnes, achats_labo


def mois_annees_tab_generiques(nb_colonnes):
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
        nouvelle_ligne = [ma] + [0] * (nb_colonnes - 1)
        tableau.append(nouvelle_ligne)

    return tableau


def colonnes_totaux_generiques(tableau, map_colonnes):

    for ligne in range(len(tableau)):
        tableau[ligne][map_colonnes["GROSSISTE TOTAL HT"]] = tableau[ligne][map_colonnes["GROSSISTE 2,1% MONTANT HT"]]
        tableau[ligne][map_colonnes["GROSSISTE TOTAL HT"]] += tableau[ligne][map_colonnes["GROSSISTE 5,5% MONTANT HT"]]
        tableau[ligne][map_colonnes["GROSSISTE TOTAL HT"]] += tableau[ligne][map_colonnes["GROSSISTE 10% MONTANT HT"]]
        tableau[ligne][map_colonnes["GROSSISTE TOTAL HT"]] += tableau[ligne][map_colonnes["GROSSISTE 20% MONTANT HT"]]

        tableau[ligne][map_colonnes["DIRECT TOTAL HT"]] = tableau[ligne][map_colonnes["DIRECT 2,1% MONTANT HT"]]
        tableau[ligne][map_colonnes["DIRECT TOTAL HT"]] += tableau[ligne][map_colonnes["DIRECT 5,5% MONTANT HT"]]
        tableau[ligne][map_colonnes["DIRECT TOTAL HT"]] += tableau[ligne][map_colonnes["DIRECT 10% MONTANT HT"]]
        tableau[ligne][map_colonnes["DIRECT TOTAL HT"]] += tableau[ligne][map_colonnes["DIRECT 20% MONTANT HT"]]

        tableau[ligne][map_colonnes["TOTAL GENERAL HT"]] = tableau[ligne][map_colonnes["GROSSISTE TOTAL HT"]]
        tableau[ligne][map_colonnes["TOTAL GENERAL HT"]] += tableau[ligne][map_colonnes["DIRECT TOTAL HT"]]

    return tableau



