import os
from django.conf import settings
import pdfplumber
from .utils import *
from .models import Achat, Produit_catalogue
from datetime import datetime
import json
from django.db.models import Sum
from django.db.models.functions import ExtractMonth, ExtractYear
from celery import shared_task

BASE_DIR = settings.BASE_DIR

@shared_task
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

@shared_task
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

            try:
                format, fournisseur = extraire_format_fournisseur(texte_page)
                format_inst = Format_facture.objects.get(pk=format)
                if format_inst.regex_date == "NA":
                    events.append(f'Facture ignorée, page {num_page + 1}')
                    continue
                tables_page = page.extract_tables(table_settings=format_inst.table_settings)
                texte_page_tout.append(texte_page)
                tables_page_toutes.append(tables_page)

            except:
                events.append(f'Format de facture non reconnu, page {num_page + 1}')
                texte_page_tout.append(texte_page)
                tables_page_toutes.append(tables_page)
                continue
        
            date = datetime.strptime(extraire_date(format, texte_page), '%d/%m/%Y').date()
            numero_facture = extraire_numero_facture(format, texte_page)

            # On vérifie si la facture a déjà été traitée, si oui on prévient
            if not Achat.objects.filter(numero_facture=numero_facture):
                processed_table, events_achats = process_tables(format, tables_page)
                produits = extraire_produits(format, fournisseur, tables_page)

                for ligne in range(len(processed_table)):
                    processed_table[ligne].extend([date, facture_name, numero_facture, fournisseur])
                    table_donnees.append(processed_table[ligne])

                table_produits.extend(produits)
                events.extend(events_achats)
                texte_page_tout.append(texte_page)
                tables_page_toutes.append(tables_page)
            else:
                events.append(f'La facture {numero_facture}, page {num_page +1} a déjà été traitée par le passé, elle n\'a donc pas été traitée à nouveau')
            
    return table_donnees, table_produits, events, texte_page_tout, tables_page_toutes, tables_page_2

@shared_task
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
            coalia = produit.coalia
            generique = (produit.type == "GENERIQUE")
            # SI LA TVA MANQUE ON L'AJOUTE AVANT LA CATEGORISATION
            if dictligne["tva"] != 0:
                if produit.tva == 0:
                    produit.tva = dictligne["tva"]
                    produit.save()
        except:
            coalia = (dictligne["fournisseur"] == "CERP COALIA")
            generique = (dictligne["fournisseur"] == "TEVA" or dictligne["fournisseur"] == "EG" or dictligne["fournisseur"] == "BIOGARAN"  or dictligne["fournisseur"] == "ARROW")

        new_categorie = categoriser_achat(dictligne["fournisseur"], dictligne["tva"], dictligne["prix_unitaire_ht"], coalia, generique)

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
        remise = 0
        nouvel_achat.remise_theorique_totale = 0

        if new_categorie == "COALIA":
            if produit.remise_direct:
                for r in json.loads(produit.remise_direct):
                    if dictligne["nb_boites"] >= r[0]:
                        remise = r[1]
                nouvel_achat.remise_theorique_totale = nouvel_achat.montant_ht_hors_remise * remise
        if new_categorie == "PHARMAT":
            #Cas particulier Pharmat car pas de remises catalogue
            if dictligne["remise_pourcent"] != 0:
                nouvel_achat.remise_theorique_totale = nouvel_achat.montant_ht_hors_remise * dictligne["remise_pourcent"]
        elif "CERP" not in dictligne["fournisseur"] and new_categorie == "GENERIQUE":
            #GENERIQUE NON CERP donc en direct
            if produit.remise_direct:
                for r in json.loads(produit.remise_direct):
                    if dictligne["nb_boites"] >= r[0]:
                        remise = r[1]
                nouvel_achat.remise_theorique_totale = nouvel_achat.montant_ht_hors_remise * remise
        elif "CERP" in dictligne["fournisseur"] and new_categorie == "GENERIQUE":
            #GENERIQUE CERP
            if produit.remise_grossiste:
                for r in json.loads(produit.remise_grossiste):
                    if dictligne["nb_boites"] >= r[0]:
                        remise = r[1]
                nouvel_achat.remise_theorique_totale = nouvel_achat.montant_ht_hors_remise * remise
        else:
            #UPP, CERP, LPP, PARAPHARMA
            #TRANCHES D'€ SEULEMENT SI PAS PARAPHARMA, UPP ou LPP
            if new_categorie == "UPP":
                #Si upp, remise grossiste si existante, sinon 0 par défaut
                if produit.remise_grossiste:
                    for r in json.loads(produit.remise_direct):
                        if dictligne["nb_boites"] >= r[0]:
                            remise = r[1]
                    nouvel_achat.remise_theorique_totale = nouvel_achat.montant_ht_hors_remise * remise
            else:
                remise = choix_remise_grossiste(produit, new_categorie, dictligne["nb_boites"])
                if remise < 1:
                    #remise classique en %
                    nouvel_achat.remise_theorique_totale = nouvel_achat.montant_ht_hors_remise * remise
                else:
                    #remise en €
                    nouvel_achat.remise_theorique_totale = remise

        nouvel_achat.save()

    return events


def generer_tableau_synthese():

    # if categoriser():
    #     print("Catégorisation effectuée")

    data = (
        Achat.objects
        .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
        .values('mois', 'annee', 'categorie')
        .annotate(total_ht_hors_remise=Sum('montant_ht_hors_remise'), remise_theorique_totale=Sum('remise_theorique_totale'))
    )

    data_dict = {}
    categories = [
        '<450€ tva 2,1% TOTAL HT', '<450€ tva 2,1% REMISE HT',
        '>450€ <1500€ tva 2,1% TOTAL HT', '>450€ <1500€ tva 2,1% REMISE HT',
        '>1500€ tva 2,1% TOTAL HT', '>1500€ tva 2,1% REMISE HT',
        'COALIA TOTAL HT', 'COALIA REMISE HT',
        'PHARMAT TOTAL HT', 'PHARMAT REMISE HT',
        'GENERIQUE TOTAL HT', 'GENERIQUE REMISE HT',
        'PARAPHARMACIE TOTAL HT', 'PARAPHARMACIE REMISE HT',
        'LPP TOTAL HT', 'LPP REMISE HT',
        'UPP TOTAL HT', 'UPP REMISE HT',
        ' TOTAL HT', ' REMISE HT'
    ]

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

    tableau_synthese = []
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

    tableau_synthese = quicksort(tableau_synthese)

    print(datetime.now())
    print(tableau_synthese)

    return tableau_synthese, categories


def categoriser():
    #try:
        achats = Achat.objects.all()
        for entry in achats:
            if entry.categorie == "":
                produit = Produit_catalogue.objects.get(code=entry.produit, annee=entry.date.year)

                if entry.fournisseur == "EG LABO":
                    entry.fournisseur = "EG"

                if entry.fournisseur == "CERP COALIA":
                    entry.categorie = "COALIA"
                elif entry.fournisseur == "CERP PHARMAT" or entry.fournisseur == "PHARMAT" :
                    entry.categorie = "PHARMAT"
                elif entry.fournisseur == "CERP" or entry.fournisseur == "CERP MAGASIN GENERAL" or entry.fournisseur == "CERP SUPPLEMENT" or entry.fournisseur == "CERP COMMANDE RESEAU":
                    if produit.type == "GENERIQUE":
                        entry.categorie = "GENERIQUE"
                    elif produit.coalia:
                        entry.categorie = "UPP"
                    elif entry.tva == 0.021 and entry.prix_unitaire_ht < 450:
                        entry.categorie = "<450€ tva 2,1%"
                    elif entry.tva == 0.021 and entry.prix_unitaire_ht > 450 and entry.prix_unitaire_ht < 1500:
                        entry.categorie = ">450€ <1500€ tva 2,1%"
                    elif entry.tva == 0.021 and entry.prix_unitaire_ht > 1500:
                        entry.categorie = ">1500€ tva 2,1%"
                    elif entry.tva == 0.055 or entry.tva == 0.1:
                        entry.categorie = "LPP"
                    elif entry.tva == 0.20:
                        entry.categorie = "PARAPHARMACIE"
                elif entry.fournisseur == "TEVA" or entry.fournisseur == "EG" or entry.fournisseur == "BIOGARAN"  or entry.fournisseur == "ARROW" :
                    entry.categorie = "GENERIQUE"
                else:
                    print(f"aucune catégorie trouvée pour {entry.produit} - {entry.date}")
                    continue

                entry.save()

        return True
    
    #except:
        return False