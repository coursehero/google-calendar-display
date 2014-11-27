from apiclient.discovery import build
from oauth2client.client import OAuth2WebServerFlow

import httplib2

import gflags
import httplib2

from apiclient.discovery import build
from oauth2client.file import Storage
from oauth2client.client import OAuth2WebServerFlow
from oauth2client.tools import run

from datetime import datetime
from datetime import timedelta
import pytz
import dateutil.parser
import sys
import os
import json

from flask import Flask
from flask import render_template
app = Flask(__name__)

import calendar_config

FLAGS = gflags.FLAGS

# had to install:
# sudo apt-get update
# sudo apt-get install python-pip
# sudo pip install --upgrade google-api-python-client python-gflags python-dateutil Flask pytz

# Set up a Flow object to be used if we need to authenticate. This
# sample uses OAuth 2.0, and we set up the OAuth2WebServerFlow with
# the information it needs to authenticate. Note that it is called
# the Web Server Flow, but it can also handle the flow for native
# applications
# The client_id and client_secret can be found in Google Developers Console
FLOW = OAuth2WebServerFlow(
    client_id=calendar_config.CLIENT_ID,
    client_secret=calendar_config.CLIENT_SECRET,
    scope=calendar_config.SCOPE,
    user_agent=calendar_config.USER_AGENT)

# To disable the local server feature, uncomment the following line:
# FLAGS.auth_local_webserver = False

# If the Credentials don't exist or are invalid, run through the native client
# flow. The Storage object will ensure that if successful the good
# Credentials will get written back to a file.
storage = Storage('calendar.dat')
credentials = storage.get()
if credentials is None or credentials.invalid == True:
  credentials = run(FLOW, storage)

# Create an httplib2.Http object to handle our HTTP requests and authorize it
# with our good Credentials.
http = httplib2.Http()
http = credentials.authorize(http)

# Build a service object for interacting with the API. Visit
# the Google Developers Console
# to get a developerKey for your own application.
service = build(serviceName='calendar', version='v3', http=http,
       developerKey=calendar_config.DEVELOPER_KEY)

la = pytz.timezone("America/Los_Angeles")

def create_time_string(dt):
    if not dt:
        return None
    hours, remainder = divmod(dt.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    h = 'hours'
    m = 'minutes'
    if hours == 1:
        h = 'hour'
    if minutes == 1:
        m = 'minute'
    if hours == 0:
       return '%s %s' % (minutes, m)
    else:
        return '%s %s and %s %s' % (hours, h, minutes, m)

# This method has a very sub-optimal approach to time zones.
@app.route('/calendars')
def calendars():
    calendars = {}
    items = []
    free_rooms = []
    events = []
    upcoming = []

    now = la.localize(datetime.now())
    start_time = now - timedelta(hours=8)
    end_time = start_time + timedelta(hours=8)

    calendar_list = service.calendarList().list().execute()
    for calendar_list_entry in calendar_list['items']:
        if calendar_list_entry['id'] not in calendar_config.EXCLUSIONS:
            calendars[calendar_list_entry['id']] = calendar_list_entry['summary']
            items.append({'id': calendar_list_entry['id']})
            free_rooms.append(calendar_list_entry['id'])

    # store this to a local file
    with open('calendars.json', mode='w') as calendar_file:
        json.dump({value: key for key, value in calendars.items()}, calendar_file)

    free_busy = service.freebusy().query(body={"timeMin": start_time.isoformat(), 
        "timeMax": end_time.isoformat(), 
        "items":items}).execute()

    for calendar in free_busy['calendars']:
        data = free_busy['calendars'][calendar]
        if data['busy']:
            busy = data['busy'][0]
            start = dateutil.parser.parse(busy['start']) - timedelta(hours=8)
            end = dateutil.parser.parse(busy['end']) - timedelta(hours=8)
            diff = start - (now - timedelta(hours=16))

            event = {'room': calendars[calendar], 
                     'start': start.strftime("%l:%M%p"), 
                     'end': end.strftime("%l:%M%p")}

            if diff < timedelta(minutes=5):
                events.append(event)
                free_rooms.remove(calendar)
            elif diff < timedelta(minutes=35):
                upcoming.append(event)
                free_rooms.remove(calendar)

    return render_template('calendars.html', 
                           events=events, 
                           upcoming=upcoming,
                           now=start_time.strftime("%A %e %B %Y, %l:%M%p"),
                           free_rooms=[calendars[f] for f in free_rooms])

def get_events(room_name):
    items = []
    now = datetime.utcnow()

    la_offset = la.utcoffset(datetime.utcnow())
    now = now + la_offset

    start_time = datetime(year=now.year, month=now.month, day=now.day, tzinfo=la)
    end_time = start_time + timedelta(days=1)

    print "Running at", now.strftime("%A %e %B %Y, %l:%M%p")
    print "Room name", room_name

    if not os.path.isfile('calendars.json'):
        # this is duplicated from the calendars() method
        calendars = {}
        calendar_list = service.calendarList().list().execute()
        for calendar_list_entry in calendar_list['items']:
            if calendar_list_entry['id'] not in calendar_config.EXCLUSIONS:
                calendars[calendar_list_entry['id']] = calendar_list_entry['summary']

        # store this to a local file
        with open('calendars.json', mode='w') as calendar_file:
            json.dump({value: key for key, value in calendars.items()}, calendar_file)

    with open('calendars.json', 'r') as f:
        calendars = json.load(f)

    room_id = calendars[room_name]

    events = service.events().list(
    	calendarId=room_id,
    	orderBy='startTime',
    	singleEvents=True,
    	timeMin=start_time.isoformat(),
    	timeMax=end_time.isoformat()
    ).execute()

    next_start = None
    next_end = None
    status = "FREE"

    for event in events['items']:
        start = dateutil.parser.parse(event['start']['dateTime']).replace(tzinfo=None)
        end = dateutil.parser.parse(event['end']['dateTime']).replace(tzinfo=None)

        if now <= end:
            items.append({'name': event['summary'], 
                'creator': event['creator']['displayName'], 
                'start': start.strftime("%l:%M%p"), 
                'end': end.strftime("%l:%M%p"),
                })
 
            if start < now and end > now:
                status = "BUSY"
                next_end = end - now

            if start > now and not next_start:
                next_start = start - now


    next_start_str = create_time_string(next_start)
    next_end_str = create_time_string(next_end)

    if status == "FREE" and next_start and next_start < timedelta(minutes=15):
        status = "SOON"

    return {'room': events['summary'], 
        'status': status, 
        'now': now.strftime("%A %e %B %Y, %l:%M%p"), 
        'events': items, 
        'next_start_str': next_start_str, 
        'next_end_str': next_end_str}

@app.route('/index/<room_name>')
def index(room_name=None):
    events = get_events(room_name)

    return render_template('index.html', 
        status=events['status'], 
        events=events['events'], 
        next_start_str=events['next_start_str'], 
        next_end_str=events['next_end_str'], 
        now=events['now'],
        room=room_name
    )

@app.route('/<room_id>')
def main(room_id):
  return render_template('main.html', room=room_id)

if __name__ == '__main__':
    app.run(host="0.0.0.0", debug=True)
