import os
import re
import logging
from .models import Format_facture, Produit_catalogue, Achat, Avoir_remises, Avoir_ratrappage_teva, Releve_alliance, Releve_CERP
import json
from datetime import datetime, timedelta
import calendar
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
        return None, None


def extraire_date(format, texte):

    date_formatee = None
    texte = texte.replace("\n", " ").strip()

    try:
        regex_date = re.compile(Format_facture.objects.get(pk=format).regex_date)

        # Recherche la date dans le texte
        if "AVOIR REMISES CERP" in format:
            match = re.search(regex_date, texte.replace(" ", ""))
        elif format == "EG":
            regex_date = [
                re.compile(Format_facture.objects.get(pk=format).regex_date),
                r'datefacture/iNvoicedate:(\d{2}/\d{2}/\d{4})n°',
                r'DATE:(\d{2}/\d{2}/\d{4})CLIENT:'
            ]
            match = None
            i = 0
            while match is None and i < len(regex_date):
                match = re.search(regex_date[i], texte.replace(" ", ""))
                i += 1
        else:
            match = re.search(regex_date, texte)
                
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
        if "AVOIR REMISES CERP" in format:
            match = re.search(regex_numero_facture, texte.replace(" ", ""))
        elif format == "EG":
            regex_numero_facture = [
                re.compile(Format_facture.objects.get(pk=format).regex_numero_facture),
                r'fACTUre/Number:(.{1,15})PHARMACIE',
                r'PIECE:(.{1,15})thegeneralterms'
            ]
            match = None
            i = 0
            while match is None and i < len(regex_numero_facture):
                match = re.search(regex_numero_facture[i], texte.replace(" ", ""))
                i += 1
        else:
            match = re.search(regex_numero_facture, texte)

        #print(match.group(1))
        return match.group(1) if match else None
    
    except Exception as e:
        print(f'Erreur extraction numéro facture : {e}')
        return None
    

def listevide(liste):
    estvide = True
    for i in range(len(liste)):
        if liste[i] is not None and liste[i] != "":
            estvide = False

    return estvide


def pre_traitement_table(format_facture: Format_facture, table_principale):
    table_sans_lignes_vides = []
    table_pretraitee = []
    i = 0

    if format_facture.format == "TEVA" or format_facture.format == "AVOIR TEVA":
        table_sans_lignes_vides = [i for i in table_principale if not listevide(i)]
        for ligne in table_sans_lignes_vides:
            if ligne[0] != "" and ligne[0] is not None and ligne[1] != "" and ligne[1] is not None:
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

    return table_pretraitee


def correspondance_tva_cerp(indice):
    match indice:
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
                except:  # noqa: E722
                    continue

            if format_facture.pre_traitement:
                table_principale = pre_traitement_table(format_facture, table_principale)

            for ligne in range(len(table_principale)):
                ligne_sans_none = [i for i in table_principale[ligne] if i != "None" and i is not None]
                if re.match(re.compile(format_facture.regex_ligne_table), ligne_sans_none[0]):

                        donnees_ligne = []
                        multiplicateur = 1 if (format_facture.format != "AVOIR CERP" and format_facture.format != "AVOIR TEVA") else -1
                        multiplicateur_teva = 1 if format_facture.format != "AVOIR TEVA" else -1

                        try:

                            if format_facture.indice_code_produit != -1:
                                try:
                                    if len(ligne_sans_none[format_facture.indice_code_produit]) > 13:
                                        ligne_sans_none[format_facture.indice_designation] = str(ligne_sans_none[format_facture.indice_code_produit][14:]).replace(" ", "") + ligne_sans_none[format_facture.indice_designation]
                                        ligne_sans_none[format_facture.indice_code_produit] = str(ligne_sans_none[format_facture.indice_code_produit][0:13])
                                except Exception as e:
                                    logger.error(f"Erreur traitement spécial EG de cette ligne pour la désignation : {ligne_sans_none} - ERREUR : {e}")
                                    continue

                                code = ligne_sans_none[format_facture.indice_code_produit]
                                donnees_ligne.append(''.join(caractere for caractere in code if not caractere.isalpha() and not caractere.isspace()))
                            else: 
                                donnees_ligne.append("")

                            if format_facture.indice_designation != -1:
                                donnees_ligne.append(ligne_sans_none[format_facture.indice_designation])
                            else: 
                                donnees_ligne.append("")

                            if format_facture.indice_nb_boites != -1:
                                if ligne_sans_none[format_facture.indice_nb_boites] != "":
                                    donnees_ligne.append(multiplicateur * multiplicateur_teva * int(ligne_sans_none[format_facture.indice_nb_boites]))
                                else: 
                                    donnees_ligne.append(0)
                            else: 
                                donnees_ligne.append(0)

                            if format_facture.indice_prix_unitaire_ht != -1:
                                if ligne_sans_none[format_facture.indice_prix_unitaire_ht] != "":
                                    donnees_ligne.append(multiplicateur * float(ligne_sans_none[format_facture.indice_prix_unitaire_ht].replace(",",".").replace(" ","")))
                                else: 
                                    donnees_ligne.append(0)
                            else: 
                                donnees_ligne.append(0)

                            if format_facture.indice_prix_unitaire_remise_ht != -1:
                                if ligne_sans_none[format_facture.indice_prix_unitaire_remise_ht] != "":
                                    donnees_ligne.append(multiplicateur * float(ligne_sans_none[format_facture.indice_prix_unitaire_remise_ht].replace(",",".").replace(" ","")))
                                else: 
                                    donnees_ligne.append(0)
                            else: 
                                donnees_ligne.append(0)

                            if format_facture.indice_remise_pourcent != -1:
                                if ligne_sans_none[format_facture.indice_remise_pourcent] != "":
                                    if float(ligne_sans_none[format_facture.indice_remise_pourcent].replace(",",".").replace(" ","").replace("%","")) <= 1:
                                        donnees_ligne.append(float(ligne_sans_none[format_facture.indice_remise_pourcent].replace(",",".").replace(" ","").replace("%","")))
                                    else:
                                        donnees_ligne.append(float(ligne_sans_none[format_facture.indice_remise_pourcent].replace(",",".").replace(" ","").replace("%","")) / 100)
                                else:
                                    donnees_ligne.append(0)
                            elif ligne_sans_none[format_facture.indice_prix_unitaire_remise_ht] != "" and ligne_sans_none[format_facture.indice_prix_unitaire_ht] != "":
                                if float(ligne_sans_none[format_facture.indice_prix_unitaire_ht].replace(",",".").replace(" ","")) != 0:
                                    donnees_ligne.append(
                                        1 - (float(ligne_sans_none[format_facture.indice_prix_unitaire_remise_ht].replace(",",".").replace(" ","")) 
                                        / float(ligne_sans_none[format_facture.indice_prix_unitaire_ht].replace(",",".").replace(" ","")))
                                    )
                                else:
                                    donnees_ligne.append(0)
                            else:
                                donnees_ligne.append(0)

                            if format_facture.indice_montant_ht_hors_remise != -1:
                                if ligne_sans_none[format_facture.indice_montant_ht_hors_remise] != "":
                                    donnees_ligne.append(multiplicateur * float(ligne_sans_none[format_facture.indice_montant_ht_hors_remise].replace(",",".").replace(" ","")))
                                else: 
                                    donnees_ligne.append(0)
                            else: 
                                donnees_ligne.append(multiplicateur * float(ligne_sans_none[format_facture.indice_prix_unitaire_ht].replace(",",".").replace(" ","")) * int(ligne_sans_none[format_facture.indice_nb_boites]))

                            if format_facture.indice_montant_ht != -1 and format_facture.indice_tva != -1:
                                try:
                                    if format_facture.format == "EG":
                                        if " " in ligne_sans_none[format_facture.indice_montant_ht]:
                                            position = ligne_sans_none[format_facture.indice_montant_ht].find(" ")
                                            ligne_sans_none[format_facture.indice_tva] = str(ligne_sans_none[format_facture.indice_montant_ht][position:]).replace(" ", "") + ligne_sans_none[format_facture.indice_tva]
                                            ligne_sans_none[format_facture.indice_montant_ht] = str(ligne_sans_none[format_facture.indice_montant_ht][0:position])
                                except Exception as e:
                                    logger.error(f"Erreur traitement spécial EG de cette ligne pour la TVA : {ligne_sans_none} - ERREUR : {e}")
                                    continue

                            if format_facture.indice_montant_ht != -1:
                                if ligne_sans_none[format_facture.indice_montant_ht] != "":
                                    donnees_ligne.append(multiplicateur * float(ligne_sans_none[format_facture.indice_montant_ht].replace(",",".").replace(" ","")))
                                else: 
                                    donnees_ligne.append(0)
                            else: 
                                donnees_ligne.append(0)

                            if format_facture.indice_tva != -1:
                                tva = ligne_sans_none[format_facture.indice_tva]
                                tva = float(tva.replace(",",".").replace(" ","").replace("%","")) / 100

                                if tva == 0.021 or tva == 0.055 or tva == 0.1 or tva == 0.2:
                                    donnees_ligne.append(tva)
                                elif tva == 0.01 or tva == 0.02 or tva == 0.03 or tva == 0.04 or tva == 0.05:
                                    donnees_ligne.append(correspondance_tva_cerp(tva * 100))
                                else: 
                                    donnees_ligne.append(0)
                            else: 
                                donnees_ligne.append(0)

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

    specialites_pharmaceutiques_montant = Decimal(0)
    lpp_cinq_ou_dix_montant = Decimal(0)
    lpp_vingt_montant = Decimal(0)
    parapharmacie_montant = Decimal(0)
    total_montant = Decimal(0)

    specialites_pharmaceutiques_remise = Decimal(0)
    lpp_cinq_ou_dix_remise = Decimal(0)
    lpp_vingt_remise = Decimal(0)
    parapharmacie_remise = Decimal(0)
    avantage_commercial = Decimal(0)
    total_remise = Decimal(0)

    # la reconnaissance de table ppale est une liste de 3 éléments : [0,0,"DATE par ex
    recotable = json.loads(format_facture.reconnaissance_table_ppale)

    try:
        for table in tables_page:
            try:
                if table[recotable[0]][recotable[1]] == recotable[2]:
                    table_principale = table
            except:  # noqa: E722
                continue

        if table_principale == []:
            logger.error(f"Table principale introuvable, avoir de remises {numero} émis le {date}")
            success = False
        else:
            for i in range(len(table_principale)):
                if "Spécialités Pharmaceutiques" in table_principale[i][0]:
                    specialites_pharmaceutiques_montant = Decimal(float(table_principale[i][1].replace(" ", "").replace(",", ".")))
                    specialites_pharmaceutiques_remise = Decimal(float(table_principale[i][2].replace(" ", "").replace(",", ".")))
                elif "LPP" in table_principale[i][0] or table_principale[i][0] == "":
                    try:
                        tva = correspondance_tva_cerp(int(table_principale[i][3]))
                        if tva == 0.055 or tva == 0.1:
                            lpp_cinq_ou_dix_montant = Decimal(float(table_principale[i][1].replace(" ", "").replace(",", ".")))
                            lpp_cinq_ou_dix_remise = Decimal(float(table_principale[i][2].replace(" ", "").replace(",", ".")))
                        elif tva == 0.2:
                            lpp_vingt_montant = Decimal(float(table_principale[i][1].replace(" ", "").replace(",", ".")))
                            lpp_vingt_remise = Decimal(float(table_principale[i][2].replace(" ", "").replace(",", ".")))
                        else:
                            logger.error(f"Problème tva LPP sur avoir {numero} - {date}")
                            continue
                    except:  # noqa: E722
                        continue
                elif "Parapharmacie" in table_principale[i][0]:
                    parapharmacie_montant = Decimal(float(table_principale[i][1].replace(" ", "").replace(",", ".")))
                    parapharmacie_remise = Decimal(float(table_principale[i][2].replace(" ", "").replace(",", ".")))
                elif "Avantage Commercial" in table_principale[i][0]:
                    avantage_commercial = Decimal(float(table_principale[i][2].replace(" ", "").replace(",", ".")))

            total_montant = specialites_pharmaceutiques_montant + lpp_cinq_ou_dix_montant + lpp_vingt_montant + parapharmacie_montant
            total_remise = specialites_pharmaceutiques_remise + lpp_cinq_ou_dix_remise + lpp_vingt_remise + parapharmacie_remise + avantage_commercial

            date_mois_concerne = date.replace(day=1) - timedelta(days=1)
            mois_concerne = f"{date_mois_concerne.month}/{date_mois_concerne.year}"

            nouvel_avoir = Avoir_remises(
                    numero = numero,
                    date = date,
                    mois_concerne = mois_concerne,
                    specialites_pharmaceutiques_montant = specialites_pharmaceutiques_montant,
                    lpp_cinq_ou_dix_montant = lpp_cinq_ou_dix_montant,
                    lpp_vingt_montant = lpp_vingt_montant,
                    parapharmacie_montant = parapharmacie_montant,
                    total_montant = total_montant,
                    specialites_pharmaceutiques_remise = specialites_pharmaceutiques_remise,
                    lpp_cinq_ou_dix_remise = lpp_cinq_ou_dix_remise,
                    lpp_vingt_remise = lpp_vingt_remise,
                    parapharmacie_remise = parapharmacie_remise,
                    avantage_commercial = avantage_commercial,
                    total_remise = total_remise,
                )
            
            nouvel_avoir.save()

    except Exception as e:
        logger.error(f"Erreur de traitement de l'avoir de remises {numero} émis le {date} : {e}")
        success = False
    
    return success


def process_avoir_remises_deuxieme_page(format, tables_page, mois_concerne, date):
    success = True
    
    format_facture = Format_facture.objects.get(pk=format)
    table_principale = []
    avoirs_exceptionnels = Decimal(0)

    generiques_montant = Decimal(0)
    marche_produits_montant = Decimal(0)
    upp_montant = Decimal(0)
    autres_montant = Decimal(0)
    coalia_montant = Decimal(0)
    pharmat_montant = Decimal(0)

    generiques_remise = Decimal(0)
    marche_produits_remise = Decimal(0)
    upp_remise = Decimal(0)
    autres_remise = Decimal(0)
    coalia_remise = Decimal(0)
    pharmat_remise = Decimal(0)

    # la reconnaissance de table ppale est une liste de 3 éléments : [0,0,"DATE par ex
    recotable = json.loads(format_facture.reconnaissance_table_ppale)

    try:
        for table in tables_page:
            try:
                if table[recotable[0]][recotable[1]] == recotable[2]:
                    table_principale = table
            except:  # noqa: E722
                continue

        if table_principale == []:
            logger.error(f"Table principale introuvable, avoir de remises du {mois_concerne} émis le {date}")
            success = False
        else:
            for i in range(len(table_principale)):
                if "Avoirs Exceptionnels" in table_principale[i][0]:
                    avoirs_exceptionnels = Decimal(float(table_principale[i][2].replace(" ", "").replace(",", ".")))
                elif "Remises Génériques" in table_principale[i][0]:
                    generiques_montant = Decimal(float(table_principale[i][3].replace(" ", "").replace(",", ".")))
                    generiques_remise = Decimal(float(table_principale[i][2].replace(" ", "").replace(",", ".")))
                elif "Remises Marchés-Produits" in table_principale[i][0]:
                    marche_produits_montant = Decimal(float(table_principale[i][3].replace(" ", "").replace(",", ".")))
                    marche_produits_remise = Decimal(float(table_principale[i][2].replace(" ", "").replace(",", ".")))
                elif "Remises Marchés Groupement UPP" in table_principale[i][0]:
                    upp_montant = Decimal(float(table_principale[i][3].replace(" ", "").replace(",", ".")))
                    upp_remise = Decimal(float(table_principale[i][2].replace(" ", "").replace(",", ".")))
                elif "Remises Autres" in table_principale[i][0]:
                    if "-" not in table_principale[i][3].replace(" ", "").replace(",", "."):
                        autres_montant = Decimal(float(table_principale[i][3].replace(" ", "").replace(",", ".")))
                    else:
                        autres_montant = Decimal(-1) * Decimal(float(table_principale[i][3].replace(" ", "").replace(",", ".").replace("-", "")))
                    if "-" not in table_principale[i][2].replace(" ", "").replace(",", "."):
                        autres_remise = Decimal(float(table_principale[i][2].replace(" ", "").replace(",", ".")))
                    else:
                        autres_remise = Decimal(-1) * Decimal(float(table_principale[i][2].replace(" ", "").replace(",", ".").replace("-", "")))
                elif "Remises Coalia" in table_principale[i][0]:
                    coalia_montant = Decimal(float(table_principale[i][3].replace(" ", "").replace(",", ".")))
                    coalia_remise = Decimal(float(table_principale[i][2].replace(" ", "").replace(",", ".")))
                elif "Remises Pharmat" in table_principale[i][0]:
                    pharmat_montant = Decimal(float(table_principale[i][3].replace(" ", "").replace(",", ".")))
                    pharmat_remise = Decimal(float(table_principale[i][2].replace(" ", "").replace(",", ".")))

            try:
                avoir = Avoir_remises.objects.get(mois_concerne=mois_concerne)
                avoir.avoirs_exceptionnels = avoirs_exceptionnels
                avoir.generiques_montant = generiques_montant
                avoir.marche_produits_montant = marche_produits_montant
                avoir.upp_montant = upp_montant
                avoir.autres_montant = autres_montant
                avoir.coalia_montant = coalia_montant
                avoir.pharmat_montant = pharmat_montant
                avoir.generiques_remise = generiques_remise
                avoir.marche_produits_remise = marche_produits_remise
                avoir.upp_remise = upp_remise
                avoir.autres_remise = autres_remise
                avoir.coalia_remise = coalia_remise
                avoir.pharmat_remise = pharmat_remise
                avoir.save()

            except Exception as e:
                logger.error(f"Erreur lors de l'importation de l'avoir concerné par la page 2 du mois {mois_concerne} émis le {date} : {e}")
                success = False

    except Exception as e:
        logger.error(f"Erreur de traitement de l'avoir de remises page 2 {mois_concerne} émis le {date} : {e}")
        success = False
    
    return success


def process_ratrappage_teva(format, tables_page, texte_page, numero, date):
    success = True
    
    format_facture = Format_facture.objects.get(pk=format)
    table_principale = []
    montant_ratrappage = Decimal(0)
    regex_mois = r'via le Direct au titre de la période du\s(\d{2}/\d{2}/\d{4})'
    texte_page = texte_page.replace("\n", " ").strip()

    # la reconnaissance de table ppale est une liste de 3 éléments : [0,0,"DATE par ex
    recotable = json.loads(format_facture.reconnaissance_table_ppale)

    try:
        for table in tables_page:
            try:
                if table[recotable[0]][recotable[1]] == recotable[2]:
                    table_principale = table
            except:  # noqa: E722
                continue

        if table_principale == []:
            logger.error(f"Table principale introuvable, avoir de ratrappage teva {numero} émis le {date}")
            success = False
        else:
            for i in range(len(table_principale)):
                if re.match(re.compile(format_facture.regex_ligne_table), table_principale[i][0]):
                    montant_ratrappage += Decimal(float(table_principale[i][1].replace(" ", "").replace(",", ".")))

            match = re.search(regex_mois, texte_page)
            if match:
                date_mois_concerne = datetime.strptime(match.group(1), '%d/%m/%Y').date()
                date_mois_concerne = date_mois_concerne.replace(day=1)
                mois_concerne = f"{date_mois_concerne.month}/{date_mois_concerne.year}"

                nouvel_avoir = Avoir_ratrappage_teva(
                        numero = numero,
                        date = date,
                        mois_concerne = mois_concerne,
                        montant_ratrappage = montant_ratrappage
                    )
                
                nouvel_avoir.save()

            else:
                logger.error("Date non trouvée dans l'avoir de ratrappage.")
                success = False

    except Exception as e:
        logger.error(f"Erreur de traitement de l'avoir de remises {numero} émis le {date} : {e}")
        success = False

    return success


def process_releve_alliance(texte_page, numero, date):
    success = True

    texte_page = texte_page.replace("\n", " ").strip()

    try:

        releve_alliance, created = Releve_alliance.objects.get_or_create(numero = numero, date = date)

        if created:
            releve_alliance.net_a_payer = Decimal(0)
            releve_alliance.montant_grossiste = Decimal(0)
            releve_alliance.montant_short_list = Decimal(0)
        
        regex = r'Net\s*à\s*payer\s*\|*I*l*\s*(-*\d{1,5},\d{1,2})'
        match = re.search(regex, texte_page)
        if match:
            releve_alliance.net_a_payer = float(match.group(1).replace(",","."))

        regex = r'EN REGLEMENT DU PRESENT RELEVE NOUS AVONS ETABLI\s*UNE\s*LCR\s*DE\s*EUROS\s*(-*\d{1,5},\d{1,2})\s*A\s*ECHEANCE\s*DU\s*\d{1,2}\.\d{2}\.\d{2}'
        match = re.search(regex, texte_page)
        if match:
            releve_alliance.montant_grossiste = float(match.group(1).replace(",","."))

        regex = r'EN REGLEMENT DU PRESENT RELEVE NOUS AVONS ETABLI\s*UNE\s*LCR\s*DE\s*EUROS\s*-*\d{1,5},\d{1,2}\s*A\s*ECHEANCE\s*DU\s*(\d{1,2}\.\d{2}\.\d{2})'
        match = re.search(regex, texte_page)
        if match:
            releve_alliance.echeance_grossiste = datetime.strptime(match.group(1), "%d.%m.%y")

        regex = r'ET\s*UNE\s*LCR\s*DE\s*EUROS\s*(-*\d{1,5},\d{1,2})\s*A\s*ECHEANCE\s*DU\s*\d{1,2}\.\d{2}\.\d{2}'
        match = re.search(regex, texte_page)
        if match:
            releve_alliance.montant_short_list = float(match.group(1).replace(",","."))

        regex = r'ET\s*UNE\s*LCR\s*DE\s*EUROS\s*-*\d{1,5},\d{1,2}\s*A\s*ECHEANCE\s*DU\s*(\d{1,2}\.\d{2}\.\d{2})'
        match = re.search(regex, texte_page)
        if match:
            releve_alliance.echeance_short_list = datetime.strptime(match.group(1), "%d.%m.%y")

        regex = r'Total avantages commerciaux (-*\d{1,5},\d{1,2})'
        match = re.search(regex, texte_page)
        if match:
            releve_alliance.avantages_commerciaux = float(match.group(1).replace(",","."))

        regex = r'Total frais généraux (-*\d{1,5},\d{1,2})'
        match = re.search(regex, texte_page)
        if match:
            releve_alliance.frais_generaux = float(match.group(1).replace(",","."))

        regex = r'Facturation services - récapitulatif du mois.*Total (-*\d{1,5},\d{1,2})'
        match = re.search(regex, texte_page)
        if match:
            releve_alliance.facturation_services = float(match.group(1).replace(",","."))

        releve_alliance.save()

        if not releve_alliance.net_a_payer > Decimal(0) and (releve_alliance.montant_grossiste > Decimal(0) or releve_alliance.montant_short_list > Decimal(0)):
            releve_alliance.net_a_payer = releve_alliance.montant_grossiste + releve_alliance.montant_short_list

    except Exception as e:
        logger.error(f"Erreur de traitement du relevé Alliance {numero} émis le {date} : {e}")
        success = False

    return success


def process_releve_cerp(texte_page, numero, date):
    success = True

    texte_page = texte_page.replace("\n", " ").strip()

    try:
        releve_cerp, created = Releve_CERP.objects.get_or_create(numero = numero, date = date)
        
        if created:
            releve_cerp.total_ttc = Decimal(0)
        
        regex = r'Arrêté au (\d{2}/\d{2}/\d{4})'
        match = re.search(regex, texte_page)
        if match:
            releve_cerp.huitaine = datetime.strptime(match.group(1), "%d/%m/%Y")
            print(releve_cerp.huitaine)

        regex = r'\d{2}/\d{2}/\d{4}(-*\d{1,5},\d{1,2})€VentilationpartauxdeT.V.A'
        match = re.search(regex, texte_page.replace(" ", ""))
        if match:
            releve_cerp.total_ttc = float(match.group(1).replace(",","."))

        releve_cerp.save()

    except Exception as e:
        logger.error(f"Erreur de traitement du relevé CERP {numero} émis le {date} : {e}")
        success = False

    return success


def choix_remise_grossiste(produit: Produit_catalogue, categorie, nb_boites):
    remise = 0

    if categorie == "<450€ tva 2,1%" or "LPP" in categorie or categorie == "PARAPHARMACIE":
        #2,5 % de remise sur le HT puis un avantage commercial qui correspond à la différence avec la remise obtenue si a 3,80 %
        remise = 0.038
    elif categorie == ">450€ tva 2,1%":
        #ici remise en € par boîte
        remise = nb_boites * 15

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
                ligne_sans_none = [i for i in table_principale[ligne] if i != "None" and i is not None]
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
                ligne_sans_none = [i for i in table_principale[ligne] if i != "None" and i is not None]
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


def determiner_fournisseur_generique(designation, fournisseur=None):
    from .constants import LABORATOIRES_GENERIQUES

    new_fournisseur_generique = None

    if fournisseur is not None:
        if fournisseur == "TEVA" or fournisseur == "EG" or fournisseur == "BIOGARAN"  or fournisseur == "ARROW" :
            new_fournisseur_generique = fournisseur
    
    if new_fournisseur_generique is None:
        if any(element in designation.upper() for element in LABORATOIRES_GENERIQUES):
            for element in LABORATOIRES_GENERIQUES:
                if element in designation.upper():
                    if element == "BIOG" or element == "BGR ":
                        new_fournisseur_generique = "BIOGARAN"
                    elif element == "SDZ " or element == "SAND ":
                        new_fournisseur_generique = "SANDOZ"
                    elif element == "ZTV " or element == "ZENT ":
                        new_fournisseur_generique = "ZENTIVA"
                    elif element == " EG ":
                        new_fournisseur_generique = "EG"
                    elif element == "ARW":
                        new_fournisseur_generique = "ARROW"
                    elif element == "MYLAN":
                        new_fournisseur_generique = "VIATRIS"
                    elif element == " TS ":
                        new_fournisseur_generique = "TEVA"
                    else:
                        new_fournisseur_generique = element.replace(" ", "")

    return new_fournisseur_generique


def determiner_type(designation):
    from .constants import MARCHES_PRODUITS, LABORATOIRES_GENERIQUES, NON_GENERIQUES

    new_type = None

    if any(element in designation.upper() for element in MARCHES_PRODUITS):
        new_type = "MARCHE PRODUITS"
    elif any(element in designation.upper() for element in LABORATOIRES_GENERIQUES):
        if any(element in designation.upper() for element in NON_GENERIQUES):
            new_type = ""
        else:
            new_type = "GENERIQUE"
    
    return new_type


def categoriser_achat(designation, fournisseur, tva, prix_unitaire_ht, remise_pourcent, coalia, generique, marche_produits, pharmupp, lpp):
    from .constants import LABORATOIRES_GENERIQUES, MARCHES_PRODUITS, NON_GENERIQUES, NON_REMBOURSABLES, OTC, SPECIAL_CASES
    
    new_categorie = ""
    
    try:
        if fournisseur == "CERP COALIA":
            new_categorie = "COALIA"
        elif fournisseur == "CERP PHARMAT" or fournisseur == "PHARMAT" :
            new_categorie = "PHARMAT"
        elif "CERP" in fournisseur:
            if "MAGASIN GENERAL" in fournisseur:
                new_categorie = "MAGASIN GENERAL"
            elif any(element in designation.upper() for element in NON_GENERIQUES):
                new_categorie = "NON GENERIQUE GROSSISTE"
            elif any(element in designation.upper() for element in NON_REMBOURSABLES):
                new_categorie = "NON REMBOURSABLE GROSSISTE"
            elif any(element in designation.upper() for element in OTC):
                new_categorie = "OTC GROSSISTE"
            elif (generique or any(element in designation.upper() for element in LABORATOIRES_GENERIQUES)):
                if (tva > 0.0209 and tva < 0.0211):
                    new_categorie = "GENERIQUE 2,1%"
                elif (tva > 0.0549 and tva < 0.0551):
                    new_categorie = "GENERIQUE 5,5%"
                elif (tva > 0.099 and tva < 0.101):
                    new_categorie = "GENERIQUE 10%"
                elif (tva > 0.199 and tva < 0.201):
                    new_categorie = "GENERIQUE 20%"
                else:
                    new_categorie = "PROBLEME TVA GENERIQUE GROSSISTE"
            elif marche_produits or any(element in designation.upper() for element in MARCHES_PRODUITS):
                new_categorie = "MARCHE PRODUITS"
            elif lpp:
                if (tva > 0.0549 and tva < 0.0551) or (tva > 0.099 and tva < 0.101):
                    new_categorie = "LPP 5,5 OU 10%"
                elif (tva > 0.199 and tva < 0.201):
                    new_categorie = "LPP 20%"
                else:
                    new_categorie = "PROBLEME TVA LPP"
            #UPP doit être après LPP
            elif coalia or pharmupp:
                new_categorie = "UPP"
            elif remise_pourcent > 0:
                new_categorie = "REMISE SUR FACTURE"
            elif (tva > 0.0209 and tva < 0.0211) and abs(prix_unitaire_ht) < 450:
                new_categorie = "<450€ tva 2,1%"
            elif (tva > 0.0209 and tva < 0.0211) and abs(prix_unitaire_ht) >= 450:
                new_categorie = ">450€ tva 2,1%"
            elif (tva > 0.0549 and tva < 0.0551) or (tva > 0.099 and tva < 0.101):
                new_categorie = "NON CATEGORISE CERP 5,5 OU 10"
            elif (tva > 0.199 and tva < 0.201):
                new_categorie = "PARAPHARMACIE"
            else:
                new_categorie = "NON CATEGORISE CERP"
        elif "TEVA" in fournisseur or fournisseur == "EG" or fournisseur == "BIOGARAN"  or fournisseur == "ARROW" :
            if any(element in designation.upper() for element in NON_GENERIQUES):
                new_categorie = "NON GENERIQUE DIRECT LABO"
            elif any(element in designation.upper() for element in NON_REMBOURSABLES):
                new_categorie = "NON REMBOURSABLE DIRECT LABO"
            elif any(element in designation.upper() for element in OTC):
                new_categorie = "OTC DIRECT LABO"
            elif generique or any(element in designation.upper() for element in LABORATOIRES_GENERIQUES):
                if (tva > 0.0209 and tva < 0.0211):
                    new_categorie = "GENERIQUE 2,1%"
                elif (tva > 0.0549 and tva < 0.0551):
                    new_categorie = "GENERIQUE 5,5%"
                elif (tva > 0.099 and tva < 0.101):
                    new_categorie = "GENERIQUE 10%"
                elif (tva > 0.199 and tva < 0.201):
                    new_categorie = "GENERIQUE 20%"
                else:
                    new_categorie = "PROBLEME TVA GENERIQUE DIRECT"
            else:
                new_categorie = "NON CATEGORISE DIRECT"
        else:
            new_categorie = "NON CATEGORISE"

        for key in SPECIAL_CASES:
            if key in designation:
                new_categorie = SPECIAL_CASES[key]
                break

    except Exception as e:
        logger.error(f'L\'achat du produit {designation} avec remise pourcent {remise_pourcent} n\'a pas été catégorisé : {e}')
        new_categorie = "NON CATEGORISE ERREUR"

    return new_categorie


def get_categorie_remise(fournisseur_generique, fournisseur, remise_pourcent):
    new_categorie_remise = ""

    if fournisseur_generique == "TEVA" or fournisseur == "TEVA":
        if remise_pourcent > -0.001 and remise_pourcent < 0.001:
            new_categorie_remise = "TEVA REMISE 0%"
        elif remise_pourcent > 0.0249 and remise_pourcent < 0.0251:
            new_categorie_remise = "TEVA REMISE 2,5%"
        elif remise_pourcent > 0.099 and remise_pourcent < 0.101:
            new_categorie_remise = "TEVA REMISE 10%"
        elif remise_pourcent > 0.199 and remise_pourcent < 0.201:
            new_categorie_remise = "TEVA REMISE 20%"
        elif remise_pourcent > 0.299 and remise_pourcent < 0.301:
            new_categorie_remise = "TEVA REMISE 30%"
        elif remise_pourcent > 0.399 and remise_pourcent < 0.401:
            new_categorie_remise = "TEVA REMISE 40%"
        else:
            new_categorie_remise = "NON ELIGIBLE AU RATTRAPAGE"
    elif fournisseur_generique == "EG" or fournisseur == "EG":
        if remise_pourcent > -0.001 and remise_pourcent < 0.001:
            new_categorie_remise = "EG REMISE 0%"
        elif remise_pourcent > 0.0249 and remise_pourcent < 0.0251:
            new_categorie_remise = "EG REMISE 2,5%"
        elif remise_pourcent > 0.049 and remise_pourcent < 0.051:
            new_categorie_remise = "EG REMISE 5%"
        elif remise_pourcent > 0.099 and remise_pourcent < 0.101:
            new_categorie_remise = "EG REMISE 10%"
        elif remise_pourcent > 0.149 and remise_pourcent < 0.151:
            new_categorie_remise = "EG REMISE 15%"
        elif remise_pourcent > 0.199 and remise_pourcent < 0.201:
            new_categorie_remise = "EG REMISE 20%"
        elif remise_pourcent > 0.299 and remise_pourcent < 0.301:
            new_categorie_remise = "EG REMISE 30%"
        elif remise_pourcent > 0.399 and remise_pourcent < 0.401:
            new_categorie_remise = "EG REMISE 40%"
        else:
            new_categorie_remise = "EG REMISE NON LISTEE"

    return new_categorie_remise


def get_taux_avantage_commercial(mois_annee, total_cerp):
    mois_annee_date = datetime.strptime(mois_annee, "%m/%Y").replace(day=1)
    taux_de_base = Decimal(0.025)

    #lpp spécial car 0 (pas de taux de base) si CA insuffisant

    if mois_annee_date < datetime(2024, 3, 1):
        taux_avantage = Decimal(0.013)
        taux_lpp = taux_de_base + Decimal(0.013)
    else:
        if total_cerp < Decimal(60000):
            taux_avantage = Decimal(0.011)
            taux_lpp = Decimal(0)
        elif total_cerp < Decimal(70000):
            taux_avantage = Decimal(0.013)
            taux_lpp = taux_de_base + taux_avantage
        else:
            taux_avantage = Decimal(0.015)
            taux_lpp = taux_de_base + taux_avantage

    return taux_de_base, taux_avantage, taux_lpp

def check_last_year(code, new_fournisseur_generique, new_type):
    new_lpp = ""
    new_remise_grossiste = ""
    new_remise_direct = ""

    return new_type, new_fournisseur_generique, new_lpp, new_remise_grossiste, new_remise_direct


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
        elif "CERP" not in nouvel_achat.fournisseur and (
            nouvel_achat.categorie.split()[0].upper() == "GENERIQUE"
            or "DIRECT LABO" in nouvel_achat.categorie
        ):
            if produit.remise_direct:
                for r in json.loads(produit.remise_direct):
                    if nouvel_achat.nb_boites >= r[0]:
                        remise = r[1]
                nouvel_achat.remise_theorique_totale = round(Decimal(nouvel_achat.montant_ht_hors_remise) * Decimal(remise), 4)
        elif "CERP" in nouvel_achat.fournisseur and (
            nouvel_achat.categorie.split()[0].upper() == "GENERIQUE"
            or "GROSSISTE" in nouvel_achat.categorie
        ):
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
                if remise < 0:
                    nouvel_achat.remise_theorique_totale = round(Decimal(remise), 4)
                elif remise < 1:
                    #remise classique en %
                    nouvel_achat.remise_theorique_totale = round(Decimal(nouvel_achat.montant_ht_hors_remise) * Decimal(remise), 4)
                else:
                    #remise en €
                    nouvel_achat.remise_theorique_totale = round(Decimal(remise), 4)

    except Exception as e:
        logger.error(f'remise théorique non calculée pour l\'achat {nouvel_achat.produit} du {nouvel_achat.date} : {e}')
        
    return nouvel_achat


def convert_date(date_str):
    try:
        # print(1, date_str)
        month_year = datetime.strptime(date_str, "%m/%Y")
        date = month_year.replace(day=calendar.monthrange(month_year.year, month_year.month)[1])
    except:  # noqa: E722
        try:
            # print(2, date_str)
            date = datetime.strptime(date_str, "%d/%m/%Y")
        except:  # noqa: E722
            # print(3, date_str)
            date = date_str
    return date


def quicksort_liste(liste):
    if len(liste) <= 1:
        return liste
    else:
        pivot = liste[0]
        less = [x for x in liste[1:] if x < pivot]
        greater = [x for x in liste[1:] if x >= pivot]
        return quicksort_liste(less) + [pivot] + quicksort_liste(greater)
    

def tri_couples_mois_annee(liste):
    def cle_tri(couple):
        mois, annee = couple.split('/')
        return (int(annee), int(mois))

    return sorted(liste, key=cle_tri)
    

def quicksort_tableau(list_of_lists):
    if len(list_of_lists) <= 1:
        return list_of_lists
    else:
        pivot = list_of_lists[0]
        pivot_date = convert_date(pivot[0])
        less = [x for x in list_of_lists[1:] if convert_date(x[0]) < pivot_date]
        greater = [x for x in list_of_lists[1:] if convert_date(x[0]) >= pivot_date]
        return quicksort_tableau(less) + [pivot] + quicksort_tableau(greater)
    

def quicksort_tableau_dates_classiques(list_of_lists):
    if len(list_of_lists) <= 1:
        return list_of_lists
    else:
        pivot = list_of_lists[0]
        pivot_date = datetime.strptime(pivot[0], '%d/%m/%Y')
        less = [x for x in list_of_lists[1:] if datetime.strptime(x[0], '%d/%m/%Y') < pivot_date]
        greater = [x for x in list_of_lists[1:] if datetime.strptime(x[0], '%d/%m/%Y') >= pivot_date]
        return quicksort_tableau_dates_classiques(less) + [pivot] + quicksort_tableau_dates_classiques(greater)
    

def quicksort_dict(dictionary):
    if len(dictionary) <= 1:
        return dictionary

    pivot_key = list(dictionary.keys())[0]

    lesser = {}
    equal = {}
    greater = {}

    for key, value in dictionary.items():
        if convert_date(key) < convert_date(pivot_key):
            lesser[key] = value
        elif convert_date(key) == convert_date(pivot_key):
            equal[key] = value
        else:
            greater[key] = value

    return {**quicksort_dict(lesser), **equal, **quicksort_dict(greater)}


def supprimer_fichiers_dossier(dossier, critere=""):
    fichiers = os.listdir(dossier)

    for fichier in fichiers:
        chemin_fichier = os.path.join(dossier, fichier)

        if os.path.isfile(chemin_fichier):
            if critere in chemin_fichier:
                os.remove(chemin_fichier)


def get_col_index(titre_colonne, tableau):
    try:
        for colonne in range(len(tableau)):
            if tableau[0][colonne] == titre_colonne:
                return colonne
            
    except:  # noqa: E722
        for colonne in range(len(tableau)):
            if tableau[colonne] == titre_colonne:
                return colonne
            

def get_data_from_dict(dict, mois_annee, categorie = None):
    if categorie:
        if mois_annee in dict and categorie in dict[mois_annee]:
            return dict[mois_annee][categorie]
        else:
            return 0
    else:
        if mois_annee in dict:
            return dict[mois_annee]
        else:
            return 0