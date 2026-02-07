import logging
import requests
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from typing import Optional, TypeAlias

from PetCalendarBot.hidden_keys import API_KEYS, PERMITTED_CHAT_IDS, DESTINATION_CHAT
from PetCalendarBot.common.types import (
    MarkdownString,
    EventDetails,
    EventLinks,
    PersonDetails
    )

from PetCalendarBot.common.pronouns import PronounFactory
import PetCalendarBot.telegram_messages as messages
import PetCalendarBot.database_processes as database

Response: TypeAlias = requests.Response

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.WARNING
)

def _RebracketArgs(input:list[str]) -> list[str]:
    rejoined_input: list[str] = []
    start: int|None = None
    end: int|None = None
    aux_list: list[str] = []
    # This short bit of logic will turn e.g. 
    # ["(Name:long", "name)", "City:city", "(Links:Fetlife:link", "Telegram:link)"]
    # into
    # ["Name:long name", "City:city", "Links:Fetlife:link Telegram:link"]
    for index, arg in enumerate(input):
        if arg[0] == '(':
            start = index
        if arg[-1] == ')':
            end = index
        
        if start is None:
            rejoined_input.append(arg)
        else:
            aux_list.append(arg)
        if not end is None:
            rejoined_input.append((" ".join(aux_list))[1:-1])
            start, end = None, None
            aux_list = []
    return rejoined_input
 
def _SplitArgs(input: list[str]) -> dict[str,str]:
    return {pair[0]: pair[1] for pair in [arg.split(':', 1) for arg in input]}

def _ProcessLinkBlob(link_blob:list[str], pair_split_char: str = ':') -> EventLinks|None:
    link_dict: dict[str,str] = {pair[0]: pair[1] for pair in [link.split(pair_split_char, 1) for link in link_blob]}
    if not link_dict:
        return None
    event_links: EventLinks = {'telegramChatLink': link_dict.get('Telegram'),
                               'fetlifeLink': link_dict.get('Fetlife'),
                               'otherSocialLink': link_dict.get('OtherSocial'),
                               'otherLink': link_dict.get('Other')}
    return event_links

def _ProcessContactBlob(contact_blob:list[str], pair_split_char: str = ':') -> PersonDetails|None:
    contact_dict: dict[str,str] = {pair[0]: pair[1] for pair in [link.split(pair_split_char, 1) for link in contact_blob]}
    
    if (name:= contact_dict.get('Name')) is None:
        return None
    if (unformatted_pronouns:=contact_dict.get('Pronouns')) is None:
        return None
    else:
        pronouns: str = PronounFactory(unformatted_pronouns.split('/'))
    
    contact: PersonDetails = {'name': name,
                              'pronouns': pronouns,
                              'blueskyHandle': contact_dict.get('Bluesky'),
                              'telegramHandle': contact_dict.get('Telegram'),
                              'fetlifeID': contact_dict.get('Fetlife')}
    return contact

def _ProcessEventInput(input:list[str]) -> EventDetails|None:
    rejoined_input = _RebracketArgs(input)
    args = _SplitArgs(rejoined_input)

    name: str|None = args.get('Name')
    city: str|None = args.get('City')

    if name is None or city is None:
        return None

    venue_name: Optional[str] = args.get('Venue')
    gmaps_link: Optional[str] = args.get('AddressLink')
    # Currently, the only API I know for this charges for the service.

    contact_blob: Optional[str] = args.get('Contact')
    contact: PersonDetails|None = None
    if contact_blob:
        contact = _ProcessContactBlob(contact_blob.split(' '))

    link_blob: Optional[str] = args.get('Links')
    event_links: EventLinks|None = None
    if link_blob:
        event_links = _ProcessLinkBlob(link_blob.split(' '))

    event_details: EventDetails = {'name': name,
                                   'acronym': args.get('Acronym'),

                                   'city': city,
                                   'venue': venue_name,
                                   'addressLink': gmaps_link,
                                   
                                   'contact':contact,
                                   'organisers':[],

                                   'links': event_links}

    return event_details


def _PreprocessTelegramUpdate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> tuple[int|None, list[str]|None]:
    assert(not (chat := update.effective_chat) is None)
    if not (feedback_id:=chat.id) in PERMITTED_CHAT_IDS:
        return None, None
    if (unsplit_args:=context.args) is None:
        return feedback_id, None
    return feedback_id, unsplit_args

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''Sends a telegram message explaining bot commands.
    
    Parameters
    ----------

        
    Returns
    -------
    '''
    feedbackID, args = _PreprocessTelegramUpdate(update, context)
    chat = update.effective_chat
    if chat is None or feedbackID is None:
        return None
    message: MarkdownString = ''
    if (args:=context.args):
        arg=args[0]
        match arg:
            case 'NewEvent':
                message += f'''/NewEvent : Announce a new event\.
Currently announces in channel and adds to database, but does not update calendar or map\.
                
An example input is as follows:
```
/NewEvent \(Name:Leicestershire Kennel Pups\) Acronym:LKP
City:Leicester \(Venue:Helsinki, 94 Rutland St, LE1 1SB\)
\(Contact:Name:Xadia Pronouns:He Telegram:@Pupxadia\)
\(Links:Telegram:https://t\.me/AllThePups\)```

Brackets are necessary for arguments with spaces \(e\.g\. the event name\) and to group the Contact and Links details\.
Contact may additionally include bluesky handle \(key: Bluesky\) or fetlife ID \(key: Fetlife\)\.
Links may additionally include fetlife \(key: Fetlife\), other social media where the event can be contacted \(key: OtherSocial\) or another relevant link \(key: Other\)\.
Acronym, Venue, Contact and Links are all optional\. 
Where Contact is used, name and pronouns must be specified\. 
Where Links is used, at least one link must be provided\.'''
            case 'UpdateEvent':
                message += f'''/UpdateEvent : Update details of an existing event\.
Currently announces in channel and updates database, but does not update calendar or map\.

The command takes an argument and some additional parameters, as specified below:
```
/UpdateEvent NewVenue EventName:{{name}} \(Venue:{{name}}\) Temporary:{{Y/N}} Date:{{DD\-MM\-YYYY}}```
Changes the event venue, either temporarily or permanently\. Naming the new venue is necessary \(see also: /UpdateEvent Cancel\)\.
If moving for a single day, e\.g\. the 3rd of march 2025, use Temporary:Y Date:03\-03\-2025; otherwise, the Date key is optional\.
                
```
/UpdateEvent AddDates EventName:{{name}} \(Dates:DD\-MM\-YYYY DD\-MM\-YYYY\)```
Adds new dates for an event\. At least one new date must be given\.
                
```
/UpdateEvent ChangeDate EventName:{{name}} OldDate:DD\-MM\-YYYY NewDate:DD\-MM\-YYYY```
Changes a single date for an event, e\.g\. if it needs to move because of a clash\.
                
```
/UpdateEvent ChangeTiming EventName:{{name}} Date:DD\-MM\-YYYY OldTimes:{{time}} NewTimes:{{time}}```
Changes timing for a single occurence of an event\. Old and New times should be specified as e\.g\. 7PM\-10PM, or 14:30\-17:45\.
                
```
/UpdateEvent Cancel EventName:{{name}} Date:DD\-MM\-YYYY```
Cancels a single instance of an event\. If no date is specified, the instance will be the next upcoming\.
                
```
/UpdateEvent Shutdown EventName:{{name}} Permanent:{{Y/N}}```
Shuts down an event, temporarily or permanently\.
                
```
/UpdateEvent Other EventName:{{name}} \(Message:{{message}}\)```
Gives an arbitrary update for an event, as specified by Message\.'''
            case 'Meta':
                message += f'''/Meta : Announce an update to our tooling\.
Example:
```
\Meta \(Widget:Petplay Calendar\) \(Message:Time has reversed\. This may affect your calendar experience\.\)```'''
            case _:
                message += f''' Oh no\! We don't recognise that command\!'''
    else:
        message += '''Welcome to the Petplay Support Bot\! 
This bot is designed to help @aderyn and friends maintain resources like the UK petplay calendar, map, and announcements channel\.\n
For more support with any command, including input formatting, use /help \(command\), e\.g\. /help NewEvent\.
'''
        message += '\-'*20
        message += f'''
Commands:
/NewEvent : Announce a new event\.
/UpdateEvent : Update details of an existing event\.
/Meta : Announce an update to our tooling\.'''

    await context.bot.send_message(chat_id=feedbackID, text=message, parse_mode='MarkdownV2')


EVENT_NAME, ACRONYM, LOCATION, VENUE, CONTACT_NAME, CONTACT_PLATFORM, CONTACT_PRONOUNS, CONTACT_HANDLE, INITIAL_TIMINGS, TICKET_COST, TICKET_LINK, EVENT_LINK, ADD_TO_DATABASE, ADD_TO_CALENDAR, ADD_TO_MAP, SEND_UPDATE = range(16)

class NewEvent:

    @staticmethod
    async def _SaveDataAndReply(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                message: str, var_name: str | None = None,
                                keyboard: list[str] | None = None) -> None:
        assert(not (update.message is None or context.user_data is None))
        if var_name:
            context.user_data[var_name] = update.message.text
        if keyboard:
            await update.message.reply_text(message, 
                                            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
                                            )
        else:
            await update.message.reply_text(message, reply_markup=ReplyKeyboardRemove())
        return None

    @staticmethod
    async def NewEvent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        message = '''You're trying to tell me about a new petplay event.
        To stop, send /cancel.\n\n
        What is the full name of the event?'''
        await NewEvent._SaveDataAndReply(update, context, message=message)
        return EVENT_NAME
    
    @staticmethod
    async def EventName(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        message = "Does the event have an acronym? If not, you can /skip."
        await NewEvent._SaveDataAndReply(update, context, message=message, var_name="event_name")
        return ACRONYM
    
    @staticmethod
    async def Acronym(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        assert(not (update.message is None or context.user_data is None))
        clash: Optional[str] = database.ManageEvent.CheckAcronym(update.message.text)
        if clash:
            message = f'''That acronym is in our database already!\n\n
            It currently corresponds to the event {clash}.
            If you were intending to update that event, please use /cancel and then /UpdateEvent instead. 
            If the acronyms genuinely clash, please enter an alternative acronym.'''
            await NewEvent._SaveDataAndReply(update, context, message)
            return ACRONYM
        message = '''What is the event's location? \n
        This can be online, UK-wide, or a specific town, city or region.'''
        await NewEvent._SaveDataAndReply(update, context, message, "event_acronym", ["Online", "UK-wide"])
        return LOCATION
    
    @staticmethod
    async def SkipAcronym(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        message = '''What is the event's location? \n
        This can be online, UK-wide, or a specific town, city or region.'''
        await NewEvent._SaveDataAndReply(update, context, message, "event_acronym", ["Online", "UK-wide"])
        return LOCATION
    
    @staticmethod
    async def Location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        message = '''What is the event's venue, if it has one?
        If not, use /skip.'''
        await NewEvent._SaveDataAndReply(update, context, message, var_name="location")
        return VENUE
    
    @staticmethod
    async def Venue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        message = '''Who is the contact for the event, if it has one?\n
        If not, use /skip.'''
        await NewEvent._SaveDataAndReply(update, context, message, var_name="venue")
        return CONTACT_NAME
    
    @staticmethod
    async def SkipVenue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        message = '''Who is the contact for the event, if it has one?\n
        "If not, use /skip.'''
        await NewEvent._SaveDataAndReply(update, context, message)
        return CONTACT_NAME
    
    @staticmethod
    async def ContactName(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        message = '''What platform are they on?\n
        For instance, Telegram, FetLife, WhatsApp.'''
        await NewEvent._SaveDataAndReply(update, context, message, var_name="contact_name")
        return CONTACT_PLATFORM
    
    @staticmethod
    async def ContactPlatform(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        message = ''
        assert(not (update.message is None or context.user_data is None))
        platform: str | None = update.message.text
        match platform:
            case "Telegram":
                message = '''What is their Telegram handle?\n
                For example, Taranau is "@aaderyn"'''
            case "FetLife":
                message = '''What is their FetLife handle?\n
                For example, Taranau is "Taranau"'''
            case "WhatsApp":
                message = '''What is their phone number?'''
                raise NotImplementedError
            case _:
                message = '''Please provide a link to their profile.'''
        await NewEvent._SaveDataAndReply(update, context, message, var_name='contact_platform')
        return CONTACT_HANDLE

    @staticmethod
    async def ContactHandle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        message = "What are their pronouns?"
        await NewEvent._SaveDataAndReply(update, context, message, var_name='contact_handle_or_link')
        return CONTACT_PRONOUNS

    @staticmethod
    async def ContactPronouns(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        message = '''Does this event have an initial date and time?\n
        If yes, please provide in the format 'DD-MM-YYYY, HH:MM-HH:MM'.\n
        E.g. 30-01-2026, 08:00-23:30.\n
        If no, please /skip.'''
        await NewEvent._SaveDataAndReply(update, context, message, var_name='pronouns')
        return INITIAL_TIMINGS

    @staticmethod
    async def SkipContact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        message = '''Does this event have an initial date and time?\n
        If yes, please provide in the format 'DD-MM-YYYY, HH:MM-HH:MM'.\n
        E.g. 30-01-2026, 08:00-23:30.\n
        If no, please /skip.'''
        await NewEvent._SaveDataAndReply(update, context, message)
        return INITIAL_TIMINGS
    
    @staticmethod
    async def InitialTimings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        message = '''Is this event ticketed?\n
        If yes, how much do tickets cost?\n
        E.g. £10, €15, £0.\n
        If not, please /skip.'''
        await NewEvent._SaveDataAndReply(update, context, message, var_name='initial_timings')
        return TICKET_COST
    
    @staticmethod
    async def SkipInitialTimings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        message = '''Is this event ticketed?\n
        If yes, how much do tickets cost?\n
        E.g. £10, €15, £0.\n
        If not, please /skip.'''
        await NewEvent._SaveDataAndReply(update, context, message)
        return TICKET_COST
    
    @staticmethod
    async def TicketCost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        message = '''Please provide a link for the tickets.'''
        await NewEvent._SaveDataAndReply(update, context, message, var_name="ticket_cost")
        return TICKET_LINK
    
    @staticmethod
    async def TicketLink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        message = '''Please provide the main link for the event.\n
        E.g. a link to the telegram or whatsapp group, or a website.\n
        If none is available, reply with "N"'''
        await NewEvent._SaveDataAndReply(update, context, message, var_name="ticket_link")
        return EVENT_LINK

    @staticmethod
    async def SkipTickets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        message = '''Please provide the main link for the event.\n
        E.g. a link to the telegram or whatsapp group, or a website.\n
        If none is available, reply with "N"'''
        await NewEvent._SaveDataAndReply(update, context, message)
        return EVENT_LINK

    @staticmethod
    async def EventLink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        message = '''Would you like to add this event to the database?'''
        assert(not update.message is None)
        assert(not update.message.text is None)
        if update.message.text.capitalize() == "N":
            await NewEvent._SaveDataAndReply(update, context, message, keyboard=["Yes", "No"])
        else:
            await NewEvent._SaveDataAndReply(update, context, message, var_name="event_link", keyboard=["Yes", "No"])
        return ADD_TO_DATABASE

    @staticmethod
    async def AddToDatabase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        assert(not update.message is None)
        if update.message.text == "Yes":
            #Do a thing here
            raise NotImplementedError
        
        raise NotImplementedError
        return ADD_TO_CALENDAR
    
    @staticmethod
    async def AddToCalendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        raise NotImplementedError

    @staticmethod
    async def AddToMap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        raise NotImplementedError
    
    @staticmethod
    async def SendUpdateMessage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        raise NotImplementedError

    @staticmethod
    async def NewEventReplacement(update: Update, context: ContextTypes.DEFAULT_TYPE):
        feedback_id, _ = _PreprocessTelegramUpdate(update, context)
        if feedback_id is None:
            return None
        # First: ask for name of event
        # Second: ask for acronym
        ## Substep: check for acronym clash? Complicated logic there
        # Third: ask for city
        # Fourth: ask for venue
        # Fifth: ask about event contact
        ## Substeps: name, pronouns, telegram handle if applicable
        # Sixth: ask about links
        # ```
        # /NewEvent \(Name:Leicestershire Kennel Pups\) Acronym:LKP
        # City:Leicester \(Venue:Helsinki, 94 Rutland St, LE1 1SB\)
        # \(Contact:Name:Xadia Pronouns:He Telegram:@Pupxadia\)
        # \(Links:Telegram:https://t\.me/AllThePups\)```
        return None

async def NewEventOld(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feedback_id, unsplit_args = _PreprocessTelegramUpdate(update, context)
    if unsplit_args is None or feedback_id is None:
        return None
    message: MarkdownString = ''
    chat_id: int = feedback_id
    event_details = _ProcessEventInput(unsplit_args)
    if event_details is None:
        message = "Missing event name or city\."
    else:
        message=messages.NewEvent(event_details)
        database.ManageEvent.New(event_details)
        chat_id = DESTINATION_CHAT
    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='MarkdownV2')

def NewEventHandlerFactory():
    return None

def _UpdateEventCaseSelect(command: str, 
                              args: dict[str, str], 
                              feedback_id: int) -> tuple[MarkdownString, int]:
    event_name = args.get('EventName') 
    event: EventDetails|None = database.ManageEvent.GetDetailsFromName(event_name)
    if event is None:
        message="Couldn't find event, or name not provided\."
        return message, feedback_id
    match command:
        case 'NewVenue':
            venue = args.get('Venue')
            if venue is None:
                message = "You haven't correctly specified a venue\."
                return message, feedback_id
            temporary_check_string: str|None = args.get('Temporary')
            temporary: bool = temporary_check_string is None or temporary_check_string == 'Y'
            date: str|None = args.get('Date')
            message=messages.VenueChange(event, new_venue=venue, temporary=temporary, date=date)
            if not temporary:
                database.ManageEvent.VenueChange(event, new_venue=venue)
            return message, DESTINATION_CHAT
        case 'AddDates':
            dates = args.get('Dates')
            if dates is None:
                message = "You need to specify one or more dates\."
                return message, feedback_id
            dateList = dates.split()
            message = messages.NewDates(event, new_dates=dateList)
            return message, DESTINATION_CHAT
        case 'ChangeDate':
            oldDate = args.get('OldDate')
            newDate = args.get('NewDate')
            if oldDate is None or newDate is None:
                message = "You need to specify dates\."
                return message, feedback_id
            message = messages.DateChange(event, oldDate, newDate)
            return message, DESTINATION_CHAT
        case 'ChangeTiming':
            date = args.get('Date')
            old_times = args.get('OldTimes')
            new_times = args.get('NewTimes')
            if date is None or old_times is None or new_times is None:
                message = "You need to specify all keys\."
                return message, feedback_id
            message = messages.TimingChange(event, date, old_times, new_times)
            return message, DESTINATION_CHAT
        case 'Cancel':
            date = args.get('Date')
            if date is None:
                date = 'Next'
            message = messages.EventCancelled(event, date)
            return message, DESTINATION_CHAT
        case 'Shutdown':
            permanent_check_string = args.get('Permanent')
            permanent: bool = (permanent_check_string =='Y' or permanent_check_string is None)
            message = messages.EventShutDown(event, permanent)
            return message, DESTINATION_CHAT
        case 'Other':
            body = args.get('Message')
            if body is None:
                message = "You need to specify the Message key\."
                return message, feedback_id
            message = messages.Other(event, text=body)
            return message, DESTINATION_CHAT
        case _:
            message = "Oh no\! You've only given a partial command, or there is a different formatting error\."
            return message, feedback_id

async def UpdateEvent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feedback_id, unsplit_args = _PreprocessTelegramUpdate(update, context)
    if feedback_id is None or unsplit_args is None:
        return None
    command = unsplit_args.pop(0)
    args = _SplitArgs(_RebracketArgs(unsplit_args))

    message, chat_id = _UpdateEventCaseSelect(command, args, feedback_id)
            
    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='MarkdownV2')

def _MetaMessageConstructor(widget:str|None, body:str|None, feedback_id: int) -> tuple[MarkdownString, int]:
    if widget is None:
        message = "You must specify the affected widget\."
        return message, feedback_id
    if body is None:
        message = "You must specify the message body\."
        return message, feedback_id
    message = messages.Meta(widget, text=body)
    return message, DESTINATION_CHAT

async def Meta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feedback_id, unsplit_args = _PreprocessTelegramUpdate(update, context)
    if feedback_id is None or unsplit_args is None:
        return None
    args = _SplitArgs(_RebracketArgs(unsplit_args))
    widget = args.get('Widget')
    body = args.get('Message')
    message, chat_id = _MetaMessageConstructor(widget, body, feedback_id)

    await context.bot.send_message(chat_id=DESTINATION_CHAT, text=message, parse_mode='MarkdownV2')

def RunBot(TELEGRAM_KEY: str) -> None:
    application = ApplicationBuilder().token(TELEGRAM_KEY).build()

    help_handler = CommandHandler('help', help)
    application.add_handler(help_handler)

    new_event_handler = CommandHandler('NewEvent', NewEvent.NewEvent)
    application.add_handler(new_event_handler)

    update_event_handler = CommandHandler('UpdateEvent', UpdateEvent)
    application.add_handler(update_event_handler)
 
    meta_handler = CommandHandler('Meta', Meta)
    application.add_handler(meta_handler)

    application.run_polling()

if __name__ == '__main__':
    RunBot(API_KEYS["TELEGRAM_KEY"])