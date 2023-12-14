from django.urls import path, include
from . import views
from django.contrib.auth import views as auth_views

app_name = "App"

urlpatterns = [
    path('', views.index, name='Accueil'),
    path('upload_factures/', views.upload_factures, name='upload_factures'),
    path('upload_catalogue_excel/', views.upload_catalogue_excel, name='upload_catalogue_excel'),
    path('afficher_tableau_synthese/', views.afficher_tableau_synthese, name='afficher_tableau_synthese'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name = 'login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]
