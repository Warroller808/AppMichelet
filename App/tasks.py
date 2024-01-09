from celery import shared_task
from .jobs import import_factures_auto


@shared_task
def async_import_factures_auto():
    import_factures_auto()


@shared_task
def async_import_factures_depuis_dossier():
    from .methods import get_factures_from_directory, process_factures
    #Permet de déclencher le traitement asynchrone des factures après avoir rempli le fichier de factures manuellement
    facture_paths = get_factures_from_directory()
    if facture_paths != []:
        success, table_achats_finale, events, texte_page, tables_page, tables_page_2 = process_factures(facture_paths)

        if success:
            print("Factures traitées avec succès")
        else:
            print("Erreur lors du traitement des factures")

    else:
        print("Aucune facture dans le dossier d'import auto")