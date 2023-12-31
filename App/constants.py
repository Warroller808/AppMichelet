from django.conf import settings
import os


DL_FOLDER_PATH = os.path.join(os.path.join(settings.BASE_DIR, "media"), "factures")
DL_FOLDER_PATH_MANUAL = os.path.join(DL_FOLDER_PATH, "manual_imports")
DL_FOLDER_PATH_AUTO = os.path.join(DL_FOLDER_PATH, "automatic_imports")


LABORATOIRES_GENERIQUES = [
    "BIOG",
    "BGR ",
    "BIOGARAN",
    "MYLAN",
    "SANDOZ",
    "SDZ ",
    "SAND ",
    "ZENTIVA",
    "ZTV ",
    "ZENT ",
    " EG ",
    " LEG "
    "ARROW",
    "ARW",
    "TEVA ",
    " TS ",
    "CRISTERS",
    "SUNPHARMA",
    "VIATRIS",
    "ZYDUS",
]


NON_GENERIQUES = [
    "SPASFON",
    "VOGALENE",
    "VOGALIB",
    "BETADINE",
    "TAREG",
    "COLOPEG",
    "RASAGILINE",
    "OROCAL",
    "PELMEG",
    "TRANSPIPEG",
    "XIMEPEG",
]


MARCHES_PRODUITS = [
    "TENA ",
    "SMITH & NEPHEW",
    "CUTIPLAST",
    "PRIMAPORE",
    "VISCOPASTE",
    "OPSITE",
    "INTRASITE",
    "MELOLIN",
    "ALGISITE",
    "BACTIGRAS",
    "IODOSORB",
    "ZOFF",
    "PROSHIELD",
    "ALLEVYN",
    "BD ",
    "BECTON",
    "GANZONI",
    "NESTLE ",
    "NUTRISENS",
    "THUASNE",
]
