from django.conf.urls import url
from django.contrib import admin
from django.apps import apps
import views

urlpatterns = [
    url(r'^webhook', views.webhook, name='web_hook'),
    url(r'^trello/add', views.new_trello, name='add_trello'),
    url(r'^trello/(?P<jid>\d+)/edit$', views.edit_trello,
        name='edit_trello'),
    url(r'^trello$', views.trello, name='trello'), ]
