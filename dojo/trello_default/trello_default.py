import requests
import json
from collections import OrderedDict
from dojo.models import TRELLO_Conf

# Script variables
HEADERS = {'content-type': 'application/json'}
URL_BASE = "https://api.trello.com/1/"


# Script methods
# Create the board
def create_default_board(api_key, token):

    url = URL_BASE + "boards/"
    params = {'key': api_key, 'token': token, 'name': 'DefectDojo findings','defaultLists': 'false',
              'desc': 'This is an automatically generated board from DefectDojo. ' +
              'This board contains all vulnerabilities, which are published through DefectDojo.'}
    board_data = request_helper(url, params)

    return board_data['id']


# Create the underlying lists
def create_default_lists(api_key, token, board_id):

    url = URL_BASE + "lists"
    names_dict = OrderedDict((('Back Log', ''), ('To Do', ''), ('In Progress', ''), ('Done', '')))

    for name in names_dict:
        params {'key': api_key, 'token': token, 'name': name, 'idBoard': board_id, 'pos': 'bottom'}
        tmp_list_data = request_helper(url, params)
        names_dict[name] = tmp_list_data['id']

    return names_dict


def create_default_labels(api_key, token, board_id):

    url = URL_BASE + "labels"
    labels = ('Critical', 'High', 'Medium', 'Low', 'Informational')
    colors = ('red', 'orange', 'yellow', 'blue', 'green')
    label_dict = {}

    for i in range(0, 4):
        params {'key': api_key,'token': token,'name': labels[i], 'color': colors[i], 'idBoard': board_id}
        tmp_label_data = request_helper(url, params)
        label_dict.update({labels[i]: tmp_label_data['id']})
    return label_dict


def new_trello_card(api_key, token, backlog_list_id, name, desc, label_id):

    url = URL_BASE + "cards"
    params = {'key': api_key,'token': token,'name': name, 'desc': desc, 'idList': backlog_list_id, 'idLabels': label_id}
    card_data = request_helper(url, params)

    return card_data['id']


def add_trello_card_comment(api_key, token, card_id, comment):

    url = URL_BASE + "cards/" + card_id + "/actions/comments/"
    params = params_builder({'text': comment})
    comment_data = request_helper(url, params)

    return comment_data


# Helper methods
def request_helper(url, params):
    response = requests.request(method="POST", url=url, data=json.dumps(params), headers=HEADERS)
    return response.json()


#def params_builder(dictionary):
#    tmp_params = PARAMS
#    tmp_params.update(dictionary)
#    return tmp_params


## Main
#boardId = create_default_board()
#print boardId
#
#all_lists = create_default_lists(boardId)
#print all_lists
#
#all_labels = create_default_labels(boardId)
#print all_labels
#
## make a test card
#trello_card_id = new_trello_card(backlog_list_id=all_lists['Back Log'],
#                              name='XXS Scripting vulnerability',
#                              desc='A XXS Scripting vulnerability was found, please take appropriate actions',
#                              label_id=all_labels['Critical'])
#comment = add_trello_card_comment(trello_card_id, "add a description for the finding here")