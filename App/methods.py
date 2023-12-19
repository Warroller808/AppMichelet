import os
from django.conf import settings
import pdfplumber
from .utils import *
from .models import Achat, Produit_catalogue
from datetime import datetime
from django.db.models import Sum
from django.db.models.functions import ExtractMonth, ExtractYear
from decimal import Decimal
import logging
import traceback

BASE_DIR = settings.BASE_DIR
logger = logging.getLogger(__name__)

def handle_uploaded_facture(facture):
    dossier_sauvegarde = os.path.join(BASE_DIR, 'media/factures')

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


def extract_data(facture_path, facture_name):
    with pdfplumber.open(facture_path) as pdf:

        table_donnees = []
        table_produits = []
        texte_page_tout = []
        tables_page_toutes = []
        events = []

        for num_page in range(len(pdf.pages)):
            page = pdf.pages[num_page]

            print(f'{facture_name} - {num_page}')

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
                texte_page_tout.append(texte_page)
                tables_page_toutes.append(tables_page)

                date = datetime.strptime(extraire_date(format, texte_page), '%d/%m/%Y').date()
                numero_facture = extraire_numero_facture(format, texte_page)

            except:
                events.append(f'Format de facture non reconnu, page {num_page + 1}')
                texte_page_tout.append(texte_page)
                tables_page_toutes.append(tables_page)
                continue

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
            
    return table_donnees, table_produits, events, texte_page_tout, tables_page_toutes, tables_page_2


def save_data(table_donnees):
    #Sauvegarde les données d'une facture
    events = []

    #Enregistrement des achats dans la bdd
    for ligne in table_donnees:

        dictligne = {
            "produit": ligne[0],
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
            produit = Produit_catalogue.objects.get(code=dictligne["produit"], annee=dictligne["date"].year)
            generique = (produit.type == "GENERIQUE")
            marche_produits = (produit.type == "MARCHE PRODUITS")
            pharmupp = produit.pharmupp
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

        #MODIFIER LA CATEGORISATION POUR RECUP DEPUIS LE PRODUIT LE MARCHE PRODUITS
        new_categorie = categoriser_achat(dictligne["designation"], dictligne["fournisseur"], dictligne["tva"], dictligne["prix_unitaire_ht"], dictligne["remise_pourcent"], coalia, generique, marche_produits, pharmupp)

        #IMPORTATION DU PRODUIT POUR AVOIR LA REMISE THEORIQUE

        if not Produit_catalogue.objects.filter(code=dictligne["produit"], annee=dictligne["date"].year):
            #SI LE PRODUIT N'EXISTE PAS IL FAUT LE CREER

            new_coalia = False
            new_fournisseur_generique = ""
            new_type = ""

            if new_categorie == "COALIA":
                new_coalia = True
            elif new_categorie == "GENERIQUE":
                if dictligne["fournisseur"] == "TEVA" or dictligne["fournisseur"] == "EG" or dictligne["fournisseur"] == "BIOGARAN"  or dictligne["fournisseur"] == "ARROW" :
                    new_fournisseur_generique = dictligne["fournisseur"]
                new_type = "GENERIQUE"        

            nouveau_produit = Produit_catalogue(
                code = dictligne["produit"],
                annee = int(dictligne["date"].year),
                designation = dictligne["designation"],
                type = new_type,
                fournisseur_generique = new_fournisseur_generique,
                coalia = new_coalia,
                remise_grossiste = "",
                remise_direct = "",
                tva = dictligne["tva"]
            )
            nouveau_produit.save()
            events.append(f'Le produit suivant a été créé sans remise, merci de compléter sa fiche dans l\'interface admin : {ligne[0]} - {ligne[1]}')

        else:
            #produit existe => mise à jour en fonction de la catégorie
            produit = Produit_catalogue.objects.get(code=dictligne["produit"], annee=dictligne["date"].year)
            if produit.type == "":
                if new_categorie == "GENERIQUE" or new_categorie == "MARCHE PRODUITS":
                    produit.type = new_categorie
                    produit.save()
            if new_categorie == "GENERIQUE" and produit.fournisseur_generique == "":
                if dictligne["fournisseur"] == "TEVA" or dictligne["fournisseur"] == "EG" or dictligne["fournisseur"] == "BIOGARAN"  or dictligne["fournisseur"] == "ARROW" :
                    produit.fournisseur_generique = dictligne["fournisseur"]
                    produit.save()

        #ON IMPORTE LE PRODUIT A NOUVEAU
        produit = Produit_catalogue.objects.get(code=dictligne["produit"], annee=dictligne["date"].year)

        #ON CREE L'ACHAT
        nouvel_achat = Achat(
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

    tableau_synthese = []
    data_dict = {}
    categories = [
        '<450€ tva 2,1% TOTAL HT', '<450€ tva 2,1% REMISE HT',
        'PARAPHARMACIE TOTAL HT', 'PARAPHARMACIE REMISE HT',
        'LPP TOTAL HT', 'LPP REMISE HT',
        'ASSIETTE GLOBALE TOTAL HT', 'ASSIETTE GLOBALE REMISE HT',
        'ASS.GLOB -9% TOTAL HT', 'ASS.GLOB -9% REMISE HT',
        'GENERIQUE TOTAL HT', 'GENERIQUE REMISE HT',
        'MARCHE PRODUITS TOTAL HT', 'MARCHE PRODUITS REMISE HT',
        'UPP TOTAL HT', 'UPP REMISE HT',
        'COALIA TOTAL HT', 'COALIA REMISE HT',
        'PHARMAT TOTAL HT', 'PHARMAT REMISE HT',
    ]

    try:

        data = (
            Achat.objects
            .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
            .values('mois', 'annee', 'categorie')
            .annotate(total_ht_hors_remise=Sum('montant_ht_hors_remise'), remise_theorique_totale=Sum('remise_theorique_totale'))
        )

        

        # Pour contrôle des produits non catégorisés
        #' TOTAL HT', ' REMISE HT'

        for entry in data:
            mois_annee = f"{entry['mois']}/{entry['annee']}"
            categorie = entry['categorie']
            total_ht_hors_remise = entry['total_ht_hors_remise']
            remise_theorique_totale = entry['remise_theorique_totale']

            # Si la clé mois_annee n'existe pas encore dans le dictionnaire, créez-la
            if mois_annee not in data_dict:
                data_dict[mois_annee] = {}

            # Remplissage du dictionnaire avec les valeurs
            data_dict[mois_annee][f"{categorie} TOTAL HT"] = total_ht_hors_remise
            data_dict[mois_annee][f"{categorie} REMISE HT"] = remise_theorique_totale

        i = 0

        for mois_annee, values in data_dict.items():
            tableau_synthese.append([mois_annee])
            for cat in categories:
                found = False
                for categorie, montant in values.items():
                    if categorie == cat:
                        tableau_synthese[i].append(round(montant, 2))
                        found = True
                if not found:
                    tableau_synthese[i].append(0.00)
            i += 1

        tableau_synthese = quicksort_tableau(tableau_synthese)

        #AJOUT DES COLONNES ASSIETTE GLOBALE

        for colonne in range(len(categories)):
            # on remplit les colonnes qui étaient à 0
            if "ASSIETTE GLOBALE" in categories[colonne]:
                for ligne in range(len(tableau_synthese)):
                    tableau_synthese[ligne][colonne + 1] = tableau_synthese[ligne][colonne - 1] + tableau_synthese[ligne][colonne - 3] + tableau_synthese[ligne][colonne - 5]
            elif "-9%" in categories[colonne]:
                for ligne in range(len(tableau_synthese)):
                    tableau_synthese[ligne][colonne + 1] = round(Decimal(tableau_synthese[ligne][colonne - 1]) * Decimal(0.81), 2)

        #LIGNES DE TOTAUX PAR ANNEE

        ligne = 0
        ligne_annee_precedente = -1

        while ligne < len(tableau_synthese):
            print(f'ligne: {ligne}, derniere ligne: {len(tableau_synthese) - 1}')
            if tableau_synthese[ligne][0] != "" and tableau_synthese[ligne][0] != "TOTAL" and tableau_synthese[ligne - 1][0] != "TOTAL":
                
                traitement = False

                if ligne == 0:
                    if ligne == len(tableau_synthese) - 1:
                        traitement = True
                        # on simule l'avance sur la prochaine ligne
                        ligne += 1
                elif ligne == len(tableau_synthese) - 1:
                    traitement = True
                    # on simule l'avance sur la prochaine ligne
                    ligne += 1
                    print(f'derniere ligne : ligne {ligne} / {len(tableau_synthese) - 1}. Nb elements : {len(tableau_synthese)}')
                elif tableau_synthese[ligne - 1][0] != "":
                    if convert_date(tableau_synthese[ligne][0]).year != convert_date(tableau_synthese[ligne - 1][0]).year:
                        traitement = True
                        print("comparaison de dates")
                else:
                    print("ne correspond à aucun cas")
                
                print(traitement)
                if traitement:
                    # ici, ligne est la ligne juste après le changement de date, donc on va insérer les totaux avant
                    # Ligne de totaux initialisée avec un vide pour la colonne mois annee
                    totaux = [f'TOTAL {convert_date(tableau_synthese[ligne - 1][0]).year}']
                    for colonne in range(1, len(tableau_synthese[0])):
                        total = Decimal(0)
                        for ligne_annee in range(ligne_annee_precedente + 1, ligne):
                            total += Decimal(tableau_synthese[ligne_annee][colonne])
                        totaux.append(round(total, 2))

                    print(f'totaux calculés entre {ligne_annee_precedente + 1} et {ligne - 1}')

                    #ligne de pourcentages initialisée avec un vide pour la colonne mois annee
                    pourcentages = ['']
                    for colonne in range(1, len(tableau_synthese[0])):
                        if "REMISE" in categories[colonne - 1]:
                            if totaux[colonne - 1] != 0:
                                pourcentages.append(f'{round(totaux[colonne] / totaux[colonne - 1] * 100, 2)} %')
                            else:
                                pourcentages.append('NA')
                        else:
                            pourcentages.append('')

                    tableau_synthese.insert(ligne, totaux)
                    tableau_synthese.insert(ligne + 1, pourcentages)
                    print(f'totaux inseres en {ligne} et pourcentages en {ligne + 1}')
                    ligne_annee_precedente = ligne + 1
                    ligne += 2
                else:
                    ligne += 1
            else:
                ligne += 1

        return tableau_synthese, categories
    
    except Exception as e:
        logger.error(f"Erreur de génération du tableau synthèse, erreur {e}. Traceback : {traceback.format_exc()}")
        return tableau_synthese, categories


def generer_tableau_generiques():
    
    # data = (
    #     Produit_catalogue.objects
    #     .filter(annee=your_desired_year)  # Remplacez your_desired_year par l'année souhaitée
    #     .values('fournisseur_generique')
    #     .annotate(
    #         somme_montants_ht=Sum(
    #             ExpressionWrapper(
    #                 F('achat__montant_ht_hors_remise'),
    #                 output_field=DecimalField(),
    #             )
    #         ),
    #         somme_remises_ht=Sum(
    #             ExpressionWrapper(
    #                 F('achat__remise_theorique_totale'),
    #                 output_field=DecimalField(),
    #             )
    #         )
    #     )
    #     .filter(achat__code_produit=F('code_produit'), achat__date__year=your_desired_year)
    # )
    # tableau_generiques = []
    # for entry in data:
    #     print(entry)

    return 1