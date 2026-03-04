# ------Libraries------
import re
# --------Types--------
from typing import (
    Optional, 
    Literal
    )
from PetCalendarBot.common.types import (
    MarkdownString,
    EventLinks,
    EventDetails
)
# --------Code---------

def _escape_special_characters(input: str) -> str:
    escaped_input: str = input
    for char in ['.', '!', '-', '(', ')', '=', '{', '}']:
        escaped_input = escaped_input.replace(char, '\\'+char)
    escaped_input = escaped_input.replace("\\\\", "\\")
    return escaped_input

def _format_hyperlinks(input: str) -> str:
    formatted_input = input
    embeds = list(re.finditer(pattern=r"]\(.*\)", string=formatted_input))
    for i in range(0, len(embeds), 2):
        embed = embeds.pop()
        formatted_input = formatted_input[:embed.start()+i+1] + formatted_input[embed.start()+i+2:embed.end()+i-1] + formatted_input[embed.end()+i:]
    return formatted_input

def _preprocess_message(user_input: Optional[str]) -> MarkdownString:
    if not user_input:
        return ''
    escaped_input = _escape_special_characters(user_input)
    formatted_message = _format_hyperlinks(escaped_input)
    return formatted_message

def _header(event: EventDetails, update_type: str) -> MarkdownString:
    '''Constructs the message header.
    
    Parameters
    ----------
    event : EventDetails
        Dictionary containing all the details about an event, usually pulled from a database.
    update_type : str
        String detailing the update type, e.g. "Cancelled".
        
    Returns
    -------
    header : MarkdownString
        String in the format 

        `-event name- :: -city- :: update_type`

        ` -------------------------------------`

        possibly with a hyperlink in the event name, written with Telegram markdown.'''
    possible_links: EventLinks|None = event['links']
    link: str|None = None
    if not possible_links is None:
        link = (possible_links['telegramChatLink'] 
                or possible_links['fetlifeLink'] 
                or possible_links['otherLink'])

    header: MarkdownString
    header = (f'[{event["name"]}]({link}) :: ' if link 
              else f'{event["name"]} :: ')

    header += (f'[{event["location"]}]({event["addressLink"]}) :: ' if event['addressLink']
               else f'{event["location"]} :: ')
    header += f'**{update_type}**\n'

    header += '-'*20 + f'\n'
    return header

def _footer(event: EventDetails) -> MarkdownString:
    '''Constructs the message footer.
    
    Parameters
    ----------
    event : EventDetails
        Dictionary containing all the details about an event, usually pulled from a database.
        
    Returns
    -------
    footer : MarkdownString
        String in the format 

        `For more details:`

        `Contact -Organiser- on Telegram, or Bluesky, or FetLife`

        `Reach out to the event on Telegram, or FetLife, or another site`

        `-----`

        `Questions? Corrections? Contact @AAderyn`

        Where contact points are given, they will be hyperlinked. Written with Telegram markdown.'''
    footer: MarkdownString = f'\n' + '-'*20 + f'\nFor more details:\n'
    # Adds links to the socials for the event contact, if they exist
    if (event_contact := event['contact']):
        footer += f'Contact {event_contact["name"]} ({event_contact["pronouns"]}) '

        organiser_links: list[str] = []
        if (tg_handle:=event_contact['telegramHandle']):
            organiser_links.append(f'[Telegram](https://web.telegram.org/k/#{tg_handle})')
        elif (bs_handle:=event_contact['blueskyHandle']):
            organiser_links.append(f'[Bluesky](https://bsky.app/profile/{bs_handle})')
        elif (fl_id:=event_contact['fetlifeID']):
            organiser_links.append(f'[FetLife](https://fetlife.com/users/{fl_id})')
        elif organiser_links:
            footer += 'on ' + ', or '.join(organiser_links)
        footer += f'\n'

    # Add links to the event, if they exist   
    if event['links']:
        event_links = event['links']
        footer += f'Reach out to the event on '
        social_links: list[str] = []
        if (tg_link:=event_links['telegramChatLink']):
            social_links.append(f'[Telegram]({tg_link})')
        if (fl_link:=event_links['fetlifeLink']):
            social_links.append(f'[FetLife]({fl_link})')
        if (os_link:=event_links['otherSocialLink']):
            social_links.append(f'[their social media]({os_link})')
        if (ow_link:=event_links['otherLink']):
            social_links.append(f'[their website]({ow_link})')
        if social_links:
            footer += ', or '.join(social_links)
        footer += f'\n'

    if price:= event['ticketPrice']:
        if price == 'Free':
            footer += 'Tickets are free'
        else:
            footer += f'Tickets cost {price}'
        if link:=event['ticketLink']:
            footer += f', and are available here: {link}'
        footer += f'\n'


    # If there's neither links to the event nor a contact point, suggests you message Taranau
    if not event['contact'] and not event['links']:
        footer += '@AAderyn might be able to help, but no guarantees.'
    return footer


def new_event(event: EventDetails, date: Optional[str] = None) -> MarkdownString:
    '''Constructs a Telegram message for new events.
    
    Parameters
    ----------
    event : EventDetails
        Dictionary containing all the details about an event.
        
    Returns
    -------
    message : MarkdownString
        A message with header and footer, written with Telegram markdown.'''
    message: MarkdownString = _header(event, 'New event')
    if (location := event['location']) == 'Online':
        message += f'A new petplay event is starting online!'
    elif location == 'UK wide':
        message += f'A new UK-wide petplay event is starting!'
    else:
        message += f'A new petplay event is starting in {event["location"]}!'
    if date:
        message += f'\nThe first meet is on {date}.'
    message += _footer(event)
    return message

def venue_change(event: EventDetails, 
                 new_venue: str, 
                 temporary: bool = False, 
                 date: Optional[str] = None) -> MarkdownString:
    '''Constructs a Telegram message for venue changes.
    
    Parameters
    ----------
    event : EventDetails
        Dictionary containing all the details about an event.
    temporary : bool, default : False
        A boolean indicating if the venue change is temporary or permenant. By default, it's 
        assumed a change is permenant.
    date : Optional[str], default : None
        If the change is for a single occurance of the event, you can provide the date. Dates 
        should be formatted as DD-MM-YYYY.
        
    Returns
    -------
    message : MarkdownString
        A message with header and footer, written with Telegram markdown.'''
    message: str = _header(event, 'Temporary venue '*temporary + 'Venue '*(not temporary) + 'change')
    message += f'{event["name"]} has '+ 'temporarily '*temporary+ f'moved to {new_venue}.'
    message += f'\nDate: {_preprocess_message(date)}'*(temporary and bool(date))
    message += _footer(event)
    return message

def new_venue_and_dates(event: EventDetails, new_venue: str, new_dates: list[str]) -> MarkdownString:
    '''Constructs a Telegram message for a new venue, together with dates for the venue.
    
    Parameters
    ----------
    event : EventDetails
        Dictionary containing all the details about an event.
    newVenue : str
        The address of the new venue. Formatted as "venue name, city, postcode", 
        e.g. "Buckingham Palace, London, SW1A 1AA".
    newDates : list[str]
        New date or dates for the event. Dates should be formatted as e.g. 'DD-MM-YYYY'.
        
    Returns
    -------
    message : MarkdownString
        A message with header and footer, written with Telegram markdown.'''
    plural: bool = (not len(new_dates) == 1)
    message: MarkdownString = _header(event, 'New venue and date' +'s'*plural)
    message += f'{event["name"]} has moved to a new venue: {new_venue}\n'

    message += 'New date' + 's'*plural + f':'
    for date in new_dates:
        message += f'\n• {_preprocess_message(date)}'
    message += _footer(event)
    return message

def new_dates(event: EventDetails, new_dates: list[str]) -> MarkdownString:
    '''Constructs a Telegram message with new dates for an event.
    
    Parameters
    ----------
    event : EventDetails
        Dictionary containing all the details about an event.
    newDates : list[str]
        New date or dates for the event. Dates should be formatted as e.g. 'DD-MM-YYYY'.
        
    Returns
    -------
    message : MarkdownString
        A message with header and footer, written with Telegram markdown.'''
    plural: bool = (not len(new_dates) == 1)
    message: MarkdownString = _header(event, 'New date' +'s'*plural)

    message += 'New date' + 's'*plural + f':'
    for date in new_dates:
        message += f'\n• {_preprocess_message(date)}'
    message += _footer(event)
    return message    

def date_change(event: EventDetails, old_date: str, new_date: str) -> MarkdownString:
    '''Constructs a Telegram message for an event change of date.
    
    Parameters
    ----------
    event : EventDetails
        Dictionary containing all the details about an event.
    oldDate, newDate : str
        Old and new dates for the event. Dates should be formatted as e.g. 'DD-MM-YYYY'.
        
    Returns
    -------
    message : MarkdownString
        A message with header and footer, written with Telegram markdown.'''
    message: MarkdownString = _header(event, 'Date change')
    message += f'The {event["name"]} social on {_preprocess_message(old_date)} has moved to {_preprocess_message(new_date)}.'
    message += _footer(event)
    return message

def timing_change(event: EventDetails, date: str, old_times: str, new_times: str) -> MarkdownString:
    '''Constructs a Telegram message for an event change of time.
    
    Parameters
    ----------
    event : EventDetails
        Dictionary containing all the details about an event.
    oldTimes, newTimes : str
        Old and new times for the event. Times should be formatted as e.g. '3pm-10pm'.
        
    Returns
    -------
    message : MarkdownString
        A message with header and footer, written with Telegram markdown.'''
    message: MarkdownString = _header(event, 'Timing change')
    message += f'The {event["name"]} social on {_preprocess_message(date)}, which was previously at {_preprocess_message(old_times)}, will now be at {_preprocess_message(new_times)}.'
    message += _footer(event)
    return message

def event_cancelled(event: EventDetails, date: str | Literal['Next']) -> MarkdownString:
    '''Constructs a Telegram message for an event cancellation.
    
    Parameters
    ----------
    event : EventDetails
        Dictionary containing all the details about an event.
    date : str | Literal['Next']
        Either a date, formatted as e.g. "DD-MM-YYYY", or the string "Next" when the next 
        upcoming event is cancelled.
        
    Returns
    -------
    message : MarkdownString
        A message with header and footer, written with Telegram markdown.'''
    message: MarkdownString = _header(event, 'Cancelled')
    if date == 'Next':
        message += f'The next {event["name"]} has been cancelled.'
    else:
        message += f'The {event["name"]} social on {_preprocess_message(date)} has been cancelled.'

    message += _footer(event)
    return message

def event_shut_down(event: EventDetails, permanent: bool = False) -> MarkdownString:
    '''Constructs a Telegram message for an event shutting down.
    
    Parameters
    ----------
    event : EventDetails
        Dictionary containing all the details about an event.
    permanent : bool, default : False
        Boolean indicating if the shutdown is permanent.
        
    Returns
    -------
    message : MarkdownString
        A message with header and footer, written with Telegram markdown.'''

    message: MarkdownString = (_header(event, 'Permanent shut down') if permanent 
                    else _header(event, 'Temporary shut down'))

    if permanent:
        message += f'{event["name"]} social is no longer running.'
    else:
        message += f'All {event["name"]} events suspended until further notice.'

    message += _footer(event)
    return message

def other(event: EventDetails, text: str) -> MarkdownString:
    '''Constructs a Telegram message for miscellaneous event happenings.
    
    Parameters
    ----------
    event : EventDetails
        Dictionary containing all the details about an event.
    text : str
        A full explanation of what has happened.
        
    Returns
    -------
    message : MarkdownString
        A message with header and footer, written with Telegram markdown.'''

    message: MarkdownString = _header(event, 'Other')
    message += _preprocess_message(text)
    message += _footer(event)
    return message

def meta(widget: str, text: str) -> MarkdownString:
    '''Constructs a Telegram message for meta events, e.g. an update to the map, or a new widget.
    
    Parameters
    ----------
    widget : str
        Which widget is affected, e.g. 'Calendar'.
    text : str
        A full explanation of the meta event.
        
    Returns
    -------
    message : MarkdownString
        A message with header and footer, written with Telegram markdown.'''

    message: MarkdownString = f'{widget} :: **Meta**\n' + '-'*20 + '\n'
    message += _preprocess_message(text)
    return message
