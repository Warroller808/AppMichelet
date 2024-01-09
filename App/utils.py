import re
import logging
from .models import Format_facture, Produit_catalogue, Achat, Avoir_remises
import json
from datetime import datetime, timedelta
from .constants import *
from decimal import Decimal


logger = logging.getLogger(__name__)


def extraire_format_fournisseur(texte):
    format_trouve = None
    texte_page = texte.replace("\n", " ").strip()

    #print(texte_page)
    for instance in Format_facture.objects.all():
        #print(f"Regex attendue : {instance.regex_reconnaissance}")
        match = re.search(instance.regex_reconnaissance, texte_page)
        #print(f"Résultat du match : {match}")
        if match:
            format_trouve = instance
            break

    try:
        format_resultat = format_trouve.format
        fournisseur_resultat = format_trouve.format

        #print(f"Format trouvé : {format_resultat}, Fournisseur : {fournisseur_resultat}")
        return format_resultat, fournisseur_resultat
    except AttributeError:
        #print("Aucun format trouvé.")
        return None


def extraire_date(format, texte):

    date_formatee = None
    texte = texte.replace("\n", " ").strip()

    try:
        regex_date = re.compile(Format_facture.objects.get(pk=format).regex_date)

        # Recherche la date dans le texte
        if format != "AVOIR REMISES CERP":
            match = re.search(regex_date, texte)
        else:
            match = re.search(regex_date, texte.replace(" ", ""))
        
        if match:
            date_formatee = match.group(1).strip().replace(".","/").replace(" ","/")
        
        return date_formatee
    
    except Exception as e:
        print(f'Erreur extraction date : {e}')
        return None


def extraire_numero_facture(format, texte):

    texte = texte.replace("\n", " ").strip()

    try:
        regex_numero_facture = re.compile(Format_facture.objects.get(pk=format).regex_numero_facture)  

        # Recherche le numéro de facture dans le texte
        if format != "AVOIR REMISES CERP":
            match = re.search(regex_numero_facture, texte)
        else:
            match = re.search(regex_numero_facture, texte.replace(" ", ""))

        #print(match.group(1))
        return match.group(1) if match else None
    
    except Exception as e:
        print(f'Erreur extraction numéro facture : {e}')
        return None
    

def listevide(liste):
    estvide = True
    for i in range(len(liste)):
        if liste[i] != None and liste[i] != "":
            estvide = False

    return estvide


def pre_traitement_table(format_facture: Format_facture, table_principale):
    table_sans_lignes_vides = []
    table_pretraitee = []
    i = 0

    if format_facture.format == "TEVA" or format_facture.format == "AVOIR TEVA":
        table_sans_lignes_vides = [i for i in table_principale if not listevide(i)]
        for ligne in table_sans_lignes_vides:
            if ligne[0] != "" and ligne[0] != None and ligne[1] != "" and ligne[1] != None:
                if ligne[0] != "Désignation":
                    #on est dans le bloc produit
                    table_pretraitee.append([
                        ligne[0], 
                        ligne[1]
                    ])
            elif ligne[0] == "" and ligne[1] is None:
                #print(ligne)
                #on est dans le bloc ventes
                table_pretraitee[i].extend([
                    ligne[2],
                    ligne[3],
                    ligne[4],
                    ligne[5],
                    ligne[7],
                    ligne[6]
                ])
                i += 1

        #print(table_pretraitee)

    return table_pretraitee


def correspondance_tva_cerp(indice):
    match indice * 100:
        case 1:
            return 0.055
        case 2:
            return 0.1
        case 3:
            return 0.2
        case 4:
            return 0.021
        case 5:
            return 0

def process_tables(format, tables_page):    
    #try:
        processed_table = []
        table_principale = []
        ligne_sans_none = []
        events = []
        i = 0

        format_facture = Format_facture.objects.get(pk=format)

        if format_facture.reconnaissance_table_ppale != "":
            # la reconnaissance de table ppale est une liste de 3 éléments : [0,0,"DATE par ex
            recotable = json.loads(format_facture.reconnaissance_table_ppale)
            
            for table in tables_page:
                try:
                    if table[recotable[0]][recotable[1]] == recotable[2]:
                        table_principale = table
                except:
                    continue

            if format_facture.pre_traitement:
                table_principale = pre_traitement_table(format_facture, table_principale)

            for ligne in range(len(table_principale)):
                ligne_sans_none = [i for i in table_principale[ligne] if i != "None" and i != None]
                if re.match(re.compile(format_facture.regex_ligne_table), ligne_sans_none[0]):

                        donnees_ligne = []
                        multiplicateur = 1 if format_facture.format != "AVOIR CERP" else -1
                        multiplicateur_teva = 1 if format_facture.format != "AVOIR TEVA" else -1

                        try:

                            if format_facture.indice_code_produit != -1:
                                code = ligne_sans_none[format_facture.indice_code_produit]
                                donnees_ligne.append(''.join(caractere for caractere in code if not caractere.isalpha() and not caractere.isspace()))
                            else: donnees_ligne.append("")

                            if format_facture.indice_designation != -1:
                                donnees_ligne.append(ligne_sans_none[format_facture.indice_designation])
                            else: donnees_ligne.append("")

                            if format_facture.indice_nb_boites != -1:
                                if ligne_sans_none[format_facture.indice_nb_boites] != "":
                                    donnees_ligne.append(multiplicateur_teva * int(ligne_sans_none[format_facture.indice_nb_boites]))
                                else: donnees_ligne.append(0)
                            else: donnees_ligne.append(0)

                            if format_facture.indice_prix_unitaire_ht != -1:
                                if ligne_sans_none[format_facture.indice_prix_unitaire_ht] != "":
                                    donnees_ligne.append(multiplicateur * float(ligne_sans_none[format_facture.indice_prix_unitaire_ht].replace(",",".").replace(" ","")))
                                else: donnees_ligne.append(0)
                            else: donnees_ligne.append(0)

                            if format_facture.indice_prix_unitaire_remise_ht != -1:
                                if ligne_sans_none[format_facture.indice_prix_unitaire_remise_ht] != "":
                                    donnees_ligne.append(multiplicateur * float(ligne_sans_none[format_facture.indice_prix_unitaire_remise_ht].replace(",",".").replace(" ","")))
                                else: donnees_ligne.append(0)
                            else: donnees_ligne.append(0)

                            if format_facture.indice_remise_pourcent != -1:
                                if ligne_sans_none[format_facture.indice_remise_pourcent] != "":
                                    if float(ligne_sans_none[format_facture.indice_remise_pourcent].replace(",",".").replace(" ","").replace("%","")) <= 1:
                                        donnees_ligne.append(float(ligne_sans_none[format_facture.indice_remise_pourcent].replace(",",".").replace(" ","").replace("%","")))
                                    else:
                                        donnees_ligne.append(float(ligne_sans_none[format_facture.indice_remise_pourcent].replace(",",".").replace(" ","").replace("%","")) / 100)
                                else: donnees_ligne.append(0)
                            else: donnees_ligne.append(0)

                            if format_facture.indice_montant_ht_hors_remise != -1:
                                if ligne_sans_none[format_facture.indice_montant_ht_hors_remise] != "":
                                    donnees_ligne.append(multiplicateur * float(ligne_sans_none[format_facture.indice_montant_ht_hors_remise].replace(",",".").replace(" ","")))
                                else: donnees_ligne.append(0)
                            else: 
                                donnees_ligne.append(multiplicateur * float(ligne_sans_none[format_facture.indice_prix_unitaire_ht].replace(",",".").replace(" ","")) * int(ligne_sans_none[format_facture.indice_nb_boites]))

                            if format_facture.indice_montant_ht != -1:
                                if ligne_sans_none[format_facture.indice_montant_ht] != "":
                                    donnees_ligne.append(multiplicateur * float(ligne_sans_none[format_facture.indice_montant_ht].replace(",",".").replace(" ","")))
                                else: donnees_ligne.append(0)
                            else: donnees_ligne.append(0)

                            if format_facture.indice_tva != -1:
                                tva = ligne_sans_none[format_facture.indice_tva]
                                tva = float(tva.replace(",",".").replace(" ","").replace("%","")) / 100

                                if tva == 0.021 or tva == 0.055 or tva == 0.1 or tva == 0.2:
                                    donnees_ligne.append(tva)
                                elif tva == 0.01 or tva == 0.02 or tva == 0.03 or tva == 0.04 or tva == 0.05:
                                    donnees_ligne.append(correspondance_tva_cerp(tva))
                                else: donnees_ligne.append(0)
                            else: donnees_ligne.append(0)

                            # for donnee in donnees_ligne:
                            #     print(donnee)

                            processed_table.append(donnees_ligne)
                            i+=1

                        except Exception as e:
                            events.append(f"Erreur lors du traitement du produit {ligne_sans_none[format_facture.indice_code_produit]} - Erreur {e}")
                            continue

        return processed_table, events
    
    #except:
        return None


def process_avoir_remises(format, tables_page, numero, date):
    success = True
    
    format_facture = Format_facture.objects.get(pk=format)
    table_principale = []
    specialites_pharmaceutiques = Decimal(0)
    lpp = Decimal(0)
    parapharmacie = Decimal(0)
    avantage_commercial = Decimal(0)
    total = Decimal(0)

    # la reconnaissance de table ppale est une liste de 3 éléments : [0,0,"DATE par ex
    recotable = json.loads(format_facture.reconnaissance_table_ppale)

    try:
        for table in tables_page:
            try:
                if table[recotable[0]][recotable[1]] == recotable[2]:
                    table_principale = table
            except Exception as e:
                continue

        if table_principale == []:
            logger.error(f"Table principale introuvable, avoir de remises {numero} émis le {date} : {e}")
        else:
            for i in range(len(table_principale)):
                if "Spécialités Pharmaceutiques" in table_principale[i][0]:
                    specialites_pharmaceutiques = Decimal(float(table_principale[i][2].replace(" ", "").replace(",", ".")))
                elif "LPP" in table_principale[i][0]:
                    lpp = Decimal(float(table_principale[i][2].replace(" ", "").replace(",", ".")))
                elif "Parapharmacie" in table_principale[i][0]:
                    parapharmacie = Decimal(float(table_principale[i][2].replace(" ", "").replace(",", ".")))
                elif "Avantage Commercial" in table_principale[i][0]:
                    avantage_commercial = Decimal(float(table_principale[i][2].replace(" ", "").replace(",", ".")))

            total = specialites_pharmaceutiques + lpp + parapharmacie + avantage_commercial

            date_mois_concerne = date.replace(day=1) - timedelta(days=1)
            mois_concerne = f"{date_mois_concerne.month}/{date_mois_concerne.year}"

            nouvel_avoir = Avoir_remises(
                    numero = numero,
                    date = date,
                    mois_concerne = mois_concerne,
                    specialites_pharmaceutiques = specialites_pharmaceutiques,
                    lpp = lpp,
                    parapharmacie = parapharmacie,
                    avantage_commercial = avantage_commercial,
                    total = total,
                )
            
            nouvel_avoir.save()

    except Exception as e:
        logger.error(f"Erreur de traitement de l'avoir de remises {numero} émis le {date} : {e}")
        success = False
    
    return success


def choix_remise_grossiste(produit: Produit_catalogue, categorie, nb_boites):
    remise = 0

    if categorie == "<450€ tva 2,1%" or categorie == "LPP" or categorie == "PARAPHARMACIE":
        #2,5 % de remise sur le HT puis un avantage commercial qui correspond à la différence avec la remise obtenue si a 3,80 %
        remise = 0.038
    elif categorie == ">450€ <1500€ tva 2,1%":
        #ici remise en € par boîte
        remise = nb_boites * 15
    elif categorie == ">1500€ tva 2,1%":
        remise = 0

    return remise


def extraire_produits(format, fournisseur, tables_page):
    produits = []
    table_principale = []
    ligne_sans_none = []
    listes_deja_ajoutees = set()
    valeurs_souhaitees = []
    i = 0

    match format:
        case "PHARMAT":
            for table in tables_page:
                if table[0][0] == "DATE":
                    table_principale = table

            for ligne in range(len(table_principale)):
                ligne_sans_none = [i for i in table_principale[ligne] if i != "None" and i != None]
                if re.match(r'\d{1,2} \d{2} \d{2,4}', ligne_sans_none[0]):
                    valeurs_souhaitees = [
                        ligne_sans_none[2],
                        ligne_sans_none[1],
                        ligne_sans_none[5],
                        0.00,
                        fournisseur
                        ]
                    tuple_liste = tuple(valeurs_souhaitees)
                    if tuple_liste not in listes_deja_ajoutees:
                        produits.append(valeurs_souhaitees)
                        listes_deja_ajoutees.add(tuple_liste)
                        i+=1
        case "CERP":
            for table in tables_page:
                if table[2][0] == "Code":
                    table_principale = table

            for ligne in range(len(table_principale)):
                ligne_sans_none = [i for i in table_principale[ligne] if i != "None" and i != None]
                if re.match(r'\d{10,20}', ligne_sans_none[0]):
                    valeurs_souhaitees = [
                        ligne_sans_none[0],
                        ligne_sans_none[1],
                        ligne_sans_none[3],
                        ligne_sans_none[4],
                        fournisseur
                        ]
                    tuple_liste = tuple(valeurs_souhaitees)
                    if tuple_liste not in listes_deja_ajoutees:
                        produits.append(valeurs_souhaitees)
                        listes_deja_ajoutees.add(tuple_liste)
                        i+=1

    return produits


def categoriser_achat(designation, fournisseur, tva, prix_unitaire_ht, remise_pourcent, coalia, generique, marche_produits, pharmupp, lpp):
    new_categorie = ""
    
    try:
        if fournisseur == "CERP COALIA":
            new_categorie = "COALIA"
        elif fournisseur == "CERP PHARMAT" or fournisseur == "PHARMAT" :
            new_categorie = "PHARMAT"
        elif "CERP" in fournisseur:
            if generique or any(element in designation.upper() for element in LABORATOIRES_GENERIQUES):
                if (tva > 0.0209 and tva < 0.0211):
                    new_categorie = "GENERIQUE 2,1%"
                elif tva > 0.0211:
                    new_categorie = "GENERIQUE AUTRE"
                else:
                    new_categorie = "PROBLEME TVA GENERIQUE"
            elif marche_produits or any(element in designation.upper() for element in MARCHES_PRODUITS):
                new_categorie = "MARCHE PRODUITS"
            elif coalia or pharmupp:
                new_categorie = "UPP"
            elif lpp:
                if (tva > 0.0549 and tva < 0.0551) or (tva > 0.099 and tva < 0.101):
                    new_categorie = "LPP 5,5 OU 10%"
                elif tva > 0.199 and tva < 0.201:
                    new_categorie = "LPP 20%"
                else:
                    new_categorie = "PROBLEME TVA LPP"
            elif remise_pourcent > 0:
                new_categorie = "REMISE SUR FACTURE"
            elif (tva > 0.0209 and tva < 0.0211) and prix_unitaire_ht < 450:
                new_categorie = "<450€ tva 2,1%"
            elif (tva > 0.0209 and tva < 0.0211) and prix_unitaire_ht >= 450:
                new_categorie = ">450€ tva 2,1%"
            elif (tva > 0.0549 and tva < 0.0551) or (tva > 0.099 and tva < 0.101):
                new_categorie = "NON CATEGORISE CERP 5,5 OU 10"
            elif tva > 0.199 and tva < 0.201:
                new_categorie = "PARAPHARMACIE"
            else:
                new_categorie = "NON CATEGORISE CERP"
        elif "TEVA" in fournisseur or fournisseur == "EG" or fournisseur == "BIOGARAN"  or fournisseur == "ARROW" :
            if remise_pourcent > 0 or any(element in designation.upper() for element in NON_GENERIQUES):
                new_categorie = "NON GENERIQUE DIRECT LABO"
            elif (tva > 0.0209 and tva < 0.0211):
                new_categorie = "GENERIQUE 2,1%"
            elif tva > 0.0211:
                new_categorie = "GENERIQUE AUTRE"
            else:
                new_categorie = "GENERIQUE PROBLEME TVA"
        else:
            new_categorie = "NON CATEGORISE"

    except Exception as e:
        logger.error(f'L\'achat du produit {designation} avec remise pourcent {remise_pourcent} n\'a pas été catégorisé : {e}')
        new_categorie = "NON CATEGORISE ERREUR"

    return new_categorie


def calculer_remise_theorique(produit: Produit_catalogue, nouvel_achat: Achat):

    remise = 0

    try:
        if nouvel_achat.categorie == "COALIA":
            if produit.remise_direct:
                for r in json.loads(produit.remise_direct):
                    if nouvel_achat.nb_boites >= r[0]:
                        remise = r[1]
                nouvel_achat.remise_theorique_totale = round(Decimal(nouvel_achat.montant_ht_hors_remise) * Decimal(remise), 4)
        if nouvel_achat.categorie == "PHARMAT":
            #Cas particulier Pharmat car pas de remises catalogue
            if nouvel_achat.remise_pourcent != 0:
                nouvel_achat.remise_theorique_totale = round(Decimal(nouvel_achat.montant_ht_hors_remise) * Decimal(nouvel_achat.remise_pourcent), 4)
        elif "CERP" not in nouvel_achat.fournisseur and nouvel_achat.categorie.split()[0].upper() == "GENERIQUE":
            #GENERIQUE NON CERP donc en direct
            if produit.remise_direct:
                for r in json.loads(produit.remise_direct):
                    if nouvel_achat.nb_boites >= r[0]:
                        remise = r[1]
                nouvel_achat.remise_theorique_totale = round(Decimal(nouvel_achat.montant_ht_hors_remise) * Decimal(remise), 4)
        elif "CERP" in nouvel_achat.fournisseur and nouvel_achat.categorie.split()[0].upper() == "GENERIQUE":
            #GENERIQUE CERP
            if produit.remise_grossiste:
                for r in json.loads(produit.remise_grossiste):
                    if nouvel_achat.nb_boites >= r[0]:
                        remise = r[1]
                nouvel_achat.remise_theorique_totale = round(Decimal(nouvel_achat.montant_ht_hors_remise) * Decimal(remise), 4)
        else:
            #UPP, CERP, LPP, PARAPHARMA
            #TRANCHES D'€ SEULEMENT SI PAS PARAPHARMA, UPP ou LPP
            if nouvel_achat.categorie == "UPP" or nouvel_achat.categorie == "MARCHE PRODUITS":
                #Si upp, remise grossiste si existante, sinon 0 par défaut
                if produit.remise_grossiste:
                    for r in json.loads(produit.remise_grossiste):
                        if nouvel_achat.nb_boites >= r[0]:
                            remise = r[1]
                    nouvel_achat.remise_theorique_totale = round(Decimal(nouvel_achat.montant_ht_hors_remise) * Decimal(remise), 4)
            else:
                remise = choix_remise_grossiste(produit, nouvel_achat.categorie, nouvel_achat.nb_boites)
                if remise < 1:
                    #remise classique en %
                    nouvel_achat.remise_theorique_totale = round(Decimal(nouvel_achat.montant_ht_hors_remise) * Decimal(remise), 4)
                else:
                    #remise en €
                    nouvel_achat.remise_theorique_totale = round(Decimal(remise), 4)

    except Exception as e:
        logger.error(f'remise théorique non calculée pour l\'achat {nouvel_achat.produit} du {nouvel_achat.date} : {e}')
        
    return nouvel_achat


def determiner_fournisseur_generique(designation, fournisseur=None):

    new_fournisseur_generique = ""

    if fournisseur is not None:
        if fournisseur == "TEVA" or fournisseur == "EG" or fournisseur == "BIOGARAN"  or fournisseur == "ARROW" :
            new_fournisseur_generique = fournisseur
    
    if new_fournisseur_generique == "":
        if any(element in designation.upper() for element in LABORATOIRES_GENERIQUES):
            for element in LABORATOIRES_GENERIQUES:
                if element in designation.upper():
                    if element == "BIOG" or element == "BGR ":
                        new_fournisseur_generique = "BIOGARAN"
                    elif element == "SDZ " or element == "SAND ":
                        new_fournisseur_generique = "SANDOZ"
                    elif element == "ZTV " or element == "ZENT ":
                        new_fournisseur_generique = "ZENTIVA"
                    elif element == " LEG " or element == " EG ":
                        new_fournisseur_generique = "EG"
                    elif element == "ARW":
                        new_fournisseur_generique = "ARROW"
                    else:
                        new_fournisseur_generique = element.strip()

    return new_fournisseur_generique


def convert_date(date_str):
    return datetime.strptime(date_str, "%m/%Y")


def quicksort_tableau(list_of_lists):
    if len(list_of_lists) <= 1:
        return list_of_lists
    else:
        pivot = list_of_lists[0]
        pivot_date = convert_date(pivot[0])
        less = [x for x in list_of_lists[1:] if convert_date(x[0]) < pivot_date]
        greater = [x for x in list_of_lists[1:] if convert_date(x[0]) >= pivot_date]
        return quicksort_tableau(less) + [pivot] + quicksort_tableau(greater)
    

def supprimer_fichiers_dossier(dossier, critere=""):
    fichiers = os.listdir(dossier)

    for fichier in fichiers:
        chemin_fichier = os.path.join(dossier, fichier)

        if os.path.isfile(chemin_fichier):
            if critere in chemin_fichier:
                os.remove(chemin_fichier)