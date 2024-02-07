import os
import time
import logging
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException
from datetime import date, datetime, timedelta
from math import ceil
from .constants import DL_FOLDER_PATH_AUTO
from .models import Constante
from .utils import supprimer_fichiers_dossier


logger = logging.getLogger(__name__)


def telecharger_fichier_cerp(driver, first_date, last_date):

    success = True
    faulty_range = None

    try:
        prev_files_list = os.listdir(DL_FOLDER_PATH_AUTO)

        download_button = driver.find_element(By.CSS_SELECTOR, 'button[aria-haspopup="true"][aria-expanded="false"].v-icon--link.ci-download')
        driver.execute_script("arguments[0].click();", download_button)

        # Vérifier si l'alerte 500 est présente pendant l'attente explicite
        try:
            error_popup = WebDriverWait(driver, 80).until(
                EC.presence_of_element_located((By.XPATH, '//div[@role="alert" and contains(text(), "500")]'))
            )

            # Si l'alerte est trouvée, afficher un message et gérer en conséquence
            logger.error("Erreur 500 détectée. On essaie à nouveau.")
            # Votre code pour gérer l'erreur 500 ici
            success = False
            format = "%d-%m-%Y"
            faulty_range = f'{first_date.strftime(format)}_au_{last_date.strftime(format)}'

            time.sleep(15)

        except TimeoutException:
            # Aucune alerte n'a été détectée dans le délai imparti
            pass

        
        WebDriverWait(driver, 5).until(lambda driver: len(os.listdir(DL_FOLDER_PATH_AUTO)) > len(prev_files_list))
        logger.error(f'Téléchargement terminé')

        for fichier in os.listdir(DL_FOLDER_PATH_AUTO):
            if fichier not in prev_files_list:
                #C'est le nouveau fichier, on le renomme
                full_file_path = os.path.join(DL_FOLDER_PATH_AUTO, fichier)
                format = "%d-%m-%Y"
                new_name = os.path.join(DL_FOLDER_PATH_AUTO, f'CERP_SAE_{datetime.now().strftime(format)}_---_{first_date.strftime(format)}_au_{last_date.strftime(format)}.pdf')
                os.rename(full_file_path, new_name)

        logger.error(f'Fichier renommé : {new_name}')
    
    except WebDriverException as e:
        # Gérer d'autres exceptions WebDriverException si nécessaire
        logger.error(f"Une exception WebDriver est survenue : {e}")
        success = False

    return success, faulty_range


def process_page_cerp(driver):

    time.sleep(2)

    WebDriverWait(driver, 3).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, 'div.v-data-table__wrapper'))
    )
    
    time.sleep(1)

    table_div = driver.find_element(By.CSS_SELECTOR, 'div.v-data-table__wrapper')

    table_body = table_div.find_element(By.TAG_NAME, "tbody")
    table_rows = table_body.find_elements(By.TAG_NAME, "tr")

    first_date = None
    last_date = None

    faulty_range = ""

    try:
        for row in table_rows:
            row_data = [cell.text for cell in row.find_elements(By.TAG_NAME, "td")]

            if last_date is None:
                last_date = datetime.strptime(row_data[8], '%d/%m/%Y')
            elif datetime.strptime(row_data[8], '%d/%m/%Y') > last_date:
                last_date = datetime.strptime(row_data[8], '%d/%m/%Y')

            if first_date is None:
                first_date = datetime.strptime(row_data[8], '%d/%m/%Y')
            elif datetime.strptime(row_data[8], '%d/%m/%Y') < first_date:
                first_date = datetime.strptime(row_data[8], '%d/%m/%Y')

        logger.error(f'{first_date} au {last_date}')

        header = driver.find_element(By.CSS_SELECTOR, 'thead.easGrid-header')
        selecteur_general = header.find_element(By.CSS_SELECTOR, 'div.v-input--selection-controls__ripple')
        selecteur_general.click()
        time.sleep(1)

        logger.error('Téléchargement du fichier...')

        success = False
        essais = 3
        while not success and essais > 0:
            print(f'Essai {essais}')
            success, faulty_range = telecharger_fichier_cerp(driver, first_date, last_date)
            essais -= 1

        logger.error(f'success : {success}')
    
    except IndexError:
        logger.error(f'Aucune facture à traiter')
        success = True

    return success, faulty_range


def main_cerp():

    LAST_IMPORT_DATE = Constante.objects.get(pk="LAST_IMPORT_DATE_CERP")

    if LAST_IMPORT_DATE:
        LAST_IMPORT_DATE = datetime.strptime(LAST_IMPORT_DATE.value, '%d/%m/%Y')
        #set import range of 1 week
        LAST_IMPORT_DATE = LAST_IMPORT_DATE + timedelta(days=-7)
    else:
        LAST_IMPORT_DATE = datetime(2020, 1, 1)

    # URL du site et du formulaire de connexion
    login_url = "https://cerp-rrm.numeria.fr/#/login"
    username = "contact@pharmaciemichelet.fr"
    password = "x,V@n?eD4R7&BYu"

    if not os.path.exists(DL_FOLDER_PATH_AUTO):
        os.makedirs(DL_FOLDER_PATH_AUTO)

    print(f'Download URL : {DL_FOLDER_PATH_AUTO}')

    # Utiliser le navigateur Chrome (à remplacer par le navigateur de votre choix)
    chrome_options = webdriver.ChromeOptions()
    prefs = {'download.default_directory' : DL_FOLDER_PATH_AUTO}
    chrome_options.add_experimental_option('prefs', prefs)
    chrome_options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=chrome_options)

    # Aller sur la page de connexion
    driver.get(login_url)

    time.sleep(2)

    # Remplir le formulaire d'authentification
    username_input = driver.find_element(By.ID, "input-33")
    password_input = driver.find_element(By.ID, "input-34")

    username_input.send_keys(username)
    password_input.send_keys(password)

    # Soumettre le formulaire
    password_input.send_keys(Keys.RETURN)

    time.sleep(3)

    WebDriverWait(driver, 3).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, 'div.v-data-table__wrapper'))
    )
    time.sleep(1)

    input_date = driver.find_element(By.XPATH, '//input[@data-type="date" and @id="if-Date"]')
    date_fin = datetime.now() + timedelta(days=1)
    date_range = f'>{LAST_IMPORT_DATE.strftime("%d/%m/%Y")} & <{date_fin.strftime("%d/%m/%Y")}'
    input_date.send_keys(date_range)

    logger.error(f'CERP date range : {date_range}')

    time.sleep(1)

    selecteur_nb = driver.find_element(By.XPATH, '//div[contains(@class, "v-select__selection v-select__selection--comma") and contains(text(), "50")]')
    selecteur_nb.click()
    WebDriverWait(driver, 3).until(
        EC.presence_of_element_located((By.XPATH, '//div[@class="v-list-item__title" and contains(text(), "200")]'))
    )
    nb_element = driver.find_element(By.XPATH, '//div[@class="v-list-item__title" and contains(text(), "200")]')
    nb_element.click()
    
    time.sleep(2)

    compte_pages = driver.find_element(By.CSS_SELECTOR, 'span.mx-2')
    span_text = compte_pages.text
    total_lignes = int(span_text.split()[-1])
    total_pages = ceil(total_lignes / 200)

    #traitement page 1
    logger.error('traitement de la page 1')
    process_page_cerp(driver)

    success = True

    for page in range(2, total_pages + 1):

        button_right = driver.find_element(By.CSS_SELECTOR, 'i.v-icon.notranslate.ci.ci-chevron_right.theme--light.black--text[aria-hidden="true"]')
        driver.execute_script("arguments[0].click();", button_right)

        logger.error(f'traitement de la page {page}')
        success, faulty_range = process_page_cerp(driver)

        if not success:
            if not faulty_range is None:
                logger.error(f'Erreur de traitement de la plage de dates suivante : {faulty_range}')
            else:
                logger.error('Erreur inconnue, plage de dates non retournée par le programme.')
            logger.error("Fin du programme et suppression des fichiers")
            supprimer_fichiers_dossier(DL_FOLDER_PATH_AUTO, "CERP_SAE")
            break
    
    driver.quit()
    
    return success