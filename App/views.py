from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.core.files.storage import default_storage
from .methods import *
import pandas as pd
from .models import Produit_catalogue, Constante
from datetime import datetime
import logging
from .tasks import async_import_factures_depuis_dossier

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
def telecharger_achats(request):

    events = ""

    try:
        data_categories = (
                Achat.objects
                .values('categorie')
                .distinct()
            )
        
        categories = [str(element['categorie']) for element in data_categories]
        categorie_selectionnee = request.POST.get('categorie', '')

        if not categorie_selectionnee and categories:
            categorie_selectionnee = ">450€ tva 2,1%"

        data_annees = (
                Achat.objects
                .annotate(annee=ExtractYear('date'))
                .values('annee')
                .distinct()
            )
        
        annees = ["Tous"] + [str(element['annee']) for element in data_annees]
        annee_selectionnee = request.POST.get('annee', '')

        if not annee_selectionnee and annees:
                annee_selectionnee = "2023"

    except Exception as e:
        logger.error(f'Erreur dans la gestion des filtres : {e}')
        events = "Erreur lors de la gestion des filtres."
    
    if request.method == 'POST':

        filtre_annee = Q()

        if annee_selectionnee != "Tous":
            filtre_annee = Q(annee=annee_selectionnee)

        data = (
            Achat.objects
            .annotate(annee=ExtractYear('date'))
            .filter(
                filtre_annee,
                categorie=categorie_selectionnee
            )
            .values(
                'code',
                'designation',
                'nb_boites',
                'prix_unitaire_ht',
                'prix_unitaire_remise_ht',
                'remise_pourcent',
                'montant_ht_hors_remise',
                'montant_ht',
                'produit__remise_grossiste',
                'produit__remise_direct',
                'remise_theorique_totale',
                'tva',
                'date',
                'numero_facture',
                'fournisseur',
                'categorie',
                'categorie_remise',
                'produit__annee',
                'produit__fournisseur_generique',
                'produit__coalia',
                'produit__pharmupp',
                'produit__lpp',
                'produit__creation_auto',
            )
        )

        if len(data) > 0:
            try:
                excel_file = telecharger_achats_excel(data)
                date_actuelle = datetime.now().strftime("%d-%m-%Y")
                filename = f"{date_actuelle}_achats.xlsx"

                response = HttpResponse(excel_file, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                response['Content-Disposition'] = f'attachment; filename={filename}'

                default_storage.delete(filename)

                return response
            
            except Exception as e:
                logger.error(f'Erreur lors du traitement du fichier excel : {e}')
                events = "Erreur lors de la génération du fichier."
        
        else:
            events = "Aucun achat ne correspond à ces critères."

        context = {
            'categories': categories,
            'categorie_selectionnee': categorie_selectionnee,
            'annees': annees,
            'annee_selectionnee': annee_selectionnee,
            'events': events
        }

        return render(request, 'index_telecharger_achats.html', context)
    
    else:
        context = {
            'categories': categories,
            'categorie_selectionnee': categorie_selectionnee,
            'annees': annees,
            'annee_selectionnee': annee_selectionnee
        }

        return render(request, 'index_telecharger_achats.html', context)


@staff_member_required
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
                'tva': 0,
                'date_creation': datetime.now(),
                'creation_auto' : False
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
                    if produit_catalogue.lpp != bool(row['lpp']):
                        produit_catalogue.lpp = bool(row['lpp'])
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
                    dateobjet = datetime(produit_catalogue.date_creation.year, produit_catalogue.date_creation.month, produit_catalogue.date_creation.day)
                    datefichier = datetime(row['date_creation'].year, row['date_creation'].month, row['date_creation'].day)
                    if dateobjet != datefichier:
                        produit_catalogue.date_creation = row['date_creation']
                        changed = True
                    if produit_catalogue.creation_auto != bool(row['creation_auto']):
                        produit_catalogue.creation_auto = bool(row['creation_auto'])
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
                    produit_catalogue.date_creation = row['date_creation']
                    produit_catalogue.creation_auto = bool(row['creation_auto'])

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

    dernier_import_cerp = Constante.objects.get(pk="LAST_IMPORT_DATE_CERP").value
    dernier_import_digi = Constante.objects.get(pk="LAST_IMPORT_DATE_DIGIPHARMACIE").value

    #Générer le tableau dans methods
    if request.method == 'POST':

        tableau_synthese_assiette_globale, categories_assiette_globale, tableau_synthese_autres, categories_autres, explications = generer_tableau_synthese()

        return render(request, 'index_tableau.html', {
            'tableau_synthese_assiette_globale': tableau_synthese_assiette_globale,
            'tableau_synthese_autres': tableau_synthese_autres,
            'tableau_generiques': tableau_generiques,
            'categories_assiette_globale': categories_assiette_globale,
            'categories_autres': categories_autres,
            'explications': explications,
            'dernier_import_cerp' : dernier_import_cerp,
            'dernier_import_digi' : dernier_import_digi
        })

    return render(request, 'index_tableau.html', {
        'dernier_import_cerp' : dernier_import_cerp,
        'dernier_import_digi' : dernier_import_digi
    })


@login_required
def tableau_grossiste(request):

    dernier_import_cerp = Constante.objects.get(pk="LAST_IMPORT_DATE_CERP").value
    dernier_import_digi = Constante.objects.get(pk="LAST_IMPORT_DATE_DIGIPHARMACIE").value

    data_annees = (
        Achat.objects
        .annotate(annee=ExtractYear('date'))
        .values('annee')
        .distinct()
    )

    annees = [str(element['annee']) for element in data_annees]
    annee_selectionnee = request.GET.get('annee', '')

    if not annee_selectionnee and annees:
        annee_selectionnee = "2023"

    tableau_grossiste, colonnes = generer_tableau_grossiste(annee_selectionnee)

    context = {
        'annees': annees,
        'annee_selectionnee': annee_selectionnee,
        'tableau_grossiste': tableau_grossiste,
        'colonnes': colonnes,
        'dernier_import_cerp' : dernier_import_cerp,
        'dernier_import_digi' : dernier_import_digi
    }

    return render(request, 'index_tableau_grossiste.html', context)


@login_required
def tableau_simplifie(request):

    dernier_import_cerp = Constante.objects.get(pk="LAST_IMPORT_DATE_CERP").value
    dernier_import_digi = Constante.objects.get(pk="LAST_IMPORT_DATE_DIGIPHARMACIE").value

    data_dict = data_dict_tab_simplifie()

    mois_annees = list(data_dict.keys())
    mois_annee_selectionne = request.GET.get('mois_annee', '')

    if not mois_annee_selectionne and mois_annees:
        mois_annee_selectionne = "10/2023"

    tableau_simplifie, colonnes = generer_tableau_simplifie(mois_annee_selectionne, data_dict)

    context = {
        'mois_annees': mois_annees,
        'mois_annee_selectionne': mois_annee_selectionne,
        'tableau_simplifie': tableau_simplifie,
        'colonnes': colonnes,
        'dernier_import_cerp' : dernier_import_cerp,
        'dernier_import_digi' : dernier_import_digi
    }

    return render(request, 'index_tableau_simplifie.html', context)


@login_required
def tableau_generiques(request):

    dernier_import_cerp = Constante.objects.get(pk="LAST_IMPORT_DATE_CERP").value
    dernier_import_digi = Constante.objects.get(pk="LAST_IMPORT_DATE_DIGIPHARMACIE").value

    laboratoires = Produit_catalogue.objects.exclude(fournisseur_generique='').values('fournisseur_generique').distinct()
    laboratoire_selectionne = request.GET.get('laboratoire', '')

    if not laboratoire_selectionne and laboratoires:
        laboratoire_selectionne = laboratoires[0]['fournisseur_generique']

    tableau_generiques, colonnes, achats_labo = generer_tableau_generiques(laboratoire_selectionne)

    context = {
        'laboratoires': laboratoires,
        'laboratoire_selectionne': laboratoire_selectionne,
        'tableau_generiques': tableau_generiques,
        'colonnes': colonnes,
        'achats_labo': achats_labo,
        'dernier_import_cerp' : dernier_import_cerp,
        'dernier_import_digi' : dernier_import_digi
    }

    return render(request, 'index_tableau_generiques.html', context)


@login_required
def tableau_teva(request):

    dernier_import_cerp = Constante.objects.get(pk="LAST_IMPORT_DATE_CERP").value
    dernier_import_digi = Constante.objects.get(pk="LAST_IMPORT_DATE_DIGIPHARMACIE").value

    if request.method == 'POST':

        tableau_teva, colonnes = generer_tableau_teva()

        return render(request, 'index_tableau_teva.html', {
            'tableau_teva': tableau_teva,
            'colonnes': colonnes,
            'dernier_import_cerp' : dernier_import_cerp,
            'dernier_import_digi' : dernier_import_digi
        })

    return render(request, 'index_tableau_teva.html', {
        'dernier_import_cerp' : dernier_import_cerp,
        'dernier_import_digi' : dernier_import_digi
    })


@staff_member_required
def lancer_import_auto(request):
    if request.method == 'POST':
        logger.error('Lancer import auto test')
        #async_import_factures_auto.delay()
        async_import_factures_depuis_dossier.delay()

    return render(request, 'index.html')