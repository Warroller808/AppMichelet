import logging
from datetime import datetime
from .utils import supprimer_fichiers_dossier
from .methods import get_factures_from_directory, process_factures
from .constants import DL_FOLDER_PATH_AUTO
from .selenium_cerp import main_cerp
from .selenium_digipharmacie import main_digi
from .models import Constante


logger = logging.getLogger(__name__)


def import_factures_auto():
    # On télécharge les factures avec selenium
    
    success_cerp = main_cerp()
    success_digi = main_digi()

    logger.error(f'Success CERP : {success_cerp}, Success Digi : {success_digi}')

    if success_cerp or success_digi:
        # On les traite
        facture_paths = get_factures_from_directory()
        if facture_paths != []:
            success, table_achats_finale, events, texte_page, tables_page, tables_page_2 = process_factures(facture_paths)

            if success:
                supprimer_fichiers_dossier(DL_FOLDER_PATH_AUTO)
                # UPDATER LA DATE DE DERNIERE IMPORTATION
                logger.error(f'Succès de l\'importation automatique et du traitement. Factures supprimées dans le dossier.')

                if success_cerp:
                    last_import_date_cerp = Constante.objects.get(pk="LAST_IMPORT_DATE_CERP")
                    last_import_date_cerp.value = datetime.now().strftime("%d/%m/%Y")
                    last_import_date_cerp.save()
                
                if success_digi:
                    last_import_date_digi = Constante.objects.get(pk="LAST_IMPORT_DATE_DIGIPHARMACIE")
                    last_import_date_digi.value = datetime.now().strftime("%d/%m/%Y")
                    last_import_date_digi.save()

            else:
                logger.error('Erreur de traitement, les fichiers ont été conservés.')
        else:
            logger.error("Aucune facture n'a été téléchargée aujourd'hui")
    else:
        logger.error('Erreur d\'importation sur les deux sites, les fichiers téléchargés ont été conservés.')