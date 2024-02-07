import logging
from celery import shared_task
from .jobs import import_factures_auto

logger = logging.getLogger(__name__)


@shared_task
def async_import_factures_auto():
    import_factures_auto()


@shared_task
def async_import_factures_depuis_dossier():
    from .methods import get_factures_from_directory, process_factures
    from .jobs import completer_fournisseur_generique_et_type_job, categoriser_achats_job, calcul_remises_job
    #Permet de déclencher le traitement asynchrone des factures après avoir rempli le dossier de factures manuellement (dossier des factures auto)
    facture_paths = get_factures_from_directory()
    if facture_paths != []:
        success, table_achats_finale, events, texte_page, tables_page, tables_page_2 = process_factures(facture_paths)

        if success:
            logger.error("Factures traitées avec succès")
        else:
            logger.error("Erreur lors du traitement des factures")

    else:
        logger.error("Aucune facture dans le dossier d'import auto")

    logger.error("Completion des fournisseurs génériques...")
    completer_fournisseur_generique_et_type_job()

    logger.error("Catégorisation des achats...")
    categoriser_achats_job()

    logger.error("Calcul des remises...")
    calcul_remises_job()