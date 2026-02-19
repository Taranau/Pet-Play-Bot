import datetime
import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow # type: ignore[import-untyped]
from googleapiclient.discovery import build # type: ignore[import-untyped]
from googleapiclient.errors import HttpError # type: ignore[import-untyped]

from PetCalendarBot.common.types import EventDetails
from PetCalendarBot.hidden_keys import CALENDAR_ID

# def AddToCalendar(start_time: datetime.datetime, end_time: datetime.datetime, event_details: EventDetails):

#     raise NotImplementedError






# If modifying these scopes, delete the file token.json.
# https://calendar.google.com/calendar/embed?src=21ebe647eeec0bd09eddf9f96e03fc285ec6a913af510f794cd85ee2cb677a75%40group.calendar.google.com&ctz=Europe%2FLondon

def _GetCredentials() -> Credentials:
  scopes = ["https://www.googleapis.com/auth/calendar.events"]
  creds = None
  if os.path.exists("token.json"):
    creds = Credentials.from_authorized_user_file("token.json", scopes)
  # If there are no (valid) credentials available, let the user log in.
  if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
      creds.refresh(Request())
    else:
      flow = InstalledAppFlow.from_client_secrets_file(
          "PetCalendarBot/credentials.json", scopes
      )
      creds = flow.run_local_server(port=0)
    # Save the credentials for the next run
    with open("token.json", "w") as token:
      token.write(creds.to_json())
  return creds

def _ConstructEvent(start_time: datetime.datetime, end_time: datetime.datetime, event_details: EventDetails) -> dict:
  now = datetime.datetime.now()
  description = f''

  if event_links := event_details.get('links'):
    if tg_link := event_links.get('telegramChatLink'):
      description += f'Telegram chat: {tg_link}\n'
    if fl_link := event_links.get('fetlifeLink'):
      description += f'Fetlife: {fl_link}\n'
    if social_link := event_links.get('otherSocialLink'):
      description += f'Socials: {social_link}\n'
    if other_link := event_links.get('otherLink'):
      description += f'Event link: {other_link}\n'
    description += f'\n'
    if ticket_link := event_links.get('ticketLink'):
      description += f'Tickets cost {event_details.get("ticketPrice")}, and can be obtained at {ticket_link}.\n\n'
  
  if contact := event_details.get('contact'):
    description += f'A contact point for the event is {contact.get("name")} ({contact.get("pronouns")})'
    if tg_handle := contact.get('telegramHandle'):
      description += f'; telegram: [@{tg_handle}](https://web.telegram.org/k/#{tg_handle})'
    if fl_id := contact.get('fetlifeID'):
      description += f'; fetlife: [{fl_id}](https://fetlife.com/users/{fl_id})'
    if bs_handle := contact.get('blueskyHandle'):
      description += f'; bluesky: [{bs_handle}](https://bsky.app/profile/{bs_handle})'
    description += f'\n'

  if not description:
    description += f'We appear to be missing details for this event. Please contact @aaderyn on telegram for support or if you have any information.\n'

  description += f'Last updated: {now.date()} (by bot)'

  event = {'summary': f'{event_details.get("name")} ({event_details.get("city")})',
           'location': event_details.get("venue"),
           'description': description,
           'start': {
             'dateTime': start_time.isoformat(),
           },
           'end': {
             'dateTime': end_time.isoformat(),
           },
          }
  return event

def AddEventToCalendar(start_time: datetime.datetime, end_time: datetime.datetime, event_details: EventDetails):
  try:
    creds = _GetCredentials()
    service = build("calendar", "v3", credentials=creds)
    calendar_id = CALENDAR_ID
    event = _ConstructEvent(start_time, end_time, event_details)
    event = service.events().insert(calendarId=calendar_id, body=event).execute()
  except HttpError as error:
    print(f"An error occurred: {error}")

  return

