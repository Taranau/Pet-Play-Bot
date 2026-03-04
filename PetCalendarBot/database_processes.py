# ------Libraries------
import peewee as pw

from PetCalendarBot.common.database_info import (
    DATABASE,
    Person,
    Event,
    Links
)
# --------Types--------
from typing import Literal, Optional

from PetCalendarBot.common.types import (
    EventDetails,
    EventLinks,
    PersonDetails
)
# ----Database wrap----
def _initialise_database(db: pw.SqliteDatabase) -> None:
    db.create_tables([Event, Person, Links])
    return None

def _preprocess_database() -> pw.SqliteDatabase:
    db = pw.SqliteDatabase(DATABASE)
    db.connect()
    _initialise_database(db)
    return db

def _postprocess_database(db: pw.SqliteDatabase) -> None:
    db.close()
    return None

def database(func):
    def db_wrapper(*args, **kwargs):
        db = _preprocess_database()
        result = func(*args, **kwargs)
        _postprocess_database(db)
        return result
        
    return db_wrapper
# --------Code---------

class EventDatabase:

    class Retrieve:

        @staticmethod
        @database
        def from_name(event_name: str|None) -> Optional[EventDetails]:
            if event_name is None:
                return None
            part_event_details = Event.select().where(Event.name == event_name).dicts()
            if not part_event_details or (location:=part_event_details[0].get('location')) is None:
                return None
            part_event_details = part_event_details[0]

            contact: PersonDetails|None = None
            aux_contact = Person.select().where((Person.associated_event==event_name) & (Person.designated_contact==True)).dicts()
            if len(aux_contact)>0:
                aux_contact = aux_contact[0]
                aux_contact.pop('associatedEvent')
                aux_contact.pop('designatedContact')
                contact = aux_contact

            aux_organisers = Person.select().where(Person.associated_event==event_name).dicts()
            organisers: list[PersonDetails] = []
            if len(aux_organisers)>0:
                for person in aux_organisers:
                    person.pop('associatedEvent')
                    person.pop('designatedContact')
                    organisers.append(person)

            links: EventLinks|None = None
            aux_links = Links.select().where(Links.event==event_name).dicts()
            if len(aux_links)>0:
                aux_links = aux_links[0]
                aux_links.pop('event')
                links = aux_links

            event_details: EventDetails = {'name':event_name,
                                        'acronym':part_event_details.get('acronym'),
                                        
                                        'location':location,
                                        'venue':part_event_details.get('venue'),
                                        'addressLink':part_event_details.get('addressLink'),

                                        'ticketPrice':part_event_details.get('ticketPrice'),
                                        'ticketLink':part_event_details.get('ticketLink'),
                                        
                                        'contact':contact,
                                        'organisers':organisers,
                                        'links':links}
            return event_details
        
        @staticmethod
        @database
        def check_acronym(acronym: str) -> Optional[EventDetails]:
            event_detail_list = Event.select().where(Event.acronym == acronym).dicts()
            return event_detail_list[0] if event_detail_list else None

        @staticmethod
        @database
        def full_database() -> list[EventDetails]:
            return Event.select().dicts()

    class Update:

        @staticmethod
        @database
        def new(event: EventDetails) -> Optional[tuple[Optional[pw.IntegrityError], Optional[pw.IntegrityError], Optional[pw.IntegrityError]]]:
            event_error, link_error, contact_error = None, None, None
            try:
                event_data = Event.insert(name=event['name'],
                                        acronym=event['acronym'],
                                        location=event['location'],
                                        venue=event['venue'],
                                        addressLink=event['addressLink'])
                event_data.execute()
            except pw.IntegrityError as error:
                event_error = error

            links = event['links']
            if links:
                try:
                    link_data = Links.insert(event=event['name'],
                                            telegramChatLink=links['telegramChatLink'],
                                            fetlifeLink=links['fetlifeLink'],
                                            otherSocialLink=links['otherSocialLink'],
                                            otherLink=links['otherLink'])
                    link_data.execute()
                except pw.IntegrityError as error:
                    link_error = error

            contact = event['contact']
            if contact:
                try:
                    contact_data = Person.insert(name=contact['name'],
                                                pronouns=contact['pronouns'],
                                                telegramHandle=contact['telegramHandle'],
                                                blueskyHandle=contact['blueskyHandle'],
                                                fetlifeID=contact['fetlifeID'],
                                                associatedEvent=event['name'],
                                                designatedContact=True)
                    contact_data.execute()
                except pw.IntegrityError as error:
                    contact_error = error
            return (event_error, link_error, contact_error) if (event_error or link_error or contact_error) else None

        @staticmethod
        @database
        def name(event: EventDetails, new_name: Optional[str], new_acronym: Optional[str]) -> Optional[pw.IntegrityError]:
            raise NotImplementedError

        @staticmethod
        @database
        def update_link(event: EventDetails, 
                        link: str,
                        linkType: Literal['Telegram', 
                                        'Fetlife', 
                                        'Other social', 
                                        'Other non-social']) -> None:
            raise NotImplementedError
            row = Links.get(Links.event==event['name'])
            match linkType:
                case 'Telegram':
                    row.telegramChatLink = link
                case 'Fetlife':
                    row.fetlifeLink = link
                case 'Other social':
                    row.otherSocialLink = link
                case 'Other non-social':
                    row.otherLink = link
            row.save()
            return None

        @staticmethod
        @database
        def location_change(event: EventDetails,
                           location: str,
                           new_venue: str) -> None:
            raise NotImplementedError
            row = Event.get(Event.name==event['name'])
            row.venue = new_venue
            row.save()
            return None

class ManagePerson:
    
    @staticmethod
    @database
    def new(event_name: str, person: PersonDetails, designated_contact: bool=False) -> None:
        raise NotImplementedError
        data = Person(**person,
                      associatedEvent=event_name,
                      designatedContact=designated_contact)
        data.save()
        return None
    
    @staticmethod
    @database
    def update_pronouns(person: PersonDetails, newPronouns: str) -> None:
        raise NotImplementedError
        data = Person(name = person['name'],
                      pronouns = newPronouns)
        data.save()
        return None
