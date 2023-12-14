import re
import logging
from .models import Format_facture, Produit_catalogue
import json


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

    try:
        regex_date = re.compile(Format_facture.objects.get(pk=format).regex_date)

        # Recherche la date dans le texte
        match = re.search(regex_date, texte)
        
        if match:
            date_formatee = match.group(1).strip().replace(".","/").replace(" ","/")
        
        return date_formatee
    
    except:
        return None
    

def extraire_numero_facture(format, texte):
    try:
        regex_numero_facture = re.compile(Format_facture.objects.get(pk=format).regex_numero_facture)  

        # Recherche le numéro de facture dans le texte
        match = re.search(regex_numero_facture, texte)
        #print(match.group(1))
        return match.group(1) if match else None
    
    except:
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

    if format_facture.format == "TEVA":
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
                print(ligne)
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

        print(table_pretraitee)

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

                        #try:

                        if format_facture.indice_code_produit != -1:
                            code = ligne_sans_none[format_facture.indice_code_produit]
                            donnees_ligne.append(''.join(caractere for caractere in code if not caractere.isalpha() and not caractere.isspace()))
                        else: donnees_ligne.append("")

                        if format_facture.indice_designation != -1:
                            donnees_ligne.append(ligne_sans_none[format_facture.indice_designation])
                        else: donnees_ligne.append("")

                        if format_facture.indice_nb_boites != -1:
                            if ligne_sans_none[format_facture.indice_nb_boites] != "":
                                donnees_ligne.append(int(ligne_sans_none[format_facture.indice_nb_boites]))
                            else: donnees_ligne.append(0)
                        else: donnees_ligne.append(0)

                        if format_facture.indice_prix_unitaire_ht != -1:
                            if ligne_sans_none[format_facture.indice_prix_unitaire_ht] != "":
                                donnees_ligne.append(float(ligne_sans_none[format_facture.indice_prix_unitaire_ht].replace(",",".").replace(" ","")))
                            else: donnees_ligne.append(0)
                        else: donnees_ligne.append(0)

                        if format_facture.indice_prix_unitaire_remise_ht != -1:
                            if ligne_sans_none[format_facture.indice_prix_unitaire_remise_ht] != "":
                                donnees_ligne.append(float(ligne_sans_none[format_facture.indice_prix_unitaire_remise_ht].replace(",",".").replace(" ","")))
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
                                donnees_ligne.append(float(ligne_sans_none[format_facture.indice_montant_ht_hors_remise].replace(",",".").replace(" ","")))
                            else: donnees_ligne.append(0)
                        else: 
                            donnees_ligne.append(float(ligne_sans_none[format_facture.indice_prix_unitaire_ht].replace(",",".").replace(" ","")) * int(ligne_sans_none[format_facture.indice_nb_boites]))

                        if format_facture.indice_montant_ht != -1:
                            if ligne_sans_none[format_facture.indice_montant_ht] != "":
                                donnees_ligne.append(float(ligne_sans_none[format_facture.indice_montant_ht].replace(",",".").replace(" ","")))
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

                        for donnee in donnees_ligne:
                            print(donnee)

                        processed_table.append(donnees_ligne)
                        i+=1

                        #except:
                            #continue

        return processed_table, events
    
    #except:
        return None


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


def categoriser_achat(fournisseur, tva, prix_unitaire_ht, coalia, generique):
    new_categorie = ""

    if fournisseur == "CERP COALIA":
        new_categorie = "COALIA"
    elif fournisseur == "CERP PHARMAT" or fournisseur == "PHARMAT" :
        new_categorie = "PHARMAT"
    elif "CERP" in fournisseur:
        if generique:
            new_categorie = "GENERIQUE"
        elif coalia:
            new_categorie = "UPP"
        elif tva == 0.021 and prix_unitaire_ht < 450:
            new_categorie = "<450€ tva 2,1%"
        elif tva == 0.021 and prix_unitaire_ht > 450 and prix_unitaire_ht < 1500:
            new_categorie = ">450€ <1500€ tva 2,1%"
        elif tva == 0.021 and prix_unitaire_ht > 1500:
            new_categorie = ">1500€ tva 2,1%"
        elif tva == 0.055 or tva == 0.1:
            new_categorie = "LPP"
        elif tva == 0.20:
            new_categorie = "PARAPHARMACIE"
        else:
            new_categorie = "NON CATEGORISE CERP"
    elif fournisseur == "TEVA" or fournisseur == "EG" or fournisseur == "BIOGARAN"  or fournisseur == "ARROW" :
        new_categorie = "GENERIQUE"
    else:
        new_categorie = "NON CATEGORISE"

    return new_categorie


def quicksort(list_of_lists):
    if len(list_of_lists) <= 1:
        return list_of_lists
    else:
        pivot = list_of_lists[0]
        less = [x for x in list_of_lists[1:] if x[0] < pivot[0]]
        greater = [x for x in list_of_lists[1:] if x[0] >= pivot[0]]
        return quicksort(less) + [pivot] + quicksort(greater)