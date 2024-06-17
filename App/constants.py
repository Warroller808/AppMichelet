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
    "ARROW",
    "ARW",
    "TEVA ",
    " TS ",
    "CRISTERS",
    "SUNPHARMA",
    "VIATRIS",
    "ZYDUS"
]


NON_GENERIQUES = [
    #TEVA
    "AIROMIR",
    "AJOVY",
    "DELURSAN",
    "FURADANTINE",
    "LONQUEX",
    "PARALYOC",
    "MODIODAL",
    "QVAR",
    "TRANSULOSE",
    "SPASFON",
    "VOGALENE",
    "BETADINE",
    "TAREG ",
    " TAREG",
    "COLOPEG",
    "OROCAL",
    "PELMEG",
    "TRANSPIPEG",
    "XIMEPEG",

    #EG
    "DUOFILM",
    "SYNTHOLKINÉ",
    "BROCHOKOD",
    "MITOSYL",
    "FLEXITOL"
]


NON_REMBOURSABLES = [
    #TEVA
    "ATOVAQUONE",
    "PIRACETAM",
    "FINASTERIDE",
    "SILDENAFIL",
    "TADALAFIL",
    "GESTODENE",
    "DONEPEZIL",
    "GALANTAMINE",
    "MEMANTINE",

    "Sildénafil",
    "Finastéride",
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
    "CLINUTREN",
    "JELONET"
]


PRODUITS_LPP = [
    "BIFLEX",
    "LEGILET",
    "VENOFL",
]


OTC = [
    #TEVA
    "ACETYLCYSTEINE",
    "ACICLOVIR",
    "AMBROXOL",
    "CARBOCISTEINE",
    "CETIRIZINE",
    "CHLORHEXIDINE",
    "DICLOFENAC",
    "DOXYLAMINE",
    "EAU DE MER TEVA",
    "HEXETIDINE",
    "IBUPROFENE",
    "LOPERAMIDE",
    "LORATADINE",
    "OMEPRAZOLE",
    "PANTOPRAZOLE",
    "PARACETAMOL",
    "DIASTROLIB",
    "MONASENS",
    "VOGALIB",

    #EG
    "ACICLOVIR",
    "AMBROXOL",
    "AMOROLFINE",
    "BISACODYL",
    "CLOTRIMAZOLE",
    "Dexpanthénol",
    "DEXPANTHENOL",
    "DIOSMINE",
    "DOXYLAMINE",
    "GINGKO",
    "GINKGO",
    "Ibuprofène EG",
    "IBUPROFENE EG",
    "KENDIX",
    "OMEGA 3 EG",
    "PANTOPRAZOLE EG"
]


SPECIAL_CASES = {
    "HUMIRA": "<450€ tva 2,1%",
}
