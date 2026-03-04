# ------Libraries------
import logging
import requests
import re
import datetime
from abc import ABC, abstractmethod

from telegram import (
    Update, 
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton
    )
from telegram.ext import (
    ApplicationBuilder, 
    ContextTypes, 
    CommandHandler, 
    ConversationHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    filters
    )

import PetCalendarBot.telegram_messages as messages
import PetCalendarBot.database_processes as database
import PetCalendarBot.calendar_processes as calendar
# --------Keys---------
from PetCalendarBot.hidden_keys import (
    API_KEYS, 
    PERMITTED_CHAT_IDS, 
    DESTINATION_CHAT
    )
# --------Types--------
from typing import Optional, TypeAlias

from PetCalendarBot.common.types import (
    MarkdownString,
    EventDetails,
    EventLinks,
    PersonDetails
    )

Response: TypeAlias = requests.Response
Context: TypeAlias = ContextTypes.DEFAULT_TYPE
StateCode: TypeAlias = int
DateTime: TypeAlias = datetime.datetime
# -----Error types-----
from googleapiclient.errors import HttpError # type: ignore[import-untyped]
from peewee import IntegrityError
MapError: TypeAlias = None
UpdateError: TypeAlias = tuple[Optional[IntegrityError], Optional[HttpError], Optional[MapError]]
# -------Logging-------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.WARNING
)
# --------Code---------

async def help(update: Update, context: Context):
    raise NotImplementedError

class TelegramProcess:

    @staticmethod
    async def _save_data(update: Update, context: Context, 
                        var_name: str, value: Optional[str] = None):
        assert(context.user_data)
        if value:
            context.user_data[var_name] = value
        else:
            assert(update.message)
            context.user_data[var_name] = update.message.text
        return None
    
    @staticmethod
    async def _reply(update: Update, context: Context, 
                     message: str, keyboard: Optional[list[list[str]]] = None, skippable: bool = False) -> None:
        formatted_message = messages._preprocess_message(message)
        reply_markup: InlineKeyboardMarkup | ReplyKeyboardRemove
        if keyboard:
            button_keyboard: list[list[InlineKeyboardButton]] = [[InlineKeyboardButton(item, callback_data=item) for item in line] for line in keyboard] + ([[InlineKeyboardButton("skip", callback_data="skip")]] if skippable else [])
            reply_markup = InlineKeyboardMarkup(button_keyboard)
        elif skippable:
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("skip", callback_data="skip")]])
        else:
            reply_markup = ReplyKeyboardRemove()
        if update.message:
            assert(update.message)
            await update.message.reply_text(formatted_message,
                                            reply_markup=reply_markup,
                                            parse_mode='MarkdownV2')
        else:
            assert(chat_id := context._chat_id)
            
            await context.bot.send_message(chat_id=chat_id, message_thread_id=4,
                                           text=formatted_message, 
                                           reply_markup=reply_markup, 
                                           parse_mode = 'MarkdownV2')
        return None

    @staticmethod
    def _process_date(date: str) -> tuple[DateTime, DateTime]:
        date = date.replace("/", "-").replace(".", "-")
        day, times = date.split(',') if (date.find(",")>=0) else date.split()
        start_time, end_time = times.strip().split("-")
        start_date_obj = datetime.datetime.strptime(day + " " + start_time, "%d-%m-%Y %H:%M")
        end_date_obj = datetime.datetime.strptime(day + " " + end_time, "%d-%m-%Y %H:%M")
        return start_date_obj, end_date_obj

class TelegramFlow(ABC):

    class _Message(ABC):

        class _Success:

            @staticmethod
            async def database(update: Update, context: Context) -> None:
                message = "Successfully added to database!"
                return await TelegramProcess._reply(update, context, message)
            
            @staticmethod
            async def calendar(update: Update, context: Context, event: EventDetails) -> None:
                message = f"Successfully added to calendar! link: {event.get('htmlLink')}"
                return await TelegramProcess._reply(update, context, message)
            
            @staticmethod
            async def map(update: Update, context: Context) -> None:
                message = f"Successfully added to map!"
                return await TelegramProcess._reply(update, context, message)

            @staticmethod
            async def update_message(update: Update, context: Context) -> None:
                message = f"Successfully sent update message!"
                return await TelegramProcess._reply(update, context, message)

        class _Error:

            @staticmethod
            async def database(update: Update, context: Context, 
                               error: Optional[IntegrityError]) -> None:
                message = f'''Oh no! There was an error updating the database: {error}'''
                return await TelegramProcess._reply(update, context, message)
            
            @staticmethod
            async def calendar(update: Update, context: Context, 
                               error: HttpError) -> None:
                message = f"Oh no! There was an error updating the calendar: {error.status_code}"
                return await TelegramProcess._reply(update, context, message)
            
            @staticmethod
            async def map(update: Update, context: Context, 
                          error: str) -> None:
                message = f"Oh no! There was an error updating the map: {error}"
                return await TelegramProcess._reply(update, context, message)

    class Conversation(ABC):

        @abstractmethod
        @staticmethod
        def handler() -> ConversationHandler:
            pass

        @abstractmethod
        @staticmethod
        def start(update: Update, context: Context) -> StateCode:
            pass

class NewEvent:

    EVENT_NAME, ACRONYM, LOCATION, VENUE, CONTACT_NAME, CONTACT_PLATFORM, CONTACT_PRONOUNS, CONTACT_HANDLE, INITIAL_TIMINGS, TICKET_COST, TICKET_LINK, EVENT_LINK, ADD_TO_DATABASE, ADD_TO_CALENDAR, ADD_TO_MAP, SEND_UPDATE = range(16)

    @staticmethod
    def _process_event_info(update: Update, 
                                context: Context) -> EventDetails:
        assert(context.user_data)
        contact: Optional[PersonDetails] = None
        if contact_name := context.user_data.get('contact_name'):
            contact = {'name': contact_name,
                       'pronouns': context.user_data['pronouns'],
                       'blueskyHandle': None,
                       'fetlifeID': None,
                       'telegramHandle': None}
            match context.user_data.get('contact_platform'):
                case 'telegram':
                    contact.update({'telegramHandle': context.user_data.get('contact_handle_or_link')})
                case 'fetlife':
                    contact.update({'fetlifeID': context.user_data.get('contact_handle_or_link')})
                case 'bluesky':
                    contact.update({'blueskyHandle': context.user_data.get('contact_handle_or_link')})

        links: EventLinks = {'telegramChatLink': None,
                             'fetlifeLink': None,
                             'otherSocialLink': None,
                             'otherLink': None}
        event_link = context.user_data.get('event_link')
        if event_link:
            if re.search(r'.*(t.me/|telegram.org).*', event_link):
                links.update({'telegramChatLink': event_link})
            elif re.search(r'.*fetlife.com.*', event_link):
                links.update({'fetlifeLink': event_link})
            elif re.search(r'.*(whatsapp.com|instagram.com).*', event_link):
                links.update({'otherSocialLink': event_link})
            else:
                links.update({'otherLink': event_link})

        event: EventDetails = {'name': context.user_data['event_name'],
                               'acronym': context.user_data.get('event_acronym'),
                               
                               'location': context.user_data['location'],
                               'venue': context.user_data.get('venue'),
                               'addressLink': None,
                               
                               'contact': contact,
                               'organisers': None,
                               
                               'ticketPrice': context.user_data.get('ticket_cost'),
                               'ticketLink': context.user_data.get('ticket_link'),
                               
                               'links': links}
        return event

    class _Message:

        class _Success:

            @staticmethod
            async def database(update: Update, context: Context) -> None:
                message = "Successfully added to database!"
                return await TelegramProcess._reply(update, context, message)
            
            @staticmethod
            async def calendar(update: Update, context: Context, event: EventDetails) -> None:
                message = f"Successfully added to calendar! link: {event.get('htmlLink')}"
                return await TelegramProcess._reply(update, context, message)
            
            @staticmethod
            async def map(update: Update, context: Context) -> None:
                message = f"Successfully added to map!"
                return await TelegramProcess._reply(update, context, message)

            @staticmethod
            async def update_message(update: Update, context: Context) -> None:
                message = f"Successfully sent update message!"
                return await TelegramProcess._reply(update, context, message)

        class _Error:

            @staticmethod
            async def database(update: Update, context: Context, 
                               error: tuple[Optional[IntegrityError], Optional[IntegrityError], Optional[IntegrityError]]) -> None:
                message = f'''Oh no! There was an error adding the event to the database. \nTried to add main event details: {({error[0]} if error[0] else 'success')} \nTried to add event links: {({error[1]} if error[1] else 'success')} \nTried to add event contact: {({error[2]} if error[2] else 'success')}'''
                return await TelegramProcess._reply(update, context, message)

            @staticmethod
            async def no_provided_timings(update: Update, context: Context) -> None:
                message = "Oh no! You didn't provide the initial timings!"
                return await TelegramProcess._reply(update, context, message)
            
            @staticmethod
            async def calendar(update: Update, context: Context, 
                               error: HttpError) -> None:
                message = f"Oh no! There was an error adding the event to the calendar: {error.status_code}"
                return await TelegramProcess._reply(update, context, message)
            
            @staticmethod
            async def map(update: Update, context: Context, 
                          error: str) -> None:
                message = f"Oh no! There was an error adding the event to the map: {error}"
                return await TelegramProcess._reply(update, context, message)
            
            @staticmethod
            async def update_message(update: Update, context: Context, 
                                    error: str) -> None:
                message = f"Oh no! There was an error sending the update message on telegram: {error}"
                return await TelegramProcess._reply(update, context, message)

        @staticmethod
        async def event_name(update: Update, context: Context) -> StateCode:
            message = '''You're trying to tell me about a new petplay event. \n\nWhat is the full name of the event?'''
            await TelegramProcess._reply(update, context, message)
            return NewEvent.EVENT_NAME            

        @staticmethod
        async def acronym(update: Update, context: Context) -> StateCode:
            message = "Does the event have an acronym?"
            await TelegramProcess._reply(update, context, message, skippable=True)
            return NewEvent.ACRONYM
        
        @staticmethod
        async def acronym_clash(update: Update, context: Context, clash: EventDetails) -> StateCode:
            message = f'''That acronym is in our database already! \n\nIt currently corresponds to the event {clash.get('name')} ({clash.get('location')}). If you were intending to update that event, please use /UpdateEvent instead. If the acronyms genuinely clash, please enter an alternative acronym.'''
            await TelegramProcess._reply(update, context, message, skippable=True)
            return NewEvent.ACRONYM

        @staticmethod
        async def location(update: Update, context: Context) -> StateCode:
            message = '''What is the event's location? \nThis can be online, UK wide, or a specific town, city or region.'''
            await TelegramProcess._reply(update, context, message, keyboard=[["Online", "UK wide"]])
            return NewEvent.LOCATION

        @staticmethod
        async def venue(update: Update, context: Context) -> StateCode:
            message = '''What is the event's venue, if it has one?'''
            await TelegramProcess._reply(update, context, message, skippable=True)
            return NewEvent.VENUE
        
        @staticmethod
        async def contact_name(update: Update, context: Context) -> StateCode:
            message = '''Who is the contact for the event, if it has one?'''
            await TelegramProcess._reply(update, context, message, skippable=True)
            return NewEvent.CONTACT_NAME
        
        @staticmethod
        async def contact_platform(update: Update, context: Context) -> StateCode:
            message = '''What platform are they on? \nFor instance, Telegram, FetLife, Bluesky.'''
            await TelegramProcess._reply(update, context, message)
            return NewEvent.CONTACT_PLATFORM

        @staticmethod
        async def contact_pronouns(update: Update, context: Context) -> StateCode:
            message = "What are their pronouns?"
            await TelegramProcess._reply(update, context, message)
            return NewEvent.CONTACT_PRONOUNS

        @staticmethod
        async def contact_handle(update: Update, context: Context) -> StateCode:
            assert(update.message and update.message.text)
            message = ''
            platform: str = update.message.text.lower()
            match platform:
                case "telegram":
                    message = '''What is their Telegram handle? \nFor example, Taranau is "@aaderyn"'''
                case "fetlife":
                    message = '''What is their FetLife handle? \nFor example, Taranau is "Taranau"'''
                case "bluesky":
                    message = '''What is their Bluesky handle?'''
                case _:
                    message = '''Please provide a link to their profile.'''
            await TelegramProcess._reply(update, context, message)
            return NewEvent.CONTACT_HANDLE
        
        @staticmethod
        async def initial_timings(update: Update, context: Context) -> StateCode:
            message = '''Does this event have an initial date and time? \nIf yes, please provide in the format 'DD-MM-YYYY, HH:MM-HH:MM'. \nE.g. 30-01-2026, 08:00-23:30.'''
            await TelegramProcess._reply(update, context, message, skippable=True)
            return NewEvent.INITIAL_TIMINGS
        
        @staticmethod
        async def ticket_cost(update: Update, context: Context) -> StateCode:
            message = '''Is this event ticketed? \nIf yes, how much do tickets cost? \nE.g. £10, €15, free.'''
            await TelegramProcess._reply(update, context, message, keyboard=[["Free"]], skippable=True)
            return NewEvent.TICKET_COST
        
        @staticmethod
        async def ticket_link(update: Update, context: Context) -> StateCode:
            message = '''Please provide a link for the tickets.'''
            await TelegramProcess._reply(update, context, message)
            return NewEvent.TICKET_LINK
        
        @staticmethod
        async def event_link(update: Update, context: Context) -> StateCode:
            message = '''Please provide the main link for the event. \nE.g. a link to the telegram or whatsapp group, or a website.'''
            await TelegramProcess._reply(update, context, message, skippable=True)
            return NewEvent.EVENT_LINK
        
        @staticmethod
        async def add_to_database(update: Update, context: Context) -> StateCode:
            message = '''Would you like to add this event to the database?'''
            await TelegramProcess._reply(update, context, message, keyboard=[["Yes", "No"]])
            return NewEvent.ADD_TO_DATABASE
        
        @staticmethod
        async def add_to_calendar(update: Update, context: Context) -> StateCode:
            message = '''Would you like to add this event to the calendar? (dev note: currently adds to test calendar)'''
            await TelegramProcess._reply(update, context, message, keyboard=[["Yes", "No"]])    
            return NewEvent.ADD_TO_CALENDAR
        
        @staticmethod
        async def add_to_map(update: Update, context: Context) -> StateCode:
            message = '''Would you like to add this event to the map? (dev note: feature not currently implemented)'''
            await TelegramProcess._reply(update, context, message, keyboard=[["Yes", "No"]])
            return NewEvent.ADD_TO_MAP
        
        @staticmethod
        async def query_update_message(update: Update, context: Context) -> StateCode:
            message = '''Would you like to send an update message on telegram? (dev note: currently just sends to this chat)'''
            await TelegramProcess._reply(update, context, message, keyboard=[["Yes", "No"]])
            return NewEvent.SEND_UPDATE

        @staticmethod
        async def update_message(update: Update, context: Context, 
                                event_details: EventDetails, date: Optional[str] = None) -> StateCode:
            message = messages.new_event(event_details, date)
            await TelegramProcess._reply(update, context, message)
            return ConversationHandler.END

    class Conversation:

        @staticmethod
        def handler() -> ConversationHandler:
            conv = NewEvent.Conversation
            entry_points = [CommandHandler("NewEvent", conv.start)]
            states = {NewEvent.EVENT_NAME: [MessageHandler(filters.TEXT, conv.event_name)],
                      NewEvent.ACRONYM: [MessageHandler(filters.TEXT, conv.acronym),
                                         CallbackQueryHandler(conv.skip_acronym, pattern="skip")],
                      NewEvent.LOCATION: [MessageHandler(filters.TEXT, conv.location),
                                          CallbackQueryHandler(conv.location_online, pattern="Online"),
                                          CallbackQueryHandler(conv.location_uk_wide, pattern="UK wide")],
                      NewEvent.VENUE: [MessageHandler(filters.TEXT, conv.venue),
                                       CallbackQueryHandler(conv.skip_venue, pattern="skip")],
                      NewEvent.CONTACT_NAME: [MessageHandler(filters.TEXT, conv.contact_name),
                                              CallbackQueryHandler(conv.skip_contact, pattern="skip")],
                      NewEvent.CONTACT_PLATFORM: [MessageHandler(filters.TEXT, conv.contact_platform)],
                      NewEvent.CONTACT_HANDLE: [MessageHandler(filters.TEXT, conv.contact_handle)],
                      NewEvent.CONTACT_PRONOUNS: [MessageHandler(filters.TEXT, conv.contact_pronouns)],
                      NewEvent.INITIAL_TIMINGS: [MessageHandler(filters.TEXT, conv.initial_timings),
                                                 CallbackQueryHandler(conv.skip_initial_timings, pattern="skip")],
                      NewEvent.TICKET_COST: [MessageHandler(filters.TEXT, conv.ticket_cost),
                                             CallbackQueryHandler(conv.ticket_cost_free, pattern="Free"),
                                             CallbackQueryHandler(conv.skip_tickets, pattern="skip")],
                      NewEvent.TICKET_LINK: [MessageHandler(filters.TEXT, conv.ticket_link)],
                      NewEvent.EVENT_LINK: [MessageHandler(filters.TEXT, conv.event_link),
                                            CallbackQueryHandler(conv.skip_event_link, pattern="skip")],
                      NewEvent.ADD_TO_DATABASE: [CallbackQueryHandler(conv.add_to_database, pattern="Yes"),
                                                 CallbackQueryHandler(conv.not_add_to_database, pattern="No")],
                      NewEvent.ADD_TO_CALENDAR: [CallbackQueryHandler(conv.add_to_calendar, pattern="Yes"),
                                                 CallbackQueryHandler(conv.not_add_to_calendar, pattern="No")],
                      NewEvent.ADD_TO_MAP: [CallbackQueryHandler(conv.add_to_map, pattern="Yes"),
                                            CallbackQueryHandler(conv.not_add_to_map, pattern="No")],
                      NewEvent.SEND_UPDATE: [CallbackQueryHandler(conv.send_update_message, pattern="Yes"),
                                             CallbackQueryHandler(conv.not_send_update_message, pattern="No")]}
            new_event_handler = ConversationHandler(
                entry_points=entry_points, # type: ignore
                states=states, # type: ignore
                fallbacks = [CommandHandler("cancel", cancel)],
            )
            return new_event_handler

        @staticmethod
        async def start(update: Update, context: Context) -> StateCode:
            return await NewEvent._Message.event_name(update, context)

        @staticmethod
        async def event_name(update: Update, context: Context) -> StateCode:
            await TelegramProcess._save_data(update, context, var_name="event_name")
            return await NewEvent._Message.acronym(update, context)
        
        @staticmethod
        async def acronym(update: Update, context: Context) -> StateCode:
            assert(update.message and update.message.text)
            clash: Optional[EventDetails] = database.EventDatabase.Retrieve.check_acronym(update.message.text)
            if clash:
                return await NewEvent._Message.acronym_clash(update, context, clash)
            await TelegramProcess._save_data(update, context, var_name="event_acronym")
            return await NewEvent._Message.location(update, context)
        
        @staticmethod
        async def skip_acronym(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("Acronym skipped")
            return await NewEvent._Message.location(update, context)
        
        @staticmethod
        async def location(update: Update, context: Context) -> StateCode:
            await TelegramProcess._save_data(update, context, var_name="location")
            return await NewEvent._Message.venue(update, context)

        @staticmethod
        async def location_online(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            await TelegramProcess._save_data(update, context, var_name="location", value="Online")
            return await NewEvent._Message.venue(update, context)

        @staticmethod
        async def location_uk_wide(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            await TelegramProcess._save_data(update, context, var_name="location", value="UK wide")
            return await NewEvent._Message.venue(update, context)

        @staticmethod
        async def venue(update: Update, context: Context) -> StateCode:
            await TelegramProcess._save_data(update, context, var_name="venue")
            return await NewEvent._Message.contact_name(update, context)
        
        @staticmethod
        async def skip_venue(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("Venue skipped")
            return await NewEvent._Message.contact_name(update, context)
        
        @staticmethod
        async def contact_name(update: Update, context: Context) -> StateCode:
            await TelegramProcess._save_data(update, context, var_name="contact_name")
            return await NewEvent._Message.contact_platform(update, context)
        
        @staticmethod
        async def contact_platform(update: Update, context: Context) -> StateCode:
            await TelegramProcess._save_data(update, context, var_name="contact_platform")
            return await NewEvent._Message.contact_handle(update, context)

        @staticmethod
        async def contact_handle(update: Update, context: Context) -> StateCode:
            await TelegramProcess._save_data(update, context, var_name="contact_handle_or_link")
            return await NewEvent._Message.contact_pronouns(update, context)

        @staticmethod
        async def contact_pronouns(update: Update, context: Context) -> StateCode:
            await TelegramProcess._save_data(update, context, var_name="pronouns")
            return await NewEvent._Message.initial_timings(update, context)

        @staticmethod
        async def skip_contact(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("Event contact skipped")
            return await NewEvent._Message.initial_timings(update, context)
        
        @staticmethod
        async def initial_timings(update: Update, context: Context) -> StateCode:
            await TelegramProcess._save_data(update, context, var_name="initial_timings")
            return await NewEvent._Message.ticket_cost(update, context)
        
        @staticmethod
        async def skip_initial_timings(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("Initial timings skipped")
            return await NewEvent._Message.ticket_cost(update, context)
        
        @staticmethod
        async def ticket_cost(update: Update, context: Context) -> StateCode:
            await TelegramProcess._save_data(update, context, var_name="ticket_cost")
            return await NewEvent._Message.ticket_link(update, context)
        
        @staticmethod
        async def ticket_cost_free(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            await TelegramProcess._save_data(update, context, var_name="ticket_cost", value="Free")
            return await NewEvent._Message.ticket_link(update, context)

        @staticmethod
        async def ticket_link(update: Update, context: Context) -> StateCode:
            await TelegramProcess._save_data(update, context, var_name="ticket_link")
            return await NewEvent._Message.event_link(update, context)

        @staticmethod
        async def skip_tickets(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("Tickets skipped")
            return await NewEvent._Message.event_link(update, context)

        @staticmethod
        async def event_link(update: Update, context: Context) -> StateCode:
            await TelegramProcess._save_data(update, context, var_name="event_link")
            return await NewEvent._Message.add_to_database(update, context)

        @staticmethod
        async def skip_event_link(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("Event link skipped")
            return await NewEvent._Message.add_to_database(update, context)

        @staticmethod
        async def add_to_database(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            event_info: EventDetails = NewEvent._process_event_info(update, context)
            error = database.EventDatabase.Update.new(event_info)
            if error:
                await NewEvent._Message._Error.database(update, context, error)
            else:
                await NewEvent._Message._Success.database(update, context)
            return await NewEvent._Message.add_to_calendar(update, context)
        
        @staticmethod
        async def not_add_to_database(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("Did not add to database")
            return await NewEvent._Message.add_to_calendar(update, context)

        @staticmethod
        async def add_to_calendar(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            
            assert(context.user_data)
            date: Optional[str] = context.user_data.get('initial_timings')
            if date:
                start_date, end_date = TelegramProcess._process_date(date)
                event_info: EventDetails = NewEvent._process_event_info(update, context)
                event = calendar.add_event_to_calendar(start_date, end_date, event_info)
                if isinstance(event, HttpError):
                    await NewEvent._Message._Error.calendar(update, context, event)
                else:
                    await NewEvent._Message._Success.calendar(update, context, event)
            else:
                await NewEvent._Message._Error.no_provided_timings(update, context)
            return await NewEvent._Message.add_to_map(update, context)

        @staticmethod
        async def not_add_to_calendar(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("Did not add to calendar")
            return await NewEvent._Message.add_to_map(update, context)

        @staticmethod
        async def add_to_map(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            return await NewEvent._Message.query_update_message(update, context)
        
        @staticmethod
        async def not_add_to_map(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("Did not add to map")
            return await NewEvent._Message.query_update_message(update, context)

        @staticmethod
        async def send_update_message(update: Update, context: Context) -> StateCode:
            assert(update.callback_query and context.user_data)
            await update.callback_query.answer()
            event_details: EventDetails = NewEvent._process_event_info(update, context)
            date = context.user_data.get('initial_timings')
            if date:
                start_time, end_time = TelegramProcess._process_date(date)
                date = start_time.strftime("d/m/Y, H:M") + '-' + end_time.strftime("H:M")
            return await NewEvent._Message.update_message(update, context, event_details, date)

        @staticmethod
        async def not_send_update_message(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("Did not send update message")
            return ConversationHandler.END

class UpdateEvent:
    
    class _Message:

        class _Error:

            @staticmethod
            async def database(update: Update, context: Context, error: IntegrityError) -> StateCode:
                message = f'''Oh no! We couldn't update our database: {error} \nYou may have to manually resolve this problem. Are there any other changes to the event?'''
                await TelegramProcess._reply(update, context, message, keyboard=[["Yes", "No"]])
                return ConversationHandler.END

            @staticmethod
            async def calendar(update: Update, context: Context, 
                                error: HttpError) -> None:
                message = f'''Oh no! There was an error updating the calendar: {error.status_code} \nYou may have to manually resolve this problem.'''
                await TelegramProcess._reply(update, context, message)
                return None

            @staticmethod
            async def map(update: Update, context: Context, error) -> None:
                message = f'''Oh no! There was an error updating the map: {error} \nYou may have to manually resolve this problem.'''
                await TelegramProcess._reply(update, context, message)
                return None

        @staticmethod
        async def ask_event_name(update: Update, context: Context) -> StateCode:
            message = '''You're trying to update an event. \n\nWhat is the full name of the event?'''
            await TelegramProcess._reply(update, context, message)
            return UpdateEvent.Conversation.ASK_EVENT_NAME
        
        @staticmethod
        async def check_full_database(update: Update, context: Context) -> StateCode:
            message = f'''We didn't find an event matching the provided name. Would you like to look at a list of events in the database?'''
            await TelegramProcess._reply(update, context, message, keyboard=[["Yes", "No"]])
            return UpdateEvent.Conversation.CHECK_FULL_DATABASE
        
        @staticmethod
        async def list_database(update: Update, context: Context, 
                               event_database: list[EventDetails]) -> StateCode:
            message = f'''Here's a list of events in the database:\n'''
            for event in event_database:
                message += f"{event.get('name')} ({event.get('location')})\n"
            message += f"If your event is in this list, please use /UpdateEvent to edit it. If it is not, you may wish to use /NewEvent to add it to the database. \nThank you! Process closed."
            await TelegramProcess._reply(update, context, message)
            return ConversationHandler.END     
         
        @staticmethod
        async def check_event_name(update: Update, context: Context, 
                                 event: EventDetails) -> StateCode:
            message = f'''We found an event matching that name: {event.get('name')} ({event.get('location')}). \n\n Is this the event you meant?'''
            await TelegramProcess._reply(update, context, message, keyboard=[["Yes", "No"]])
            return UpdateEvent.Conversation.CHECK_EVENT_NAME
          
        @staticmethod
        async def select_update(update: Update, context: Context) -> StateCode:
            message = f'''Choice confirmed! What detail would you like to update about this event?'''
            await TelegramProcess._reply(update, context, message, keyboard=[["Name", "Location"], ["Contact", "Organisers"], ["Tickets", "Links"]])
            return UpdateEvent.Conversation.SELECT_UPDATE
        
        class Name:

            class Error:
                
                @staticmethod
                async def name_clash(update: Update, context: Context) -> StateCode:
                    message = f'''Oh no! That name is already in our database. Are there any other changes to the event?'''
                    await TelegramProcess._reply(update, context, message, keyboard=[["Yes", "No"]])
                    return ConversationHandler.END

                @staticmethod
                async def acronym_clash(update: Update, context: Context,
                                       clash: EventDetails) -> StateCode:
                    message = f'''Oh no! That acronym is already in our database, corresponding to {clash.get('name')} ({clash.get('location')}). Please try a different acronym!'''
                    await TelegramProcess._reply(update, context, message)
                    return UpdateEvent.Conversation.Name.EVENT_ACRONYM

            @staticmethod
            async def ask_name(update: Update, context: Context) -> StateCode:
                message = f'''What is the new name of the event?'''
                await TelegramProcess._reply(update, context, message)
                return UpdateEvent.Conversation.Name.EVENT_NAME

            @staticmethod
            async def ask_acronym(update: Update, context: Context) -> StateCode:
                message = f'''What is the new acronym for the event?'''
                await TelegramProcess._reply(update, context, message)
                return UpdateEvent.Conversation.Name.EVENT_ACRONYM

            @staticmethod
            async def name_updated(update: Update, context: Context) -> StateCode:
                message = f'''Thank you! These details have been updated! Are there further changes?'''
                await TelegramProcess._reply(update, context, message, keyboard=[["Yes", "No"]])
                return ConversationHandler.END

        class Location:
            
            class Error:
                pass

            @staticmethod
            async def ask_location(update: Update, context: Context) -> StateCode:
                message = f'''What's the event's location? E.g. online, UK wide, a specific city or town? If this is unchanged, please skip.'''
                await TelegramProcess._reply(update, context, message, keyboard=[["Online", "UK wide"]], skippable=True)
                raise NotImplementedError

            @staticmethod
            async def ask_venue(update: Update, context: Context) -> StateCode:
                message = f'''What's the event's new venue?'''
                await TelegramProcess._reply(update, context, message)
                raise NotImplementedError

            @staticmethod
            async def location_updated(update: Update, context: Context) -> StateCode:
                message = f'''Thank you! The location has been updated. Are there any further changes?'''
                await TelegramProcess._reply(update, context, message)
                return ConversationHandler.END

        class Contact:

            class Error:
                
                @staticmethod
                async def no_contact(update: Update, context: Context) -> StateCode:
                    message = f'''No organisers were found for this event! You may need to add some before setting the contact. Are there any other changes to the event?'''
                    await TelegramProcess._reply(update, context, message, keyboard=[["Yes", "No"]])
                    return ConversationHandler.END

            @staticmethod
            async def current_contact(update: Update, context: Context,
                                     contact: PersonDetails, organisers: list[PersonDetails]) -> StateCode:
                message = f'''The current contact for this event is {contact.get('name')} ({contact.get('pronouns')}). The saved organisers are: \n'''
                organiser_names = list(filter(None, [organiser.get('name') for organiser in organisers]))
                for name in organiser_names:
                    message += f"{name}\n"
                message += f'''If you'd like to change the contact, select one of the other organisers. If you want to add a new organiser as the contact, please skip, then add the organiser.'''
                keyboard = [organiser_names[i:i + 2] for i in range(0, len(organiser_names), 2)]
                await TelegramProcess._reply(update, context, message, keyboard, skippable=True)
                return UpdateEvent.Conversation.Contact.PICK_CONTACT

            @staticmethod
            async def skip_contact(update: Update, context: Context) -> StateCode:
                message = f'''Contact not updated. Are there any other changes to the event?'''
                await TelegramProcess._reply(update, context, message, keyboard=[["Yes", "No"]])
                return ConversationHandler.END
            
            @staticmethod
            async def contact_updated(update: Update, context: Context) -> StateCode:
                message = f'''Successfully updated contact! Are there any other changes to the event?'''
                await TelegramProcess._reply(update, context, message, keyboard=[["Yes", "No"]])
                return ConversationHandler.END

        class Organisers:

            class Error:
                pass

            @staticmethod
            async def query_add_remove_or_update(update: Update, context: Context) -> StateCode:
                message = f'''Do you want to add a new organiser, remove an existing organiser, or update an existing organiser?'''
                await TelegramProcess._reply(update, context, message, keyboard=[["Add", "Remove"], ["Update"]])
                raise NotImplementedError
            
            class Add:

                @staticmethod
                async def name(update: Update, context: Context) -> StateCode:
                    message = f'''What is the organiser's name?'''
                    await TelegramProcess._reply(update, context, message)
                    raise NotImplementedError

                @staticmethod
                async def pronouns(update: Update, context: Context) -> StateCode:
                    message = f'''What are the organiser's pronouns?'''
                    await TelegramProcess._reply(update, context, message)
                    raise NotImplementedError

                class SocialMedia:

                    @staticmethod
                    async def site(update: Update, context: Context) -> StateCode:
                        message = f'''Which social media do you want to add?'''
                        keyboard = [["Telegram", "FetLife"], ["Bluesky"]]
                        await TelegramProcess._reply(update, context, message, keyboard)
                        raise NotImplementedError
                    
                    @staticmethod
                    async def telegram(update: Update, context: Context) -> StateCode:
                        message = f'''What is their Telegram handle?'''
                        await TelegramProcess._reply(update, context, message)
                        raise NotImplementedError

                    @staticmethod
                    async def fetlife(update: Update, context: Context) -> StateCode:
                        message = f'''What is their FetLife ID?'''
                        await TelegramProcess._reply(update, context, message)
                        raise NotImplementedError
                    
                    @staticmethod
                    async def bluesky(update: Update, context: Context) -> StateCode:
                        message = f'''What is their Bluesky handle?'''
                        await TelegramProcess._reply(update, context, message)
                        raise NotImplementedError

            class Remove:

                @staticmethod
                async def pick(update: Update, context: Context, 
                               organisers: list[PersonDetails]) -> StateCode:
                    message = f'''Which organiser would you like to remove?\n'''
                    organiser_names = list(filter(None, [organiser.get('name') for organiser in organisers]))
                    for name in organiser_names:
                        message += f"{name}\n"
                    keyboard = [organiser_names[i:i + 2] for i in range(0, len(organiser_names), 2)]
                    await TelegramProcess._reply(update, context, message, keyboard)
                    raise NotImplementedError
                
                @staticmethod
                async def confirm_choice(update: Update, context: Context, 
                                        candidate: PersonDetails) -> StateCode:
                    message = f'''Are you sure you want to remove {candidate.get('name')}?'''
                    await TelegramProcess._reply(update, context, message, keyboard=[["Yes", "No"]])
                    raise NotImplementedError
                
                @staticmethod
                async def organiser_removed(update: Update, context: Context, 
                                           candidate: PersonDetails) -> StateCode:
                    message = f'''{candidate.get('name')} successfully removed! Are there any other changes to the event?'''
                    await TelegramProcess._reply(update, context, message, keyboard=[["Yes", "No"]])
                    return ConversationHandler.END

            class UpdateDetails:

                @staticmethod
                async def pick(update: Update, context: Context, 
                               organisers: list[PersonDetails]) -> StateCode:
                    message = f'''Which organiser would you like to update?\n'''
                    organiser_names = list(filter(None, [organiser.get('name') for organiser in organisers]))
                    for name in organiser_names:
                        message += f"{name}\n"
                    keyboard = [organiser_names[i:i + 2] for i in range(0, len(organiser_names), 2)]
                    await TelegramProcess._reply(update, context, message, keyboard)
                    raise NotImplementedError

                @staticmethod
                async def detail(update: Update, context: Context) -> StateCode:
                    message = f'''What would you like to update about this organiser?'''
                    keyboard = [["Name", "pronouns"], ["Social media handles"]]
                    await TelegramProcess._reply(update, context, message, keyboard)
                    raise NotImplementedError

                @staticmethod
                async def name(update: Update, context: Context) -> StateCode:
                    message = f'''What is the organiser's new name?'''
                    await TelegramProcess._reply(update, context, message)
                    raise NotImplementedError

                @staticmethod
                async def pronouns(update: Update, context: Context) -> StateCode:
                    message = f'''What are the organiser's new pronouns?'''
                    await TelegramProcess._reply(update, context, message)
                    raise NotImplementedError

                class SocialMedia:

                    @staticmethod
                    async def site(update: Update, context: Context) -> StateCode:
                        message = f'''Which social media do you want to update?'''
                        keyboard = [["Telegram", "FetLife"], ["Bluesky"]]
                        await TelegramProcess._reply(update, context, message, keyboard)
                        raise NotImplementedError
                    
                    @staticmethod
                    async def telegram(update: Update, context: Context) -> StateCode:
                        message = f'''What is their new Telegram handle?'''
                        await TelegramProcess._reply(update, context, message)
                        raise NotImplementedError

                    @staticmethod
                    async def fetlife(update: Update, context: Context) -> StateCode:
                        message = f'''What is their new FetLife ID?'''
                        await TelegramProcess._reply(update, context, message)
                        raise NotImplementedError
                    
                    @staticmethod
                    async def bluesky(update: Update, context: Context) -> StateCode:
                        message = f'''What is their new Bluesky handle?'''
                        await TelegramProcess._reply(update, context, message)
                        raise NotImplementedError

        class Tickets:

            @staticmethod
            async def ask_price(update: Update, context: Context) -> StateCode:
                message = f'''Has the ticket price changed? If so, enter the new price (e.g. £5, Free, $10). If not, please skip.'''
                await TelegramProcess._reply(update, context, message, skippable=True)
                return UpdateEvent.Conversation.Tickets.PRICE
            
            @staticmethod
            async def ask_link(update: Update, context: Context) -> StateCode:
                message = f'''Has the ticket link changed? If so, enter the new link. If not, please skip.'''
                await TelegramProcess._reply(update, context, message, skippable=True)
                return UpdateEvent.Conversation.Tickets.LINK
            
            @staticmethod
            async def tickets_updated(update: Update, context: Context) -> StateCode:
                message = f'''Ticket details successfully updated! Are there any other changes to the event?'''
                await TelegramProcess._reply(update, context, message, keyboard=[["Yes", "No"]])
                return ConversationHandler.END

        class Links:
            pass

        @staticmethod
        async def end_conversation(update: Update, context: Context) -> StateCode:
            message = f'''Thank you! Please pick another command, if you want.'''
            await TelegramProcess._reply(update, context, message)
            return ConversationHandler.END

    class Conversation:

        ASK_EVENT_NAME, CHECK_FULL_DATABASE, CHECK_EVENT_NAME, SELECT_UPDATE, CONTINUE_UPDATE = range(5)

        @staticmethod
        def handler() -> ConversationHandler:
            conv = UpdateEvent.Conversation
            entry_points = [CommandHandler("UpdateEvent", conv.start)]
            states = {conv.ASK_EVENT_NAME: [MessageHandler(filters.TEXT, conv.event_name)],
                      conv.CHECK_FULL_DATABASE: [
                          CallbackQueryHandler(conv.check_full_database, pattern="Yes"), 
                          CallbackQueryHandler(conv.not_check_database, pattern="No")],
                      conv.CHECK_EVENT_NAME: [
                          CallbackQueryHandler(conv.confirm_event_name, pattern="Yes"), 
                          CallbackQueryHandler(conv.deny_event_name, pattern="No")],
                      conv.SELECT_UPDATE: [conv.Name.handler(),
                                           conv.Location.handler(),
                                           conv.Contact.handler(),
                                           conv.Organisers.handler(),
                                           conv.Tickets.handler(),
                                           conv.Links.handler()],
                     }
            handler = ConversationHandler(entry_points=entry_points, # type: ignore
                                          states=states, #type: ignore
                                          fallbacks=[CommandHandler("cancel", cancel)])
            return handler

        @staticmethod
        async def start(update: Update, context: Context) -> StateCode:
            return await UpdateEvent._Message.ask_event_name(update, context)

        @staticmethod
        async def event_name(update: Update, context: Context) -> StateCode:
            assert(update.message and (name:=update.message.text))
            event = database.EventDatabase.Retrieve.from_name(name)
            assert(context.user_data)
            context.user_data['event'] = event
            if event:
                return await UpdateEvent._Message.check_event_name(update, context, event)
            else:
                return await UpdateEvent._Message.check_full_database(update, context)
            
        @staticmethod
        async def check_full_database(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            event_database = database.EventDatabase.Retrieve.full_database()
            return await UpdateEvent._Message.list_database(update, context, event_database)
        
        @staticmethod
        async def not_check_database(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            return await UpdateEvent._Message.end_conversation(update, context)

        @staticmethod
        async def deny_event_name(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            return await UpdateEvent._Message.check_full_database(update, context)

        @staticmethod
        async def confirm_event_name(update: Update, context: Context) -> StateCode:
            assert(update.callback_query)
            await update.callback_query.answer()
            return await UpdateEvent._Message.select_update(update, context)

        class Name:

            EVENT_NAME, EVENT_ACRONYM = range(2)

            @staticmethod
            def handler() -> ConversationHandler:
                conv = UpdateEvent.Conversation.Name
                entry_points = [CallbackQueryHandler(conv.start, "Name")]
                states = {conv.EVENT_NAME: MessageHandler(filters.TEXT, conv.event_name),
                          conv.EVENT_ACRONYM: MessageHandler(filters.TEXT, conv.event_acronym)}
                handler = ConversationHandler(entry_points=entry_points, # type: ignore
                                              states=states, # type: ignore
                                              fallbacks=[CommandHandler("cancel", cancel)],
                                              map_to_parent={ConversationHandler.END: UpdateEvent.Conversation.CONTINUE_UPDATE})
                return handler
            
            @staticmethod
            async def start(update: Update, context: Context) -> StateCode:
                assert(update.callback_query)
                await update.callback_query.answer()
                return await UpdateEvent._Message.Name.ask_name(update, context)
            
            @staticmethod
            async def event_name(update: Update, context: Context) -> StateCode:
                assert(update.message)
                name = update.message.text
                clash = database.EventDatabase.Retrieve.from_name(name)
                if clash:
                    return await UpdateEvent._Message.Name.Error.name_clash(update, context)
                await TelegramProcess._save_data(update, context, var_name="new_name")
                return await UpdateEvent._Message.Name.ask_acronym(update, context)

            @staticmethod
            async def event_acronym(update: Update, context: Context) -> StateCode:
                assert(update.message and update.message.text)
                new_acronym = update.message.text
                clash = database.EventDatabase.Retrieve.check_acronym(new_acronym)
                if clash:
                    return await UpdateEvent._Message.Name.Error.acronym_clash(update, context, clash)
                await TelegramProcess._save_data(update, context, var_name="new_acronym")
                return await UpdateEvent.Conversation.Name._handle_update(update, context)                

            @staticmethod
            async def _handle_update(update: Update, context: Context) -> StateCode:
                error = UpdateEvent.Conversation.Name._update_external(context)
                if error:
                    db_error, calendar_error, map_error = error
                    if db_error:
                        return await UpdateEvent._Message._Error.database(update, context, db_error)
                    if calendar_error:
                        await UpdateEvent._Message._Error.calendar(update, context, calendar_error)
                    if map_error:
                        await UpdateEvent._Message._Error.map(update, context, map_error)
                return await UpdateEvent._Message.Name.name_updated(update, context)                

            @staticmethod
            def _update_external(context: Context) -> Optional[UpdateError]:
                assert(context.user_data)
                event: Optional[EventDetails] = context.user_data.get('event')
                new_name: Optional[str] = context.user_data.get('new_name')
                new_acronym: Optional[str] = context.user_data.get('new_acronym')
                assert(event)
                
                db_error = database.EventDatabase.Update.name(event, new_name, new_acronym)
                if db_error:
                    return db_error, None, None
                calendar_error = calendar.Update.name(event, new_name, new_acronym)
                map_error = None # Add to map
                return (None, calendar_error, map_error) if (calendar_error or map_error) else None

        class Location:

            LOCATION, VENUE = range(2)

            @staticmethod
            def handler() -> ConversationHandler:
                conv = UpdateEvent.Conversation.Location
                entry_points = [CallbackQueryHandler(conv.start, "Location")]
                states = {conv.LOCATION: [CallbackQueryHandler(conv.skip_location, pattern = "skip"),
                                          CallbackQueryHandler(conv.location_online, pattern="Online"),
                                          CallbackQueryHandler(conv.location_uk_wide, pattern="UK Wide"),
                                          MessageHandler(filters.TEXT, conv.location)],
                          conv.VENUE: [MessageHandler(filters.TEXT, conv.venue)]}
                handler = ConversationHandler(entry_points=entry_points, # type: ignore
                                              states=states, # type: ignore
                                              fallbacks=[CommandHandler("cancel", cancel)],
                                              map_to_parent={ConversationHandler.END: UpdateEvent.Conversation.CONTINUE_UPDATE})
                return handler
            
            @staticmethod
            async def start(update: Update, context: Context) -> StateCode:
                assert(update.callback_query)
                await update.callback_query.answer()
                return await UpdateEvent._Message.Location.ask_location(update, context)

            @staticmethod
            async def skip_location(update: Update, context: Context) -> StateCode:
                assert(update.callback_query)
                await update.callback_query.answer()
                return await UpdateEvent._Message.Location.ask_venue(update, context)

            @staticmethod
            async def location_online(update: Update, context: Context) -> StateCode:
                assert(update.callback_query)
                await update.callback_query.answer()
                await TelegramProcess._save_data(update, context, var_name="new_location", value="Online")
                return await UpdateEvent.Conversation.Location._handle_update(update, context)

            @staticmethod
            async def location_uk_wide(update: Update, context: Context) -> StateCode:
                assert(update.callback_query)
                await update.callback_query.answer()
                await TelegramProcess._save_data(update, context, var_name="new_location", value="UK wide")
                return await UpdateEvent.Conversation.Location._handle_update(update, context)

            @staticmethod
            async def location(update: Update, context: Context) -> StateCode:
                await TelegramProcess._save_data(update, context, var_name="new_location")
                return await UpdateEvent._Message.Location.ask_venue(update, context)

            @staticmethod
            async def venue(update: Update, context: Context) -> StateCode:
                await TelegramProcess._save_data(update, context, var_name="new_venue")
                return await UpdateEvent.Conversation.Location._handle_update(update, context)
            
            @staticmethod
            async def _handle_update(update: Update, context: Context) -> StateCode:
                error = UpdateEvent.Conversation.Location._update_external(context)
                if error:
                    db_error, calendar_error, map_error = error
                    if db_error:
                        return await UpdateEvent._Message._Error.database(update, context, db_error)
                    if calendar_error:
                        await UpdateEvent._Message._Error.calendar(update, context, calendar_error)
                    if map_error:
                        await UpdateEvent._Message._Error.map(update, context, map_error)
                return await UpdateEvent._Message.Location.location_updated(update, context)

            @staticmethod
            def _update_external(context: Context) -> Optional[UpdateError]:
                raise NotImplementedError

        class Contact:

            PICK_CONTACT = 1

            @staticmethod
            def handler() -> ConversationHandler:
                conv = UpdateEvent.Conversation.Contact
                entry_points = [CallbackQueryHandler(conv.start, "Contact")]
                states = {conv.PICK_CONTACT: [CallbackQueryHandler(conv.skip_contact, pattern="skip"),
                                              CallbackQueryHandler(conv.pick_contact, pattern="^(?!skip)$")]}
                handler = ConversationHandler(entry_points=entry_points, # type: ignore
                                              states=states, # type: ignore
                                              fallbacks=[CommandHandler("cancel", cancel)],
                                              map_to_parent={ConversationHandler.END: UpdateEvent.Conversation.CONTINUE_UPDATE})
                return handler
            
            @staticmethod
            async def start(update: Update, context: Context) -> StateCode:
                assert(context.user_data)
                event: Optional[EventDetails] = context.user_data.get('event')
                assert(event)
                contact = event.get('contact')
                organisers = event.get('organisers')
                if contact and organisers:
                    return await UpdateEvent._Message.Contact.current_contact(update, context, contact, organisers)
                return await UpdateEvent._Message.Contact.Error.no_contact(update, context)

            @staticmethod
            async def skip_contact(update: Update, context: Context) -> StateCode:
                assert(query := update.callback_query)
                await query.answer()
                return await UpdateEvent._Message.Contact.skip_contact(update, context)
            
            @staticmethod
            async def pick_contact(update: Update, context: Context) -> StateCode:
                assert(query := update.callback_query)
                await query.answer()
                await TelegramProcess._save_data(update, context, var_name="new_contact", value=query.data)
                return await UpdateEvent.Conversation.Contact._handle_update(update, context)
            
            @staticmethod
            async def _handle_update(update: Update, context: Context) -> StateCode:
                error = UpdateEvent.Conversation.Contact._update_external(context)
                if error:
                    db_error, calendar_error, map_error = error
                    if db_error:
                        return await UpdateEvent._Message._Error.database(update, context, db_error)
                    if calendar_error:
                        await UpdateEvent._Message._Error.calendar(update, context, calendar_error)
                    if map_error:
                        await UpdateEvent._Message._Error.map(update, context, map_error)
                return await UpdateEvent._Message.Contact.contact_updated(update, context)

            @staticmethod
            def _update_external(context: Context) -> Optional[UpdateError]:
                raise NotImplementedError

        class Organisers:

            @staticmethod
            def handler() -> ConversationHandler:
                conv = UpdateEvent.Conversation.Organisers
                entry_points = [CallbackQueryHandler(conv.start, "Organisers")]
                states = {1:1}
                handler = ConversationHandler(entry_points=entry_points, # type: ignore
                                              states=states, # type: ignore
                                              fallbacks=[CommandHandler("cancel", cancel)],
                                              map_to_parent={ConversationHandler.END: UpdateEvent.Conversation.CONTINUE_UPDATE})
                raise NotImplementedError
            
            @staticmethod
            async def start(update: Update, context: Context) -> StateCode:
                raise NotImplementedError      

        class Tickets:

            PRICE, LINK = range(2)

            @staticmethod
            def handler() -> ConversationHandler:
                conv = UpdateEvent.Conversation.Tickets
                entry_points = [CallbackQueryHandler(conv.start, "Tickets")]
                states = {conv.PRICE: [MessageHandler(filters.TEXT, conv.price),
                                       CallbackQueryHandler(conv.skip_price, "skip")],
                          conv.LINK: [MessageHandler(filters.TEXT, conv.link),
                                      CallbackQueryHandler(conv.skip_link, "skip")]}
                handler = ConversationHandler(entry_points=entry_points, # type: ignore
                                              states=states, # type: ignore
                                              fallbacks=[CommandHandler("cancel", cancel)],
                                              map_to_parent={ConversationHandler.END: UpdateEvent.Conversation.CONTINUE_UPDATE})
                return handler
            
            @staticmethod
            async def start(update: Update, context: Context) -> StateCode:
                return await UpdateEvent._Message.Tickets.ask_price(update, context)
            
            @staticmethod
            async def skip_price(update: Update, context: Context) -> StateCode:
                return await UpdateEvent._Message.Tickets.ask_link(update, context)

            @staticmethod
            async def price(update: Update, context: Context) -> StateCode:
                await TelegramProcess._save_data(update, context, var_name="new_ticket_price")
                return await UpdateEvent._Message.Tickets.ask_link(update, context)
            
            @staticmethod
            async def skip_link(update: Update, context: Context) -> StateCode:
                return await UpdateEvent.Conversation.Tickets._handle_update(update, context)

            @staticmethod
            async def link(update: Update, context: Context) -> StateCode:
                await TelegramProcess._save_data(update, context, var_name="new_ticket_link")
                return await UpdateEvent.Conversation.Tickets._handle_update(update, context)
                        
            @staticmethod
            async def _handle_update(update: Update, context: Context) -> StateCode:
                error = UpdateEvent.Conversation.Tickets._update_external(context)
                if error:
                    db_error, calendar_error, map_error = error
                    if db_error:
                        return await UpdateEvent._Message._Error.database(update, context, db_error)
                    if calendar_error:
                        await UpdateEvent._Message._Error.calendar(update, context, calendar_error)
                    if map_error:
                        await UpdateEvent._Message._Error.map(update, context, map_error)
                return await UpdateEvent._Message.Tickets.tickets_updated(update, context)

            @staticmethod
            def _update_external(context: Context) -> Optional[UpdateError]:
                raise NotImplementedError

        class Links:

            @staticmethod
            def handler() -> ConversationHandler:
                conv = UpdateEvent.Conversation.Links
                entry_points = [CallbackQueryHandler(conv.start, "Links")]
                states = {1:1}
                handler = ConversationHandler(entry_points=entry_points, # type: ignore
                                              states=states, # type: ignore
                                              fallbacks=[CommandHandler("cancel", cancel)],
                                              map_to_parent={ConversationHandler.END: UpdateEvent.Conversation.CONTINUE_UPDATE})
                raise NotImplementedError
            
            @staticmethod
            async def start(update: Update, context: Context) -> StateCode:
                raise NotImplementedError

async def cancel(update: Update, _: Context) -> StateCode:
    """Cancels and ends the conversation."""
    assert(update.message)
    await update.message.reply_text(
        "Bye! I hope we can talk again some day.", reply_markup=ReplyKeyboardRemove()
    )

    return ConversationHandler.END

def run_bot(TELEGRAM_KEY: str) -> None:
    application = ApplicationBuilder().token(TELEGRAM_KEY).build()

    help_handler = CommandHandler('help', help)
    application.add_handler(help_handler)

    # update_event_handler = CommandHandler('UpdateEvent', UpdateEvent)
    # application.add_handler(update_event_handler)
 
    # meta_handler = CommandHandler('Meta', Meta)
    # application.add_handler(meta_handler)

    new_event_handler = NewEvent.Conversation.handler()
    application.add_handler(new_event_handler)

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    run_bot(API_KEYS["TELEGRAM_KEY"])
