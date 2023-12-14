from django.urls import path
from . import views

app_name = "App"

urlpatterns = [
    path('', views.index, name='Accueil'),
    path('upload_factures/', views.upload_factures, name='upload_factures'),
    path('upload_catalogue_excel/', views.upload_catalogue_excel, name='upload_catalogue_excel'),
    path('afficher_tableau_synthese/', views.afficher_tableau_synthese, name='afficher_tableau_synthese')
]
