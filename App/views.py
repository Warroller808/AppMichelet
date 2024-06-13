from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.core.files.storage import default_storage
from django.db.models.functions import ExtractMonth, ExtractYear
from django.db.models import Q
from datetime import datetime
import logging
import pandas as pd
from .methods import handle_uploaded_facture, process_factures, telecharger_excel
from .methods import generer_tableau_alliance, generer_tableau_eg, generer_tableau_generiques, generer_tableau_grossiste, generer_tableau_simplifie
from .methods import generer_tableau_synthese, generer_tableau_teva, data_dict_tab_simplifie, data_dict_tab_simplifie_full_year
from .utils import quicksort_liste
from .models import Achat, Produit_catalogue, Constante, Releve_alliance
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
    categories = []
    categorie_selectionnee = ""
    annees = []
    annee_selectionnee = ""
    mois = []
    mois_selectionne = ""

    try:
        data_categories = (
                Achat.objects
                .values('categorie')
                .distinct()
            )
        
        categories = [str(element['categorie']) for element in data_categories]
        categories = ["Tous"] + categories
        categorie_selectionnee = request.POST.get('categorie', '')

        if not categorie_selectionnee and categories:
            categorie_selectionnee = "Tous"

        data_annees = (
                Achat.objects
                .annotate(annee=ExtractYear('date'))
                .values('annee')
                .distinct()
            )
        
        annees = [str(element['annee']) for element in data_annees]
        annees = ["Tous"] + quicksort_liste(annees)
        annee_selectionnee = request.POST.get('annee', '')

        if not annee_selectionnee and annees:
            annee_selectionnee = "Tous"

        data_mois = (
                Achat.objects
                .annotate(mois=ExtractMonth('date'))
                .values('mois')
                .distinct()
            )
        
        mois = [str(element['mois']) for element in data_mois]
        mois = ["Tous"] + [str(intelement) for intelement in quicksort_liste([int(strelement) for strelement in mois])]
        mois_selectionne = request.POST.get('mois', '')

        if not mois_selectionne and mois:
            mois_selectionne = "Tous"

    except Exception as e:
        logger.error(f'Erreur dans la gestion des filtres : {e}')
        events = "Erreur lors de la gestion des filtres."
    
    if request.method == 'POST':

        filtre_categorie = Q()

        if categorie_selectionnee != "Tous":
            filtre_categorie = Q(categorie=categorie_selectionnee)

        filtre_annee = Q()

        if annee_selectionnee != "Tous":
            filtre_annee = Q(annee=annee_selectionnee)

        filtre_mois = Q()

        if mois_selectionne != "Tous":
            filtre_mois = Q(mois=mois_selectionne)

        data = (
            Achat.objects
            .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
            .filter(
                filtre_categorie,
                filtre_annee,
                filtre_mois,
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
                excel_file = telecharger_excel(data, "Achat")
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
            'mois': mois,
            'mois_selectionne': mois_selectionne,
            'events': events
        }

        return render(request, 'index_telecharger_achats.html', context)
    
    else:
        context = {
            'categories': categories,
            'categorie_selectionnee': categorie_selectionnee,
            'annees': annees,
            'annee_selectionnee': annee_selectionnee,
            'mois': mois,
            'mois_selectionne': mois_selectionne,
        }

        return render(request, 'index_telecharger_achats.html', context)


@login_required
def telecharger_produits_tableau_simplifie(request):

    if request.method == 'GET':

        mois_annee = request.GET.get('date')

        if len(mois_annee) > 4:
            filtre_mois = Q(mois=mois_annee.split('/')[0])
            filtre_annee = Q(annee=mois_annee.split('/')[1])
        else:
            filtre_mois = Q()
            filtre_annee = Q(annee=mois_annee)

        #Q(categorie__startswith='GENERIQUE') | Q(categorie__icontains='MARCHE PRODUITS') | Q(categorie__icontains='UPP') | Q(categorie__icontains='COALIA') | Q(categorie__icontains='PHARMAT'),

        data = (
            Achat.objects
            .annotate(mois=ExtractMonth('date'), annee=ExtractYear('date'))
            .filter(
                Q(fournisseur__icontains='CERP') | Q(fournisseur__icontains='PHARMAT'),
                filtre_mois,
                filtre_annee,
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

        try:
            excel_file = telecharger_excel(data, "Achat")
            date_actuelle = datetime.now().strftime("%d-%m-%Y")
            filename = f"{date_actuelle}_achats_{mois_annee}.xlsx"

            response = HttpResponse(excel_file, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = f'attachment; filename={filename}'

            default_storage.delete(filename)

            return response

        except Exception as e:
            logger.error(f'Erreur lors du traitement du fichier excel (tableau simplifié): {e}')


@login_required
def telecharger_releves_alliance(request):

    if request.method == 'GET':

        data = (
            Releve_alliance.objects
            .values(
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
            )
        )

        try:
            excel_file = telecharger_excel(data, "Releve_alliance")
            date_actuelle = datetime.now().strftime("%d-%m-%Y")
            filename = f"{date_actuelle}_releves_alliance.xlsx"

            response = HttpResponse(excel_file, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = f'attachment; filename={filename}'

            default_storage.delete(filename)

            return response

        except Exception as e:
            logger.error(f'Erreur lors du traitement du fichier excel (tableau Alliance): {e}')
        

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

    data_dict, annees = data_dict_tab_simplifie()

    mois_annees = list(data_dict.keys())
    mois_annees = annees + mois_annees
    mois_annee_selectionne = request.GET.get('mois_annee', '')

    if not mois_annee_selectionne and mois_annees:
        mois_annee_selectionne = "10/2023"

    if len(mois_annee_selectionne) > 4:
        tableau_simplifie, colonnes = generer_tableau_simplifie(mois_annee_selectionne, data_dict)
    else:
        tableau_simplifie, colonnes = generer_tableau_simplifie(mois_annee_selectionne, data_dict_tab_simplifie_full_year(mois_annee_selectionne))

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


@login_required
def tableau_eg(request):

    dernier_import_cerp = Constante.objects.get(pk="LAST_IMPORT_DATE_CERP").value
    dernier_import_digi = Constante.objects.get(pk="LAST_IMPORT_DATE_DIGIPHARMACIE").value

    if request.method == 'POST':

        tableau_eg, colonnes = generer_tableau_eg()

        return render(request, 'index_tableau_eg.html', {
            'tableau_eg': tableau_eg,
            'colonnes': colonnes,
            'dernier_import_cerp' : dernier_import_cerp,
            'dernier_import_digi' : dernier_import_digi
        })

    return render(request, 'index_tableau_eg.html', {
        'dernier_import_cerp' : dernier_import_cerp,
        'dernier_import_digi' : dernier_import_digi
    })


@login_required
def tableau_alliance(request):

    dernier_import_digi = Constante.objects.get(pk="LAST_IMPORT_DATE_DIGIPHARMACIE").value

    print("GET parameters:", request.GET)

    show_decades = request.GET.get('decades_value', 'on') == 'on'

    data_annees = (
        Releve_alliance.objects
        .annotate(annee=ExtractYear('date'))
        .filter(annee__gte = 2022)
        .values('annee')
        .distinct()
    )
    annees = [str(element['annee']) for element in data_annees]
    annees = ["Tous"] + quicksort_liste(annees)
    annee_selectionnee = request.GET.get('annee', '')

    if not annee_selectionnee and annees:
        annee_selectionnee = "Tous"

    filtre_annee = Q()
    if annee_selectionnee != "Tous":
        filtre_annee = Q(annee=annee_selectionnee)

    data_mois = (
        Releve_alliance.objects
        .annotate(annee=ExtractYear('date'), mois=ExtractMonth('date'))
        .filter(
            filtre_annee,
            annee__gte = 2022,
        )
        .values('mois')
        .distinct()
    )
    
    mois = [str(element['mois']) for element in data_mois]
    mois = ["Tous"] + [str(intelement) for intelement in quicksort_liste([int(strelement) for strelement in mois])]
    mois_selectionne = request.GET.get('mois', '')

    if not mois_selectionne and mois:
        mois_selectionne = "Tous"

    filtre_mois = Q()
    if mois_selectionne != "Tous":
        filtre_mois = Q(mois=mois_selectionne)

    tableau_alliance, colonnes = generer_tableau_alliance(show_decades, filtre_annee, filtre_mois)

    return render(request, 'index_tableau_alliance.html', {
        'tableau_alliance': tableau_alliance,
        'colonnes': colonnes,
        'dernier_import_digi' : dernier_import_digi,
        'show_decades': show_decades,
        'annees': annees,
        'annee_selectionnee': annee_selectionnee,
        'mois': mois,
        'mois_selectionne': mois_selectionne,
    })


@staff_member_required
def lancer_import_auto(request):
    if request.method == 'POST':
        logger.error('Lancer import auto test')
        #async_import_factures_auto.delay()
        async_import_factures_depuis_dossier.delay()

    return render(request, 'index.html')