import os
import time
import logging
import zipfile
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from datetime import datetime, timedelta
from .constants import DL_FOLDER_PATH_AUTO
from .models import Constante


logger = logging.getLogger(__name__)


def handle_popups(driver):
    # Obtenir les dimensions de la fenêtre du navigateur
    window_width = driver.execute_script("return window.innerWidth;")
    window_height = driver.execute_script("return window.innerHeight;")

    # Calculer la position de clic à 10% de la marge droite
    x_coordinate = int(window_width * 0.95)
    y_coordinate = int(window_height / 2)  # Position verticale au milieu de la fenêtre, ajustez selon vos besoins

    # Utiliser ActionChains pour effectuer un clic à la position calculée
    action = ActionChains(driver)
    action.move_by_offset(x_coordinate, y_coordinate).click().perform()


def export_factures(driver, first_date, last_date):

    success = True

    try:
        exporter = driver.find_element(By.XPATH, '//span[@class="MuiButton-label" and text()="Exporter"]')
        exporter.click()

        time.sleep(1)

        WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.XPATH, '//span[@class="MuiTypography-root MuiFormControlLabel-label MuiTypography-body1" and text()=".pdf"]'))
        )
        pdf = driver.find_element(By.XPATH, '//span[@class="MuiTypography-root MuiFormControlLabel-label MuiTypography-body1" and text()=".pdf"]')
        pdf.click()

        time.sleep(1)

        tags_input = driver.find_element(By.XPATH, '//input[@id="tags-filled"]')
        tags_input.send_keys("exporté app")
        time.sleep(1)
        tags_input.send_keys(Keys.ENTER)

        time.sleep(1)

        prev_files_list = os.listdir(DL_FOLDER_PATH_AUTO)
        boite_dialogue = driver.find_element(By.XPATH, '//div[@role="dialog" and @aria-describedby="alert-dialog-slide-description"]')

        valider_export = boite_dialogue.find_element(By.XPATH, '//button//span[@class="MuiButton-label" and text()="Exporter"]')
        driver.execute_script("arguments[0].click();", valider_export)
        
        WebDriverWait(driver, 60).until(lambda driver: len(os.listdir(DL_FOLDER_PATH_AUTO)) > len(prev_files_list))
        time.sleep(3)
        logger.error('Téléchargement terminé')

        for fichier in os.listdir(DL_FOLDER_PATH_AUTO):
            if fichier not in prev_files_list:
                #C'est l'archive, on la décompresse
                full_zip_file_path = os.path.join(DL_FOLDER_PATH_AUTO, fichier)

                with zipfile.ZipFile(full_zip_file_path, 'r') as zip_ref:
                    zip_ref.extractall(DL_FOLDER_PATH_AUTO)

                os.remove(full_zip_file_path)

        logger.error('Archive décompressée')

    except Exception as e:
        logger.error(f'Erreur lors de l\'export des factures : {e}')
        success = False

    return success


def main_digi():

    LAST_IMPORT_DATE = Constante.objects.get(pk="LAST_IMPORT_DATE_DIGIPHARMACIE")
    LISTE_FOURNISSEURS = ["Teva", "Arrow", "Alliance", "BIOGARAN", "EG LABO"]

    success = False

    if LAST_IMPORT_DATE:
        LAST_IMPORT_DATE = datetime.strptime(LAST_IMPORT_DATE.value, '%d/%m/%Y')
        #set import range of 1 week
        LAST_IMPORT_DATE = LAST_IMPORT_DATE + timedelta(days=-7)
    else:
        LAST_IMPORT_DATE = datetime(2023, 10, 1)

    # URL du site et du formulaire de connexion
    login_url = "https://app.digipharmacie.fr/login"
    username = "contact@pharmaciemichelet.fr"
    password = "200172vS1****++++"

    try:
        if not os.path.exists(DL_FOLDER_PATH_AUTO):
            os.makedirs(DL_FOLDER_PATH_AUTO)

        # Utiliser le navigateur Chrome (à remplacer par le navigateur de votre choix)
        chrome_options = webdriver.ChromeOptions()
        prefs = {'download.default_directory' : DL_FOLDER_PATH_AUTO}
        chrome_options.add_experimental_option('prefs', prefs)
        chrome_options.add_argument("--headless=new")
        driver = webdriver.Chrome(options=chrome_options)

        # Aller sur la page de connexion
        driver.get(login_url)

        time.sleep(2)

        handle_popups(driver)

        time.sleep(1)

        # Remplir le formulaire d'authentification
        username_input = driver.find_element(By.CSS_SELECTOR, "input[placeholder='Adresse email']")
        password_input = driver.find_element(By.CSS_SELECTOR, "input[placeholder='Mot de passe']")

        username_input.send_keys(username)
        password_input.send_keys(password)

        # Soumettre le formulaire
        password_input.send_keys(Keys.RETURN)

    except Exception as e:
        logger.error(f'Erreur lors de l\'initialisation du Webdriver ou lors du login : {e}')
        return False

    time.sleep(3)

    try:

        WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'table.MuiTable-root'))
        )
        time.sleep(1)

        try:
            effacer_filtres = driver.find_element(By.XPATH, "//span[text()='Effacer les filtres']")
            driver.execute_script("arguments[0].click();", effacer_filtres)
        except:  # noqa: E722
            print("no filter")

        time.sleep(1)

        emission = driver.find_element(By.XPATH, '//span[contains(text(), "Date d\'émission")]')
        driver.execute_script("arguments[0].click();", emission)

        time.sleep(1)

        input_start_date = driver.find_element(By.NAME, 'Depuis')
        if LAST_IMPORT_DATE < datetime.now().replace(hour=0, minute=0, second=0, microsecond=0):
            start_date = (LAST_IMPORT_DATE + timedelta(days=1)).strftime("%d/%m/%Y")
        else:
            start_date = datetime.now().strftime("%d/%m/%Y")
        input_start_date.send_keys(start_date)

        input_end_date = driver.find_element(By.NAME, 'Jusqu\'àu')
        end_date = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")
        input_end_date.send_keys(end_date)

        logger.error(f'Digipharmacie date range : {start_date} - {end_date}')

        time.sleep(2)

        fournisseurs = driver.find_element(By.XPATH, "//span[text()='Fournisseurs']")
        driver.execute_script("arguments[0].click();", fournisseurs)

        time.sleep(2)

        logger.error('Début boucle sur les fournisseurs')

        for i in range(len(LISTE_FOURNISSEURS)):
            logger.error(f"Ajout du fournisseur/labo {LISTE_FOURNISSEURS[i]}")

            input_fournisseurs = driver.find_element(By.XPATH, "//input[@name='Fournisseur']")
            driver.execute_script("arguments[0].value = '';", input_fournisseurs)
            input_fournisseurs.send_keys(LISTE_FOURNISSEURS[i])
            time.sleep(1)
            labo_trouve = driver.find_element(By.XPATH, f"//div[@class='ListItem']//div[text()='{LISTE_FOURNISSEURS[i]}']")
            time.sleep(1)
            driver.execute_script("arguments[0].click();", labo_trouve)
            time.sleep(1)

        logger.error('Fin boucle sur les fournisseurs')

        fournisseurs = driver.find_element(By.XPATH, "//span[text()='Fournisseurs']")
        driver.execute_script("arguments[0].click();", fournisseurs)

        time.sleep(1)

        nombre_factures = driver.find_element(By.XPATH, '//div[contains(text(), "Factures et Avoirs")]/following-sibling::div').text
        logger.error(f'Nombre de factures : {nombre_factures}')

        if nombre_factures != "-":
            success = export_factures(driver, start_date, end_date)
        else:
            success = True

    except Exception as e:
        logger.error(f'Erreur lors du traitement des factures fournisseurs : {e}')
    
    time.sleep(2)

    driver.quit()

    return success