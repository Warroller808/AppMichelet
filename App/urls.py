from django.urls import path, include
from . import views
from django.contrib.auth import views as auth_views

app_name = "App"

urlpatterns = [
    path('', views.index, name='Accueil'),
    path('upload_factures/', views.upload_factures, name='upload_factures'),
    path('import_auto/', views.lancer_import_auto, name='import_auto'),
    path('upload_catalogue_excel/', views.upload_catalogue_excel, name='upload_catalogue_excel'),
    path('tableau_synthese/', views.tableau_synthese, name='tableau_synthese'),
    path('tableau_generiques/', views.tableau_generiques, name='tableau_generiques'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name = 'login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]
