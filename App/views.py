from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from .methods import *
import pandas as pd
from .models import Produit_catalogue
from datetime import datetime
import logging
from .tasks import async_import_factures_auto, async_import_factures_depuis_dossier

# Create your views here.

logger = logging.getLogger(__name__)


@login_required
def index(request):
    return render(request,'index.html')


@login_required
def upload_factures(request):
    if request.method == 'POST':
        # Traitement des factures manuelles
        factures = request.FILES.getlist('factures')
        if factures:
            facture_paths = [handle_uploaded_facture(facture) for facture in factures]

            success, table_achats_finale, events, texte_page, tables_page, tables_page_2 = process_factures(facture_paths)

            logger.error(f'Succès de l\'importation manuelle des factures : {success}')

            # On envoie les infos extraites au template HTML
            return render(request, 'index.html', {
                                                'table_achats_finale': table_achats_finale,
                                                'events': events, 
                                                'texte_page': texte_page, 
                                                'tables_page': tables_page,
                                                'tables_page_2': tables_page_2
                                            })
        
        else: 
            return render(request, 'index.html', {   
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
                    if produit_catalogue.pharmupp != bool(row['pharmupp']):
                        produit_catalogue.pharmupp = bool(row['pharmupp'])
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
                    produit_catalogue.pharmupp = bool(row['pharmupp'])
                    produit_catalogue.remise_grossiste = str(row['remise_grossiste'])
                    produit_catalogue.remise_direct = str(row['remise_direct'])
                    produit_catalogue.tva = float(row['tva'])

                    produit_catalogue.save()
                    events.append(f'Le produit {code} a été ajouté')
                    
            events.insert(0, "Importation du catalogue réussie !")
            logger.error("Importation du catalogue réussie !")

        except Exception as e:
            events.append(f'Erreur sur le produit {code}: {str(e)}')
            logger.error(f'Erreur sur le produit {code}: {str(e)}')

        logger.error(events)

        return render(request, 'index_upload_catalogue.html', {'events': events})

    return render(request, 'index_upload_catalogue.html')


@login_required
def tableau_synthese(request):

    #Générer le tableau dans methods
    if request.method == 'POST':

        tableau_synthese_assiette_globale, categories_assiette_globale, tableau_synthese_autres, categories_autres = generer_tableau_synthese()

        return render(request, 'index_tableau.html', {
            'tableau_synthese_assiette_globale': tableau_synthese_assiette_globale,
            'tableau_synthese_autres': tableau_synthese_autres,
            'tableau_generiques': tableau_generiques,
            'categories_assiette_globale': categories_assiette_globale,
            'categories_autres': categories_autres
        })

    return render(request, 'index_tableau.html')


@login_required
def tableau_generiques(request):
    
    laboratoires = Produit_catalogue.objects.exclude(fournisseur_generique='').values('fournisseur_generique').distinct()
    laboratoire_selectionne = request.GET.get('laboratoire', '')

    tableau_generiques, colonnes, achats_labo = generer_tableau_generiques(laboratoire_selectionne)

    context = {
        'laboratoires': laboratoires,
        'laboratoire_selectionne': laboratoire_selectionne,
        'tableau_generiques': tableau_generiques,
        'colonnes': colonnes,
        'achats_labo': achats_labo,
    }

    return render(request, 'index_tableau_generiques.html', context)


@login_required
def lancer_import_auto(request):
    if request.method == 'POST':
        logger.error('Lancer import auto test')
        #async_import_factures_auto.delay()
        async_import_factures_depuis_dossier()

    return render(request, 'index.html')