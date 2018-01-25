import calendar as tcalendar
import re
import binascii, os, hashlib
import json
from os import name

from Crypto.Cipher import AES
from calendar import monthrange
from datetime import date, datetime, timedelta
from math import pi, sqrt
from trello import TrelloApi

import vobject
import requests
from collections import OrderedDict
from dateutil.relativedelta import relativedelta, MO
from django.conf import settings
from django.core.mail import send_mail
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.urlresolvers import get_resolver, reverse
from django.contrib import messages
from django.db.models import Q, Sum, Case, When, IntegerField, Value, Count
from django.template.defaultfilters import pluralize
from django.template.loader import render_to_string
from django.utils import timezone
from jira import JIRA
from jira.exceptions import JIRAError
from dojo.models import Finding, Scan, Test, Test_Type, Engagement, Stub_Finding, Finding_Template, \
                        Report, Product, JIRA_PKey, JIRA_Issue, Dojo_User, User, Notes, \
                        TRELLO_PKey, TRELLO_board, TRELLO_items, TRELLO_list, TRELLO_card, TRELLO_label, TRELLO_Issue, \
                        FindingImage, Alerts, System_Settings, Notifications
from django_slack import slack_message
# from dojo.trello_default import trello_default


"""
Michael & Fatima:
Helper function for metrics
Counts the number of findings and the count for the products for each level of
severity for a given finding querySet
"""


def count_findings(findings):
    product_count = {}
    finding_count = {'low': 0, 'med': 0, 'high': 0, 'crit': 0}
    for f in findings:
        product = f.test.engagement.product
        if product in product_count:
            product_count[product][4] += 1
            if f.severity == 'Low':
                product_count[product][3] += 1
                finding_count['low'] += 1
            if f.severity == 'Medium':
                product_count[product][2] += 1
                finding_count['med'] += 1
            if f.severity == 'High':
                product_count[product][1] += 1
                finding_count['high'] += 1
            if f.severity == 'Critical':
                product_count[product][0] += 1
                finding_count['crit'] += 1
        else:
            product_count[product] = [0, 0, 0, 0, 0]
            product_count[product][4] += 1
            if f.severity == 'Low':
                product_count[product][3] += 1
                finding_count['low'] += 1
            if f.severity == 'Medium':
                product_count[product][2] += 1
                finding_count['med'] += 1
            if f.severity == 'High':
                product_count[product][1] += 1
                finding_count['high'] += 1
            if f.severity == 'Critical':
                product_count[product][0] += 1
                finding_count['crit'] += 1
    return product_count, finding_count


def findings_this_period(findings, period_type, stuff, o_stuff, a_stuff):
    # periodType: 0 - weeks
    # 1 - months
    now = timezone.now()
    for i in range(6):
        counts = []
        # Weeks start on Monday
        if period_type == 0:
            curr = now - relativedelta(weeks=i)
            start_of_period = curr - relativedelta(weeks=1, weekday=0,
                                                   hour=0, minute=0, second=0)
            end_of_period = curr + relativedelta(weeks=0, weekday=0, hour=0,
                                                 minute=0, second=0)
        else:
            curr = now - relativedelta(months=i)
            start_of_period = curr - relativedelta(day=1, hour=0,
                                                   minute=0, second=0)
            end_of_period = curr + relativedelta(day=31, hour=23,
                                                 minute=59, second=59)

        o_count = {'closed': 0, 'zero': 0, 'one': 0, 'two': 0,
                   'three': 0, 'total': 0}
        a_count = {'closed': 0, 'zero': 0, 'one': 0, 'two': 0,
                   'three': 0, 'total': 0}
        for f in findings:
            if f.mitigated is not None and end_of_period >= f.mitigated >= start_of_period:
                o_count['closed'] += 1
            elif f.mitigated is not None and f.mitigated > end_of_period and f.date <= end_of_period.date():
                if f.severity == 'Critical':
                    o_count['zero'] += 1
                elif f.severity == 'High':
                    o_count['one'] += 1
                elif f.severity == 'Medium':
                    o_count['two'] += 1
                elif f.severity == 'Low':
                    o_count['three'] += 1
            elif f.mitigated is None and f.date <= end_of_period.date():
                if f.severity == 'Critical':
                    o_count['zero'] += 1
                elif f.severity == 'High':
                    o_count['one'] += 1
                elif f.severity == 'Medium':
                    o_count['two'] += 1
                elif f.severity == 'Low':
                    o_count['three'] += 1
            elif f.mitigated is None and f.date <= end_of_period.date():
                if f.severity == 'Critical':
                    a_count['zero'] += 1
                elif f.severity == 'High':
                    a_count['one'] += 1
                elif f.severity == 'Medium':
                    a_count['two'] += 1
                elif f.severity == 'Low':
                    a_count['three'] += 1

        total = sum(o_count.values()) - o_count['closed']
        if period_type == 0:
            counts.append(
                start_of_period.strftime("%b %d") + " - " +
                end_of_period.strftime("%b %d"))
        else:
            counts.append(start_of_period.strftime("%b %Y"))
        counts.append(o_count['zero'])
        counts.append(o_count['one'])
        counts.append(o_count['two'])
        counts.append(o_count['three'])
        counts.append(total)
        counts.append(o_count['closed'])

        stuff.append(counts)
        o_stuff.append(counts[:-1])

        a_counts = []
        a_total = sum(a_count.values())
        if period_type == 0:
            a_counts.append(start_of_period.strftime("%b %d") + " - " + end_of_period.strftime("%b %d"))
        else:
            a_counts.append(start_of_period.strftime("%b %Y"))
        a_counts.append(a_count['zero'])
        a_counts.append(a_count['one'])
        a_counts.append(a_count['two'])
        a_counts.append(a_count['three'])
        a_counts.append(a_total)
        a_stuff.append(a_counts)


def add_breadcrumb(parent=None, title=None, top_level=True, url=None, request=None, clear=False):
    title_done = False
    if clear:
        request.session['dojo_breadcrumbs'] = None
        return
    else:
        crumbs = request.session.get('dojo_breadcrumbs', None)

    if top_level or crumbs is None:
        crumbs = [{'title': 'Home',
                   'url': reverse('home')}, ]
        if parent is not None and getattr(parent, "get_breadcrumbs", None):
            crumbs += parent.get_breadcrumbs()
        else:
            title_done = True
            crumbs += [{'title': title,
                        'url': request.get_full_path() if url is None else url}]
    else:
        resolver = get_resolver(None).resolve
        if parent is not None and getattr(parent, "get_breadcrumbs", None):
            obj_crumbs = parent.get_breadcrumbs()
            if title is not None:
                obj_crumbs += [{'title': title,
                                'url': request.get_full_path() if url is None else url}]
        else:
            title_done = True
            obj_crumbs = [{'title': title,
                           'url': request.get_full_path() if url is None else url}]

        for crumb in crumbs:
            crumb_to_resolve = crumb['url'] if '?' not in crumb['url'] else crumb['url'][
                                                                            :crumb['url'].index('?')]
            crumb_view = resolver(crumb_to_resolve)
            for obj_crumb in obj_crumbs:
                obj_crumb_to_resolve = obj_crumb['url'] if '?' not in obj_crumb['url'] else obj_crumb['url'][
                                                                                            :obj_crumb[
                                                                                                'url'].index(
                                                                                                '?')]
                obj_crumb_view = resolver(obj_crumb_to_resolve)

                if crumb_view.view_name == obj_crumb_view.view_name:
                    if crumb_view.kwargs == obj_crumb_view.kwargs:
                        if len(obj_crumbs) == 1 and crumb in crumbs:
                            crumbs = crumbs[:crumbs.index(crumb)]
                        else:
                            obj_crumbs.remove(obj_crumb)
                    else:
                        if crumb in crumbs:
                            crumbs = crumbs[:crumbs.index(crumb)]

        crumbs += obj_crumbs

    request.session['dojo_breadcrumbs'] = crumbs


def get_punchcard_data(findings, weeks_between, start_date):
    punchcard = list()
    ticks = list()
    highest_count = 0
    tick = 0
    week_count = 1

    # mon 0, tues 1, wed 2, thurs 3, fri 4, sat 5, sun 6
    # sat 0, sun 6, mon 5, tue 4, wed 3, thur 2, fri 1
    day_offset = {0: 5, 1: 4, 2: 3, 3: 2, 4: 1, 5: 0, 6: 6}
    for x in range(-1, weeks_between):
        # week starts the monday before
        new_date = start_date + relativedelta(weeks=x, weekday=MO(1))
        end_date = new_date + relativedelta(weeks=1)
        append_tick = True
        days = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
        for finding in findings:
	    try:
		    if new_date < datetime.combine(finding.date, datetime.min.time()).replace(tzinfo=timezone.get_current_timezone()) <= end_date:
			# [0,0,(20*.02)]
			# [week, day, weight]
			days[day_offset[finding.date.weekday()]] += 1
			if days[day_offset[finding.date.weekday()]] > highest_count:
			    highest_count = days[day_offset[finding.date.weekday()]]
	    except:
		if new_date < finding.date <= end_date:
			# [0,0,(20*.02)]
			# [week, day, weight]
			days[day_offset[finding.date.weekday()]] += 1
			if days[day_offset[finding.date.weekday()]] > highest_count:
			    highest_count = days[day_offset[finding.date.weekday()]]
		pass

        if sum(days.values()) > 0:
            for day, count in days.items():
                punchcard.append([tick, day, count])
                if append_tick:
                    ticks.append([tick, new_date.strftime("<span class='small'>%m/%d<br/>%Y</span>")])
                    append_tick = False
            tick += 1
        week_count += 1
    # adjust the size
    ratio = (sqrt(highest_count / pi))
    for punch in punchcard:
        punch[2] = (sqrt(punch[2] / pi)) / ratio

    return punchcard, ticks, highest_count

#5 params
def get_period_counts_legacy(findings, findings_closed, accepted_findings, period_interval, start_date,
                      relative_delta='months'):
    opened_in_period = list()
    accepted_in_period = list()
    opened_in_period.append(['Timestamp', 'Date', 'S0', 'S1', 'S2',
                             'S3', 'Total', 'Closed'])
    accepted_in_period.append(['Timestamp', 'Date', 'S0', 'S1', 'S2',
                               'S3', 'Total', 'Closed'])

    for x in range(-1, period_interval):
        if relative_delta == 'months':
            # make interval the first through last of month
            end_date = (start_date + relativedelta(months=x)) + relativedelta(day=1, months=+1, days=-1)
            new_date = (start_date + relativedelta(months=x)) + relativedelta(day=1)
        else:
            # week starts the monday before
            new_date = start_date + relativedelta(weeks=x, weekday=MO(1))
            end_date = new_date + relativedelta(weeks=1, weekday=MO(1))

        closed_in_range_count = findings_closed.filter(mitigated__range=[new_date, end_date]).count()

        if accepted_findings:
            risks_a = accepted_findings.filter(
                risk_acceptance__created__range=[datetime(new_date.year,
                                                          new_date.month, 1,
                                                          tzinfo=timezone.get_current_timezone()),
                                                 datetime(new_date.year,
                                                          new_date.month,
                                                          monthrange(new_date.year,
                                                                     new_date.month)[1],
                                                          tzinfo=timezone.get_current_timezone())])
        else:
            risks_a = None

        crit_count, high_count, med_count, low_count, closed_count = [0, 0, 0, 0, 0]
        for finding in findings:
            if new_date <= datetime.combine(finding.date, datetime.min.time()).replace(tzinfo=timezone.get_current_timezone()) <= end_date:
                if finding.severity == 'Critical':
                    crit_count += 1
                elif finding.severity == 'High':
                    high_count += 1
                elif finding.severity == 'Medium':
                    med_count += 1
                elif finding.severity == 'Low':
                    low_count += 1

        total = crit_count + high_count + med_count + low_count
        opened_in_period.append(
            [(tcalendar.timegm(new_date.timetuple()) * 1000), new_date, crit_count, high_count, med_count, low_count,
             total, closed_in_range_count])
        crit_count, high_count, med_count, low_count, closed_count = [0, 0, 0, 0, 0]
        if risks_a is not None:
            for finding in risks_a:
                if finding.severity == 'Critical':
                    crit_count += 1
                elif finding.severity == 'High':
                    high_count += 1
                elif finding.severity == 'Medium':
                    med_count += 1
                elif finding.severity == 'Low':
                    low_count += 1

        total = crit_count + high_count + med_count + low_count
        accepted_in_period.append(
            [(tcalendar.timegm(new_date.timetuple()) * 1000), new_date, crit_count, high_count, med_count, low_count,
             total])

    return {'opened_per_period': opened_in_period,
            'accepted_per_period': accepted_in_period}


def get_period_counts(active_findings, findings, findings_closed, accepted_findings, period_interval, start_date,
                      relative_delta='months'):
    start_date = datetime(start_date.year,
                          start_date.month, start_date.day,
                          tzinfo=timezone.get_current_timezone())
    opened_in_period = list()
    active_in_period = list()
    accepted_in_period = list()
    opened_in_period.append(['Timestamp', 'Date', 'S0', 'S1', 'S2',
                             'S3', 'Total', 'Closed'])
    active_in_period.append(['Timestamp', 'Date', 'S0', 'S1', 'S2',
                             'S3', 'Total', 'Closed'])
    accepted_in_period.append(['Timestamp', 'Date', 'S0', 'S1', 'S2',
                               'S3', 'Total', 'Closed'])

    for x in range(-1, period_interval):
        if relative_delta == 'months':
            # make interval the first through last of month
            end_date = (start_date + relativedelta(months=x)) + relativedelta(day=1, months=+1, days=-1)
            new_date = (start_date + relativedelta(months=x)) + relativedelta(day=1)
        else:
            # week starts the monday before
            new_date = start_date + relativedelta(weeks=x, weekday=MO(1))
            end_date = new_date + relativedelta(weeks=1, weekday=MO(1))

        closed_in_range_count = findings_closed.filter(mitigated__range=[new_date, end_date]).count()

        if accepted_findings:
            risks_a = accepted_findings.filter(
                risk_acceptance__created__range=[datetime(new_date.year,
                                                          new_date.month, 1,
                                                          tzinfo=timezone.get_current_timezone()),
                                                 datetime(new_date.year,
                                                          new_date.month,
                                                          monthrange(new_date.year,
                                                                     new_date.month)[1],
                                                          tzinfo=timezone.get_current_timezone())])
        else:
            risks_a = None

        crit_count, high_count, med_count, low_count, closed_count = [0, 0, 0, 0, 0]
        for finding in findings:
            try:
                if new_date <= datetime.combine(finding.date, datetime.min.time()).replace(tzinfo=timezone.get_current_timezone()) <= end_date:
                    if finding.severity == 'Critical':
                        crit_count += 1
                    elif finding.severity == 'High':
                        high_count += 1
                    elif finding.severity == 'Medium':
                        med_count += 1
                    elif finding.severity == 'Low':
                        low_count += 1
            except:
                if new_date <= finding.date <= end_date:
                    if finding.severity == 'Critical':
                        crit_count += 1
                    elif finding.severity == 'High':
                        high_count += 1
                    elif finding.severity == 'Medium':
                        med_count += 1
                    elif finding.severity == 'Low':
                        low_count += 1
                pass

        total = crit_count + high_count + med_count + low_count
        opened_in_period.append(
            [(tcalendar.timegm(new_date.timetuple()) * 1000), new_date, crit_count, high_count, med_count, low_count,
             total, closed_in_range_count])
        crit_count, high_count, med_count, low_count, closed_count = [0, 0, 0, 0, 0]
        if risks_a is not None:
            for finding in risks_a:
                if finding.severity == 'Critical':
                    crit_count += 1
                elif finding.severity == 'High':
                    high_count += 1
                elif finding.severity == 'Medium':
                    med_count += 1
                elif finding.severity == 'Low':
                    low_count += 1

        total = crit_count + high_count + med_count + low_count
        accepted_in_period.append(
            [(tcalendar.timegm(new_date.timetuple()) * 1000), new_date, crit_count, high_count, med_count, low_count,
             total])
        crit_count, high_count, med_count, low_count, closed_count = [0, 0, 0, 0, 0]
        for finding in active_findings:
            try:
		    if datetime.combine(finding.date, datetime.min.time()).replace(tzinfo=timezone.get_current_timezone()) <= end_date:
			if finding.severity == 'Critical':
			    crit_count += 1
			elif finding.severity == 'High':
			    high_count += 1
			elif finding.severity == 'Medium':
			    med_count += 1
			elif finding.severity == 'Low':
			    low_count += 1
	    except:
		if finding.date <= end_date:
			if finding.severity == 'Critical':
			    crit_count += 1
			elif finding.severity == 'High':
			    high_count += 1
			elif finding.severity == 'Medium':
			    med_count += 1
			elif finding.severity == 'Low':
			    low_count += 1
		pass
        total = crit_count + high_count + med_count + low_count
        active_in_period.append(
            [(tcalendar.timegm(new_date.timetuple()) * 1000), new_date, crit_count, high_count, med_count, low_count,
             total])

    return {'opened_per_period': opened_in_period,
            'accepted_per_period': accepted_in_period,
            'active_per_period': active_in_period}


def opened_in_period(start_date, end_date, pt):
    start_date = datetime(start_date.year,
                          start_date.month, start_date.day,
                          tzinfo=timezone.get_current_timezone())
    end_date = datetime(end_date.year,
                        end_date.month, end_date.day,
                        tzinfo=timezone.get_current_timezone())
    opened_in_period = Finding.objects.filter(date__range=[start_date, end_date],
                                              test__engagement__product__prod_type=pt,
                                              verified=True,
                                              false_p=False,
                                              duplicate=False,
                                              out_of_scope=False,
                                              mitigated__isnull=True,
                                              severity__in=('Critical', 'High', 'Medium', 'Low')).values(
        'numerical_severity').annotate(Count('numerical_severity')).order_by('numerical_severity')
    total_opened_in_period = Finding.objects.filter(date__range=[start_date, end_date],
                                                    test__engagement__product__prod_type=pt,
                                                    verified=True,
                                                    false_p=False,
                                                    duplicate=False,
                                                    out_of_scope=False,
                                                    mitigated__isnull=True,
                                                    severity__in=(
                                                        'Critical', 'High', 'Medium', 'Low')).aggregate(
        total=Sum(
            Case(When(severity__in=('Critical', 'High', 'Medium', 'Low'),
                      then=Value(1)),
                 output_field=IntegerField())))['total']

    oip = {'S0': 0,
           'S1': 0,
           'S2': 0,
           'S3': 0,
           'Total': total_opened_in_period,
           'start_date': start_date,
           'end_date': end_date,
           'closed': Finding.objects.filter(mitigated__range=[start_date, end_date],
                                            test__engagement__product__prod_type=pt,
                                            severity__in=(
                                                'Critical', 'High', 'Medium', 'Low')).aggregate(total=Sum(
               Case(When(severity__in=('Critical', 'High', 'Medium', 'Low'), then=Value(1)),
                    output_field=IntegerField())))['total'],
           'to_date_total': Finding.objects.filter(date__lte=end_date.date(),
                                                   verified=True,
                                                   false_p=False,
                                                   duplicate=False,
                                                   out_of_scope=False,
                                                   mitigated__isnull=True,
                                                   test__engagement__product__prod_type=pt,
                                                   severity__in=('Critical', 'High', 'Medium', 'Low')).count()}

    for o in opened_in_period:
        oip[o['numerical_severity']] = o['numerical_severity__count']

    return oip


def message(count, noun, verb):
    return ('{} ' + noun + '{} {} ' + verb).format(count, pluralize(count), pluralize(count, 'was,were'))


class FileIterWrapper(object):
    def __init__(self, flo, chunk_size=1024 ** 2):
        self.flo = flo
        self.chunk_size = chunk_size

    def next(self):
        data = self.flo.read(self.chunk_size)
        if data:
            return data
        else:
            raise StopIteration

    def __iter__(self):
        return self


def get_cal_event(start_date, end_date, summary, description, uid):
    cal = vobject.iCalendar()
    cal.add('vevent')
    cal.vevent.add('summary').value = summary
    cal.vevent.add(
        'description').value = description
    start = cal.vevent.add('dtstart')
    start.value = start_date
    end = cal.vevent.add('dtend')
    end.value = end_date
    cal.vevent.add('uid').value = uid
    return cal


def named_month(month_number):
    """
    Return the name of the month, given the number.
    """
    return date(1900, month_number, 1).strftime("%B")


def normalize_query(query_string,
                    findterms=re.compile(r'"([^"]+)"|(\S+)').findall,
                    normspace=re.compile(r'\s{2,}').sub):
    return [normspace(' ',
                      (t[0] or t[1]).strip()) for t in findterms(query_string)]


def build_query(query_string, search_fields):
    """ Returns a query, that is a combination of Q objects. That combination
    aims to search keywords within a model by testing the given search fields.

    """
    query = None  # Query to search for every search term
    terms = normalize_query(query_string)
    for term in terms:
        or_query = None  # Query to search for a given term in each field
        for field_name in search_fields:
            q = Q(**{"%s__icontains" % field_name: term})

            if or_query:
                or_query = or_query | q
            else:
                or_query = q

        if query:
            query = query & or_query
        else:
            query = or_query
    return query


def template_search_helper(fields=None, query_string=None):
    if not fields:
        fields = ['title', 'description', ]
    findings = Finding_Template.objects.all()

    if not query_string:
        return findings

    entry_query = build_query(query_string, fields)
    found_entries = findings.filter(entry_query)

    return found_entries


def get_page_items(request, items, page_size, param_name='page'):
    size = request.GET.get('page_size', page_size)
    paginator = Paginator(items, size)
    page = request.GET.get(param_name)
    try:
        page = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        page = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        page = paginator.page(paginator.num_pages)

    return page


def handle_uploaded_threat(f, eng):
    name, extension = os.path.splitext(f.name)
    with open(settings.MEDIA_ROOT + '/threat/%s%s' % (eng.id, extension),
              'wb+') as destination:
        for chunk in f.chunks():
            destination.write(chunk)
    eng.tmodel_path = settings.MEDIA_ROOT + '/threat/%s%s' % (eng.id, extension)
    eng.save()

def handle_uploaded_selenium(f, cred):
    name, extension = os.path.splitext(f.name)
    with open(settings.MEDIA_ROOT + '/selenium/%s%s' % (cred.id, extension),
              'wb+') as destination:
        for chunk in f.chunks():
            destination.write(chunk)
    cred.selenium_script = settings.MEDIA_ROOT + '/selenium/%s%s' % (cred.id, extension)
    cred.save()

#Gets a connection to a Jira server based on the finding
def get_jira_connection(finding):
    prod = Product.objects.get(engagement=Engagement.objects.get(test=finding.test))
    jpkey = JIRA_PKey.objects.get(product=prod)
    jira_conf = jpkey.conf

    jira = JIRA(server=jira_conf.url, basic_auth=(jira_conf.username, jira_conf.password))
    return jira

def jira_get_resolution_id(jira, issue, status):
    transitions = jira.transitions(issue)
    resolution_id = None
    for t in transitions:
        if t['name'] == "Resolve Issue":
            resolution_id = t['id']
            break
        if t['name'] == "Reopen Issue":
            resolution_id = t['id']
            break

    return resolution_id

def jira_change_resolution_id(jira, issue, id):
    jira.transition_issue(issue, id)

# Logs the error to the alerts table, which appears in the notification toolbar
def log_jira_alert(error, finding):
    create_notification(event='jira_update', title='Jira update issue', description='Finding: ' + str(finding.id) + ', ' + error,
                       icon='bullseye', source='Jira')

# Displays an alert for Jira notifications
def log_jira_message(text, finding):
    create_notification(event='jira_update', title='Jira update message', description=text + " Finding: " + str(finding.id),
                       url=reverse('view_finding', args=(finding.id,)),
                       icon='bullseye', source='Jira')

# Adds labels to a Jira issue
def add_labels(find, issue):
    #Update Label with Security
    issue.fields.labels.append(u'security')
    #Update the label with the product name (underscore)
    prod_name = find.test.engagement.product.name.replace(" ", "_")
    issue.fields.labels.append(prod_name)
    issue.update(fields={"labels": issue.fields.labels})

def jira_long_description(find_description, find_id, jira_conf_finding_text):
    return find_description + "\n\n*Dojo ID:* " + str(find_id) + "\n\n" + jira_conf_finding_text

def add_issue(find, push_to_jira):
    eng = Engagement.objects.get(test=find.test)
    prod =  Product.objects.get(engagement= eng)
    jpkey = JIRA_PKey.objects.get(product=prod)
    jira_conf = jpkey.conf

    if push_to_jira:
        if 'Active' in find.status() and 'Verified' in find.status():
            try:
                JIRAError.log_to_tempfile=False
                jira = JIRA(server=jira_conf.url, basic_auth=(jira_conf.username, jira_conf.password))
                if jpkey.component:
                    new_issue = jira.create_issue(project=jpkey.project_key, summary=find.title,
                                                  components=[{'name': jpkey.component}, ],
                                                  description=jira_long_description(find.long_desc(), find.id,
                                                                                    jira_conf.finding_text),
                                                  issuetype={'name': jira_conf.default_issue_type},
                                                  priority={'name': jira_conf.get_priority(find.severity)})
                else:
                    new_issue = jira.create_issue(project=jpkey.project_key, summary=find.title,
                                                  description=jira_long_description(find.long_desc(), find.id,
                                                                                    jira_conf.finding_text),
                                                  issuetype={'name': jira_conf.default_issue_type},
                                                  priority={'name': jira_conf.get_priority(find.severity)})
                j_issue = JIRA_Issue(jira_id=new_issue.id, jira_key=new_issue, finding=find)
                j_issue.save()
                issue = jira.issue(new_issue.id)

                #Add labels (security & product)
                add_labels(find, new_issue)
                #Upload dojo finding screenshots to Jira
                for pic in find.images.all():
                    jira_attachment(jira, issue, settings.MEDIA_ROOT + pic.image_large.name)

                    #if jpkey.enable_engagement_epic_mapping:
                    #      epic = JIRA_Issue.objects.get(engagement=eng)
                    #      issue_list = [j_issue.jira_id,]
                    #      jira.add_issues_to_epic(epic_id=epic.jira_id, issue_keys=[str(j_issue.jira_id)], ignore_epics=True)
            except JIRAError as e:
                log_jira_alert(e.text, find)
        else:
            log_jira_alert("Finding not active or verified.", find)

def add_trello_issue(find, push_to_trello):
    eng = Engagement.objects.get(test=find.test)
    prod =  Product.objects.get(engagement= eng)
    tpkey = TRELLO_PKey.objects.get(product=prod)
    trello_conf = tpkey.conf

    if push_to_trello:
        if 'Active' in find.status() and 'Verified' in find.status():
            try:
                t_issue = TRELLO_Issue(trello_id=new_issue.id, trello_key=new_issue, finding=find)
                t_issue.save()
            except JIRAError as e:
                log_jira_alert(e.text, find)
        else:
            log_jira_alert("Finding not active or verified.", find)

def jira_attachment(jira, issue, file, jira_filename=None):

    basename = file
    if jira_filename is None:
        basename = os.path.basename(file)

    # Check to see if the file has been uploaded to Jira
    if jira_check_attachment(issue, basename) == False:
        try:
            if jira_filename is not None:
                attachment = StringIO.StringIO()
                attachment.write(data)
                jira.add_attachment(issue=issue, attachment=attachment, filename=jira_filename)
            else:
                # read and upload a file
                with open(file, 'rb') as f:
                    jira.add_attachment(issue=issue, attachment=f)
        except JIRAError as e:
            log_jira_alert("Attachment: " + e.text, find)

def jira_check_attachment(issue, source_file_name):
    file_exists = False
    for attachment in issue.fields.attachment:
        filename=attachment.filename

        if filename == source_file_name:
            file_exists = True
            break

    return file_exists

def update_issue(find, old_status, push_to_jira):
    prod = Product.objects.get(engagement=Engagement.objects.get(test=find.test))
    jpkey = JIRA_PKey.objects.get(product=prod)
    jira_conf = jpkey.conf

    if push_to_jira:
        j_issue = JIRA_Issue.objects.get(finding=find)
        try:
            JIRAError.log_to_tempfile=False
            jira = JIRA(server=jira_conf.url, basic_auth=(jira_conf.username, jira_conf.password))
            issue = jira.issue(j_issue.jira_id)

            fields={}
            # Only update the component if it didn't exist earlier in Jira, this is to avoid assigning multiple components to an item
            if issue.fields.components:
                log_jira_alert("Component not updated, exists in Jira already. Update from Jira instead.", find)
            else:
                #Add component to the Jira issue
                component = [{'name': jpkey.component},]
                fields={"components": component}

            #Upload dojo finding screenshots to Jira
            for pic in find.images.all():
                jira_attachment(jira, issue, settings.MEDIA_ROOT + pic.image_large.name)

            issue.update(summary=find.title, description=jira_long_description(find.long_desc(), find.id, jira_conf.finding_text), priority={'name': jira_conf.get_priority(find.severity)}, fields=fields)

            #Add labels(security & product)
            add_labels(find, issue)
        except JIRAError as e:
            log_jira_alert(e.text, find)

        req_url =jira_conf.url+'/rest/api/latest/issue/'+ j_issue.jira_id+'/transitions'
        if 'Inactive' in find.status() or 'Mitigated' in find.status() or 'False Positive' in find.status() or 'Out of Scope' in find.status() or 'Duplicate' in find.status():
            if 'Active' in old_status:
                json_data = {'transition':{'id':jira_conf.close_status_key}}
                r = requests.post(url=req_url, auth=HTTPBasicAuth(jira_conf.username, jira_conf.password), json=json_data)
        elif 'Active' in find.status() and 'Verified' in find.status():
            if 'Inactive' in old_status:
                json_data = {'transition':{'id':jira_conf.open_status_key}}
                r = requests.post(url=req_url, auth=HTTPBasicAuth(jira_conf.username, jira_conf.password), json=json_data)

def close_epic(eng, push_to_jira):
    engagement = eng
    prod = Product.objects.get(engagement=engagement)
    jpkey = JIRA_PKey.objects.get(product=prod)
    jira_conf = jpkey.conf
    if jpkey.enable_engagement_epic_mapping and push_to_jira:
        j_issue = JIRA_Issue.objects.get(engagement=eng)
        req_url = jira_conf.url+'/rest/api/latest/issue/'+ j_issue.jira_id+'/transitions'
        j_issue = JIRA_Issue.objects.get(engagement=eng)
        json_data = {'transition':{'id':jira_conf.close_status_key}}
        r = requests.post(url=req_url, auth=HTTPBasicAuth(jira_conf.username, jira_conf.password), json=json_data)


def push_finding_to_trello():
    temp = 'temp'


# Helper methods
def request_helper(url, params, HEADERS, requestMethod,):
    if requestMethod == "PUT":
        response = requests.request(method=requestMethod, url=url, params=params, headers=HEADERS)
        return response
    else:
        response = requests.request(method="POST", url=url, data=json.dumps(params), headers=HEADERS)
        return response.json()

def params_builder(dictionary, PARAMS):
    tmp_params = PARAMS
    tmp_params.update(dictionary)
    return tmp_params


def description_builder(description, vuln_endpoint, mitigation, impact, references, notes):
    # kwargs need to have the same name corresponding with the arguments array below.
    # arguments = ['description', 'vuln_endpoint', 'mitigation', 'impact', 'references', 'notes']
    # headlines = ['Description', 'Vulnerable Endpoints', 'Mitigation', 'Impact', 'References', 'Notes']

    desc = ""
    desc += '***Description***\n'
    desc += description + '\n\n'
    desc += '***Vulnerable Endpoints***\n'
    desc += str(vuln_endpoint) + '\n\n'
    desc += '***Mitigation***\n'
    desc += mitigation + '\n\n'
    desc += '***Description***\n'
    desc += description + '\n\n'
    desc += '***Impact***\n'
    desc += impact + '\n\n'
    desc += '***References***\n'
    desc += references + '\n\n'
    desc += '***Notes***\n'
    desc += str(notes) + '\n\n'

    return desc


def create_default_board(HEADERS,PARAMS,URL_BASE,new_finding):

    test = Test.objects.get(id=new_finding.test_id)

    testType = Test_Type.objects.get(id = test.test_type_id)

    url = URL_BASE + "boards/"
    params = params_builder({'name': 'DefectDojo - ' + testType.name,
                             'defaultLists': 'false',
                             'desc': 'This is an automatically generated board from DefectDojo. ' +
                             'This board contains all vulnerabilities, which are published through DefectDojo.'}, PARAMS)
    board_data = request_helper(url, params, HEADERS, requestMethod="POST")

    return board_data


# Create the underlying lists
def create_default_lists(boardId, HEADERS,PARAMS,URL_BASE):

    url = URL_BASE + "lists"
    names_dict = OrderedDict((('Back Log', ''), ('To Do', ''), ('In Progress', ''), ('Done', '')))

    for name in names_dict:
        params = params_builder({'name': name, 'idBoard': boardId, 'pos': 'bottom'}, PARAMS)
        tmp_list_data = request_helper(url, params, HEADERS, requestMethod="POST")

        #save new list to db
        new_trello_list = TRELLO_list(list_name = name, list_id = tmp_list_data['id'], board_id=boardId)
        new_trello_list.save()

        names_dict[name] = tmp_list_data['id']

    return names_dict


# Create the configurated lists
#def create_conf_lists(board_id, conf, HEADERS,PARAMS,URL_BASE):

#    url = URL_BASE + "lists"
#    names_dict = OrderedDict((('Back Log', ''), ('To Do', ''), ('In Progress', ''), ('Done', '')))

#    for name in names_dict:
#        params = params_builder({'name': name, 'idBoard': board_id, 'pos': 'bottom'}, PARAMS)
#        tmp_list_data = request_helper(url, params, HEADERS)
#        names_dict[name] = tmp_list_data['id']
#        new_trello_list = TRELLO_list()

#    return names_dict


def create_default_labels(boardId, HEADERS,PARAMS,URL_BASE):

    url = URL_BASE + "labels"
    labels = ('Critical', 'High', 'Medium', 'Low', 'Informational')
    colors = ('red', 'orange', 'yellow', 'blue', 'green')
    label_dict = {}

    for i in range(0, len(labels)):
        params = params_builder({'name': labels[i], 'color': colors[i], 'idBoard': boardId}, PARAMS)
        tmp_label_data = request_helper(url, params, HEADERS, requestMethod="POST")

        #save labels to db
        new_trello_label = TRELLO_label(label_name = labels[i], label_color = colors[i], label_id = tmp_label_data['id'], board_id=boardId)
        new_trello_label.save()

        label_dict.update({labels[i]: tmp_label_data['id']})
    return label_dict


def new_trello_card(list_id, name, desc, label_id, HEADERS,PARAMS,URL_BASE):

    url = URL_BASE + "cards"
    params = params_builder({'name': name, 'desc': desc, 'idList': list_id, 'idLabels': label_id}, PARAMS)
    card_data = request_helper(url, params, HEADERS, requestMethod="POST")

    return card_data['id']


def update_trello_card(card_id, name, desc, label_id, std_headers, std_params, url_base,trello):

    url = url_base + "cards/" + str(card_id)
    params = params_builder({'name': name, 'desc': desc, 'idLabels': label_id}, std_params)

    put_card = request_helper(url, params, std_headers, requestMethod="PUT")
    #trello_board = trello.boards.new(put_card)
    return put_card


def update_trello_issue(new_finding, tconf):
    #trello init
    API_KEY = tconf.api_key
    TOKEN = tconf.token
    HEADERS = {'content-type': 'application/json'}
    PARAMS = {'key': API_KEY, 'token': TOKEN}
    URL_BASE = "https://api.trello.com/1/"
    trello = TrelloApi(API_KEY)
    trello.set_token(TOKEN)
    boardName = 'scan'

    #check if testboard exists if true push to existing board else make new board and push
    trello_item = TRELLO_items.objects.filter(test_id = new_finding.test_id).exists()

    if trello_item:
        #condition returns true, finding exists
        trello_finding = TRELLO_items.objects.filter(finding_id = new_finding.id)
        if trello_finding.exists():
            #update finding in trello
            #trello_board = trello.boards.new('update')
            #get boardID
            trello_obj= TRELLO_items.objects.filter(test_id=new_finding.test_id).first()
            trello_boardId = trello_obj.trello_board_id
            #get listID
            trello_listId = TRELLO_list.objects.get(board_id=trello_boardId, list_name='Back Log')
            #get cardID
            trello_card_id = trello_finding.get(finding_id = new_finding.id);
            trello_label = TRELLO_label.objects.get(board_id=trello_boardId, label_name=new_finding.severity)
            new_card_description = description_builder(description=new_finding.description,
                                                       vuln_endpoint=new_finding.endpoints,
                                                       mitigation=new_finding.mitigation,
                                                       impact=new_finding.impact,
                                                       references=new_finding.references,
                                                       notes=new_finding.notes)
                                                 # description, vuln_endpoint, mitigation, impact, references, notes
            updated_trello_card = update_trello_card(card_id=trello_card_id.card_id,
                                                     name=new_finding.title,
                                                     desc=new_card_description,
                                                     label_id=trello_label.label_id,
                                                     std_headers=HEADERS,
                                                     std_params=PARAMS,
                                                     url_base=URL_BASE,
                                                     trello=trello)
            #trello_board = trello.boards.new('test2')
            #trello_board = trello.boards.new(URL_BASE)
        else:
            #push new finding to trello
            #trello_board = trello.boards.new('new finding')
            #get boardID
            trello_item = TRELLO_items.objects.filter(test_id = new_finding.test_id).first()
            trello_boardId = trello_item.trello_board_id
            #get listID
            trello_list = TRELLO_list.objects.get(board_id=trello_boardId,list_name='Back Log')
            #get label
            trello_label = TRELLO_label.objects.get(board_id=trello_boardId,label_name=new_finding.severity)
            new_card_description = description_builder(description=new_finding.description,
                                                       vuln_endpoint=new_finding.endpoints,
                                                       mitigation=new_finding.mitigation,
                                                       impact=new_finding.impact,
                                                       references=new_finding.references,
                                                       notes=new_finding.notes)
            #push new finding to trello
            trello_card = new_trello_card(
                        trello_list.list_id,
                        new_finding.title,
                        new_card_description,
                        trello_label.label_id,HEADERS,PARAMS,URL_BASE)
            #save card to db save new trello item
            new_trello_item = TRELLO_items(finding_id=new_finding.id, trello_board_id=trello_boardId,test_id=new_finding.test_id,card_id=trello_card)
            new_trello_item.save()
            add_trello_card = TRELLO_card(card_name=new_finding.title, list_id=trello_list.list_id, description=new_finding.description, label_id=trello_label.label_id, card_id=trello_card)
            add_trello_card.save()
    else:
        #condition returns false, item does not exist and a new board has to be created
        #make new trello board
        #trello_board = trello.boards.new(boardName) // old board creation
        trello_board = create_default_board(HEADERS,PARAMS,URL_BASE,new_finding)
        #define trello attributes
        board_id = trello_board.get('id')
        board_name = trello_board.get('name')
        board_url = trello_board.get('url')
        board_shortUrl = trello_board.get('shortUrl')
        #save new board to db
        new_trello_board = TRELLO_board(trello_board_id=board_id,trello_board_name=board_name,shortUrl=board_url,url = board_shortUrl)
        new_trello_board.save()
        #make the default lists
        trello_lists = create_default_lists(board_id, HEADERS,PARAMS,URL_BASE)
        #make the default labels
        trello_default_labels = create_default_labels(board_id, HEADERS,PARAMS,URL_BASE)
        #push finding to newly created board
        trello_card = new_trello_card(
                        trello_lists['Back Log'],
                        new_finding.title,
                        new_finding.description,
                        trello_default_labels['Critical'],HEADERS,PARAMS,URL_BASE)
        #save new trello item
        new_trello_item = TRELLO_items(finding_id=new_finding.id, trello_board_id=board_id,test_id=new_finding.test_id,card_id=trello_card)
        new_trello_item.save()
        add_trello_card = TRELLO_card(card_name=new_finding.title, list_id=trello_lists['Back Log'], description=new_finding.description, card_id=trello_card)
        add_trello_card.save()


def close_epic(eng, push_to_jira):
    engagement = eng
    prod = Product.objects.get(engagement=engagement)
    jpkey = JIRA_PKey.objects.get(product=prod)
    jira_conf = jpkey.conf
    if jpkey.enable_engagement_epic_mapping and push_to_jira:
        j_issue = JIRA_Issue.objects.get(engagement=eng)
        req_url = jira_conf.url+'/rest/api/latest/issue/'+ j_issue.jira_id+'/transitions'
        j_issue = JIRA_Issue.objects.get(engagement=eng)
        json_data = {'transition':{'id':jira_conf.close_status_key}}
        r = requests.post(url=req_url, auth=HTTPBasicAuth(jira_conf.username, jira_conf.password), json=json_data)


def update_epic(eng, push_to_jira):
    engagement = eng
    prod = Product.objects.get(engagement=engagement)
    jpkey = JIRA_PKey.objects.get(product=prod)
    jira_conf = jpkey.conf
    if jpkey.enable_engagement_epic_mapping and push_to_jira:
        jira = JIRA(server=jira_conf.url, basic_auth=(jira_conf.username, jira_conf.password))
        j_issue = JIRA_Issue.objects.get(engagement=eng)
        issue = jira.issue(j_issue.jira_id)
        issue.update(summary=eng.name, description=eng.name)

def add_epic(eng, push_to_jira):
    engagement = eng
    prod = Product.objects.get(engagement=engagement)
    jpkey = JIRA_PKey.objects.get(product=prod)
    jira_conf = jpkey.conf
    if jpkey.enable_engagement_epic_mapping and push_to_jira:
        issue_dict = {
            'project': {'key': jpkey.project_key},
            'summary': engagement.name,
            'description' : engagement.name,
            'issuetype': {'name': 'Epic'},
            'customfield_' + str(jira_conf.epic_name_id) : engagement.name,
            }
        jira = JIRA(server=jira_conf.url, basic_auth=(jira_conf.username, jira_conf.password))
        new_issue = jira.create_issue(fields=issue_dict)
        j_issue = JIRA_Issue(jira_id=new_issue.id, jira_key=new_issue, engagement=engagement)
        j_issue.save()

def add_comment(find, note, force_push=False):
    prod = Product.objects.get(engagement=Engagement.objects.get(test=find.test))
    jpkey = JIRA_PKey.objects.get(product=prod)
    jira_conf = jpkey.conf
    if jpkey.push_notes or force_push == True:
        jira = JIRA(server=jira_conf.url, basic_auth=(jira_conf.username, jira_conf.password))
        j_issue = JIRA_Issue.objects.get(finding=find)
        jira.add_comment(j_issue.jira_id, '(%s): %s' % (note.author.get_full_name(), note.entry))

def send_review_email(request, user, finding, users, new_note):
    recipients = [u.email for u in users]
    msg = "\nGreetings, \n\n"
    msg += "{0} has requested that you please review ".format(str(user))
    msg += "the following finding for accuracy:"
    msg += "\n\n" + finding.title
    msg += "\n\nIt can be reviewed at " + request.build_absolute_uri(reverse("view_finding", args=(finding.id,)))
    msg += "\n\n{0} provided the following details:".format(str(user))
    msg += "\n\n" + new_note.entry
    msg += "\n\nThanks\n"

    send_mail('DefectDojo Finding Review Request',
              msg,
              user.email,
              recipients,
              fail_silently=False)
    pass

def process_notifications(request, note, parent_url, parent_title):
    regex = re.compile(r'(?:\A|\s)@(\w+)\b')
    usernames_to_check = set([un.lower() for un in regex.findall(note.entry)])
    users_to_notify=[User.objects.filter(username=username).get()
                   for username in usernames_to_check if User.objects.filter(is_active=True, username=username).exists()] #is_staff also?
    user_posting=request.user

    create_notification(event='user_mentioned',
                        section=parent_title,
                        note=note,
                        user=request.user,
                        title='%s mentioned you in a note' % request.user,
                        url=parent_url,
                        icon='commenting',
                        recipients=users_to_notify)

def send_atmention_email(user, users, parent_url, parent_title, new_note):
    recipients=[u.email for u in users]
    msg = "\nGreetings, \n\n"
    msg += "User {0} mentioned you in a note on {1}".format(str(user),parent_title)
    msg += "\n\n" + new_note.entry
    msg += "\n\nIt can be reviewed at " + parent_url
    msg += "\n\nThanks\n"
    send_mail('DefectDojo - {0} @mentioned you in a note'.format(str(user)),
          msg,
          user.email,
          recipients,
          fail_silently=False)

def encrypt(key, iv, plaintext):
    text = ""
    if plaintext != "" and plaintext != None:
        aes = AES.new(key, AES.MODE_CBC, iv, segment_size=128)
        plaintext = _pad_string(plaintext)
        encrypted_text = aes.encrypt(plaintext)
        text = binascii.b2a_hex(encrypted_text).rstrip()
    return text

def decrypt(key, iv, encrypted_text):
    aes = AES.new(key, AES.MODE_CBC, iv, segment_size=128)
    encrypted_text_bytes = binascii.a2b_hex(encrypted_text)
    decrypted_text = aes.decrypt(encrypted_text_bytes)
    decrypted_text = _unpad_string(decrypted_text)
    return decrypted_text

def _pad_string(value):
    length = len(value)
    pad_size = 16 - (length % 16)
    return value.ljust(length + pad_size, '\x00')

def _unpad_string(value):
    if value != "" and value != None:
        while value[-1] == '\x00':
            value = value[:-1]
    return value

def dojo_crypto_encrypt(plaintext):
    key = None
    key = get_db_key()

    iv =  os.urandom(16)
    return prepare_for_save(iv, encrypt(key, iv, plaintext.encode('ascii', 'ignore')))

def prepare_for_save(iv, encrypted_value):
    stored_value = None

    if encrypted_value != "" and encrypted_value != None:
        binascii.b2a_hex(encrypted_value).rstrip()
        stored_value = "AES.1:" + binascii.b2a_hex(iv) + ":" + encrypted_value
    return stored_value

def get_db_key():
    db_key = None
    if hasattr(settings, 'DB_KEY'):
        db_key = settings.DB_KEY
        db_key = binascii.b2a_hex(hashlib.sha256(db_key).digest().rstrip())[:32]

    return db_key

def prepare_for_view(encrypted_value):

    key = None
    decrypted_value = ""
    if encrypted_value != None:
        key = get_db_key()
        encrypted_values = encrypted_value.split(":")

        if len(encrypted_values) > 1:
            type = encrypted_values[0]

            iv = binascii.a2b_hex(encrypted_values[1])
            value = encrypted_values[2]

            try:
                decrypted_value = decrypt(key, iv, value)
                decrypted_value.decode('ascii')
            except UnicodeDecodeError:
                decrypted_value = ""

    return decrypted_value

def get_system_setting(setting):
    try:
        system_settings = System_Settings.objects.get()
    except:
        system_settings = System_Settings()

    return getattr(system_settings, setting, None)


def create_notification(event=None, **kwargs):
    def create_notification_message(event, notification_type):
        template = 'notifications/%s.tpl' % event.replace('/', '')
        kwargs.update({'type':notification_type})

        try:
            notification = render_to_string(template, kwargs)
        except:
            notification = render_to_string('notifications/other.tpl', kwargs)

        return notification

    def send_slack_notification(channel):
        try:
            res = requests.request(method='POST', url='https://slack.com/api/chat.postMessage',
                             data={'token':get_system_setting('slack_token'),
                                   'channel':channel,
                                   'username':get_system_setting('slack_username'),
                                   'text':create_notification_message(event, 'slack')})
        except Exception as e:
            log_alert(e)
            pass

    def send_hipchat_notification(channel):
        try:
            # We use same template for HipChat as for slack
            res = requests.request(method='POST',
                            url='https://%s/v2/room/%s/notification?auth_token=%s' % (get_system_setting('hipchat_site'), channel, get_system_setting('hipchat_token')),
                            data={'message':create_notification_message(event, 'slack'),
                                  'message_format':'text'})
            print res
        except Exception as e:
            log_alert(e)
            pass

    def send_mail_notification(address):
        subject = '%s notification' % get_system_setting('team_name')
        if 'title' in kwargs:
            subject += ': %s' % kwargs['title']
        try:
            send_mail(subject,
                    create_notification_message(event, 'mail'),
                    get_system_setting('mail_notifications_from'),
                    [address],
                    fail_silently=False)
        except Exception as e:
            log_alert(e)
            pass

    def send_alert_notification(user=None):
        icon = kwargs.get('icon', 'info-circle')
        alert = Alerts(user_id=user, 
                       title=kwargs.get('title'),
                       description=create_notification_message(event, 'alert'),
                       url=kwargs.get('url', reverse('alerts')),
                       icon=icon, 
                       source=Notifications._meta.get_field(event).verbose_name.title())
        alert.save()


    def log_alert(e):
        alert = Alerts(user_id=Dojo_User.objects.get(is_superuser=True), title='Notification issue', description="%s" % e, icon="exclamation-triangle", source="Notifications")
        alert.save()

    # Global notifications
    try:
        notifications = Notifications.objects.get(user=None)
    except Exception as e:
        notifications = Notifications()

    slack_enabled = get_system_setting('enable_slack_notifications')
    hipchat_enabled = get_system_setting('enable_hipchat_notifications')
    mail_enabled = get_system_setting('enable_mail_notifications')

    if slack_enabled and 'slack' in getattr(notifications, event):
        send_slack_notification(get_system_setting('slack_channel'))

    if hipchat_enabled and 'hipchat' in getattr(notifications, event):
        send_hipchat_notification(get_system_setting('hipchat_channel'))

    if mail_enabled and 'mail' in getattr(notifications, event):
        send_slack_notification(get_system_setting('mail_notifications_from'))

    if 'alert' in getattr(notifications, event, None):
        send_alert_notification()

    # Personal notifications
    if 'recipients' in kwargs:
        users = User.objects.filter(username__in=kwargs['recipients'])
    else:
        users = User.objects.filter(is_superuser=True)
    for user in users:
        try:
            notifications = Notifications.objects.get(user=user)
        except Exception as e:
            notifications = Notifications()

        if slack_enabled and 'slack' in getattr(notifications, event) and user.usercontactinfo.slack_username is not None:
            send_slack_notification('@%s' % user.usercontactinfo.slack_username)

        # HipChat doesn't seem to offer direct message functionality, so no HipChat PM functionality here...

        if mail_enabled and 'mail' in getattr(notifications, event):
            send_mail_notification(user.email)
                
        if 'alert' in getattr(notifications, event):
            send_alert_notification(user)
                