# #  product
import logging
import sys
import json
import pprint
from datetime import datetime
from math import ceil

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from dojo.filters import ProductFilter, ProductFindingFilter
from dojo.forms import ProductForm, EngForm, DeleteProductForm
from dojo.models import Product_Type, Finding, Product, Engagement, ScanSettings, Risk_Acceptance
from dojo.utils import get_page_items, add_breadcrumb, get_punchcard_data, get_system_setting
from dojo.models import *
from dojo.forms import *
#from jira import JIRA
from trello import TrelloApi
from dojo.tasks import *
from dojo.product import views as ds

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] %(levelname)s [%(name)s:%(lineno)d] %(message)s',
    datefmt='%d/%b/%Y %H:%M:%S',
    filename=settings.DOJO_ROOT + '/../django_app.log',
)
logger = logging.getLogger(__name__)


@csrf_exempt
def webhook(request):
    if request.method == 'POST':
        parsed = json.loads(request.body)
        if 'issue' in parsed.keys():
            jid = parsed['issue']['id']
            jissue = JIRA_Issue.objects.get(jira_id=jid)
            if jissue.finding is not None:
                finding = jissue.finding
                resolved = True
                if parsed['issue']['fields']['resolution'] == None:
                    resolved = False
                if finding.active == resolved:
                    if finding.active:
                        now = timezone.now()
                        finding.active = False
                        finding.mitigated = now
                        finding.endpoints.clear()
                    else:
                        finding.active = True
                        finding.mitigated = None
                        finding.save()
                    finding.save()
            """
            if jissue.engagement is not None:
                eng = jissue.engagement
                if parsed['issue']['fields']['resolution'] != None:
                    eng.active = False
                    eng.status = 'Completed'
                    eng.save()
           """
        else:
            comment_text = parsed['comment']['body']
            commentor = parsed['comment']['updateAuthor']['displayName']
            jid = parsed['comment']['self'].split('/')[7]
            jissue = JIRA_Issue.objects.get(jira_id=jid)
            finding = jissue.finding
            new_note = Notes()
            new_note.entry = '(%s): %s' % (commentor, comment_text)
            new_note.author = User.objects.get(username='JIRA')
            new_note.save()
            finding.notes.add(new_note)
            finding.save()
    return HttpResponse('')


@user_passes_test(lambda u: u.is_staff)
def new_trello(request):
    if request.method == 'POST':
        jform = TRELLOForm(request.POST, instance=TRELLO_Conf())
        if jform.is_valid():
            try:
                '''get the trello url for the token'''
                trello_api_key = '1c2f484151a65f7653422cc628a3246e'
                trello = TrelloApi(trello_api_key)
                token_url = trello.get_token_url('Defectdojo', expires='never', write_access=True)
                '''save config to db'''
                new_j = jform.save(commit=False)
                new_j.url = token_url
                new_j.save()
                messages.add_message(request,
                                     messages.SUCCESS,
                                     'Trello Configuration Successfully Created.',
                                     extra_tags='alert-success')
                return render(request, 'dojo/trello.html',
                  {'trello_api_key': trello_api_key})
            except:
                messages.add_message(request,
                                     messages.ERROR,
                                     'some error msg',
                                     extra_tags='alert-danger')
    else:
        jform = TRELLOForm()
        add_breadcrumb(title="New Trello Configuration", top_level=False, request=request)
    return render(request, 'dojo/new_trello.html',
                  {'jform': jform})

@user_passes_test(lambda u: u.is_staff)
def edit_trello(request, jid):
    jira = TRELLO_Conf.objects.get(pk=jid)
    if request.method == 'POST':
        jform = TRELLOForm(request.POST, instance=trello)
        if jform.is_valid():
            try:
                jira_server = jform.cleaned_data.get('url').rstrip('/')
                jira = JIRA(server=jira_server,
                            basic_auth=(jform.cleaned_data.get('username'), jform.cleaned_data.get('password')))

                new_j = jform.save(commit=False)
                new_j.url = jira_server
                new_j.save()
                messages.add_message(request,
                                     messages.SUCCESS,
                                     'Trello Configuration Successfully Created.',
                                     extra_tags='alert-success')
                return HttpResponseRedirect(reverse('trello', ))
            except:
                messages.add_message(request,
                                     messages.ERROR,
                                     'Unable to authenticate. Please check the URL, username, and password.',
                                     extra_tags='alert-danger')
    else:
        jform = TRELLOForm(instance=trello)
    add_breadcrumb(title="Edit Trello Configuration", top_level=False, request=request)

    return render(request,
                  'dojo/edit_trello.html',
                  {
                      'jform': jform,
                  })

@user_passes_test(lambda u: u.is_staff)
def delete_issue(request, find):
    j_issue = JIRA_Issue.objects.get(finding=find)
    jira = JIRA(server=jira_conf.url, basic_auth=(jira_conf.username, jira_conf.password))
    issue = jira.issue(j_issue.jira_id)
    issue.delete()

@user_passes_test(lambda u: u.is_staff)
def trello(request):
    confs = TRELLO_Conf.objects.all()
    add_breadcrumb(title="Trello List", top_level=not len(request.GET), request=request)
    return render(request,
                  'dojo/trello.html',
                  {'confs': confs,
                   })
