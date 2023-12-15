from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from .methods import *
import pandas as pd
from .models import Produit_catalogue
from datetime import datetime
import logging

# Create your views here.

logger = logging.getLogger('my_app')

@login_required
def index(request):
    return render(request,'index.html')


@login_required
def upload_factures(request):
    if request.method == 'POST':
        factures = request.FILES.getlist('factures')

        if factures:

            table_achats_finale = []
            table_produits_finale = []
            events = []

            for facture in factures:

                # Sauvegarde de la facture sur le serveur
                facture_path, facture_name = handle_uploaded_facture(facture)
                #Extraction des infos
                table_donnees, table_produits, events_facture, texte_page, tables_page, tables_page_2 = extract_data(facture_path, facture_name)
                #Ajout des infos à la bdd + Contrôles
                events_save = save_data(table_donnees)

                table_achats_finale.extend(table_donnees)
                table_produits_finale.extend(table_produits)
                events.extend(events_facture)
                events.extend(events_save)

            events.append("Importation terminée.")
            logger.debug("Importation terminée.")
            logger.debug(events)

            # On envoie les infos extraites au template HTML
            return render(request, 'index.html', {
                                                    'table_achats_finale': table_achats_finale, 
                                                    'table_produits': table_produits_finale, 
                                                    'events': events, 
                                                    'texte_page': texte_page, 
                                                    'tables_page': tables_page,
                                                    'tables_page_2': tables_page_2
                                                })
        
        else: render(request, 'index.html', {   
                                                'events': [["Aucune facture sélectionnée"]]
                                            })

    return render(request, 'index.html')


@login_required
def upload_catalogue_excel(request):
    if request.method == 'POST':

        events = []

        try:
            excel_file = request.FILES['catalogue']
            # Utiliser pandas pour lire le fichier Excel
            df = pd.read_excel(excel_file)

            default_values = {
                'annee': int(datetime.now().year),
                'designation': '',
                'type': '',
                'fournisseur_generique': '',
                'remise_grossiste': '',
                'remise_direct': '',
                'tva': 0
            }
            
            df.fillna(default_values, inplace=True)

            # Convertir les données en objets Django
            for index, row in df.iterrows():
                code = str(row['code'])
                annee = int(row['annee'])

                produit_catalogue, created = Produit_catalogue.objects.get_or_create(code=code, annee=annee)
                changed = False

                if not created:
                    # Vérifier les différences avant de mettre à jour
                    if produit_catalogue.designation != row['designation']:
                        produit_catalogue.designation = row['designation']
                        changed = True
                    if produit_catalogue.type != row['type']:
                        produit_catalogue.type = row['type']
                        changed = True
                    if produit_catalogue.fournisseur_generique != row['fournisseur_generique']:
                        produit_catalogue.fournisseur_generique = row['fournisseur_generique']
                        changed = True
                    if produit_catalogue.coalia != bool(row['coalia']):
                        produit_catalogue.coalia = bool(row['coalia'])
                        changed = True
                    if produit_catalogue.remise_grossiste != str(row['remise_grossiste']):
                        produit_catalogue.remise_grossiste = str(row['remise_grossiste'])
                        changed = True
                    if produit_catalogue.remise_direct != str(row['remise_direct']):
                        produit_catalogue.remise_direct = str(row['remise_direct'])
                        changed = True
                    if produit_catalogue.tva != float(row['tva']):
                        produit_catalogue.tva = float(row['tva'])
                        changed = True

                    produit_catalogue.save()
                    if changed:
                        events.append(f'Le produit {code} a été modifié')

                else:
                    produit_catalogue.designation = row['designation']
                    produit_catalogue.type = row['type']
                    produit_catalogue.fournisseur_generique = row['fournisseur_generique']
                    produit_catalogue.coalia = bool(row['coalia'])
                    produit_catalogue.remise_grossiste = str(row['remise_grossiste'])
                    produit_catalogue.remise_direct = str(row['remise_direct'])
                    produit_catalogue.tva = float(row['tva'])

                    produit_catalogue.save()
                    events.append(f'Le produit {code} a été ajouté')
                    
            events.append("Importation du catalogue réussie !")
            logger.debug("Importation du catalogue réussie !")

        except Exception as e:
            events.append(f'Erreur sur le produit {code}: {str(e)}')
            logger.debug(f'Erreur sur le produit {code}: {str(e)}')

        logger.debug(events)

        return render(request, 'index_upload_catalogue.html', {'events': events})

    return render(request, 'index_upload_catalogue.html')


@login_required
def afficher_tableau_synthese(request):

    #Générer le tableau dans methods
    if request.method == 'POST':

        tableau_synthese, categories = generer_tableau_synthese()
        tableau_generiques = generer_tableau_generiques()

        return render(request, 'index_tableau.html', {
            'tableau_synthese': tableau_synthese,
            'tableau_generiques': tableau_generiques,
            'categories': categories
        })

    return render(request, 'index_tableau.html')