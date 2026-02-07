import peewee as pw
from typing import Literal, Optional

from PetCalendarBot.common.types import (
    EventDetails,
    EventLinks,
    PersonDetails
)
from PetCalendarBot.common.database_info import (
    DATABASE,
    Person,
    Event,
    Links
)

def _InitialiseDatabase(db: pw.SqliteDatabase) -> None:
    db.create_tables([Event, Person, Links])
    return None

def _PreprocessDatabase() -> pw.SqliteDatabase:
    db = pw.SqliteDatabase(DATABASE)
    db.connect()
    _InitialiseDatabase(db)
    return db

def _PostprocessDatabase(db: pw.SqliteDatabase) -> None:
    db.close()
    return None


def Database(func):
    def DBWrapper(*args, **kwargs):
        db = _PreprocessDatabase()
        result = func(*args, **kwargs)
        _PostprocessDatabase(db)
        return result
        
    return DBWrapper

class ManageEvent:

    @staticmethod
    @Database
    def GetDetailsFromName(event_name: str|None) -> Optional[EventDetails]:
        if event_name is None:
            return None
        part_event_details = Event.select().where(Event.name == event_name).dicts()
        if not part_event_details or (city:=part_event_details[0].get('city')) is None:
            return None
        part_event_details = part_event_details[0]

        contact: PersonDetails|None = None
        aux_contact = Person.select().where((Person.associatedEvent==event_name) & (Person.designatedContact==True)).dicts()
        if len(aux_contact)>0:
            aux_contact = aux_contact[0]
            aux_contact.pop('associatedEvent')
            aux_contact.pop('designatedContact')
            contact = aux_contact

        aux_organisers = Person.select().where(Person.associatedEvent==event_name).dicts()
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
                                       
                                       'city':city,
                                       'venue':part_event_details.get('venue'),
                                       'addressLink':part_event_details.get('addressLink'),
                                       
                                       'contact':contact,
                                       'organisers':organisers,
                                       'links':links}
        return event_details
    
    @staticmethod
    @Database
    def CheckAcronym(acronym: str) -> Optional[str]:
        event_details = Event.select().where(Event.acronym == acronym).dicts()
        if not event_details:
            return None
        event_details = event_details[0]
        return event_details.get('name')

    @staticmethod
    @Database
    def New(event: EventDetails) -> None:
        event_data = Event.insert(name=event['name'],
                          acronym=event['acronym'],
                          city=event['city'],
                          venue=event['venue'],
                          addressLink=event['addressLink'])
        event_data.execute()

        links = event['links']
        if not links is None:
            link_data = Links.insert(event=event['name'],
                            telegramChatLink=links['telegramChatLink'],
                            fetlifeLink=links['fetlifeLink'],
                            otherSocialLink=links['otherSocialLink'],
                            otherLink=links['otherLink'])
            link_data.execute()

        contact = event['contact']
        if not contact is None:
            contact_data = Person.insert(name=contact['name'],
                                pronouns=contact['pronouns'],
                                telegramHandle=contact['telegramHandle'],
                                blueskyHandle=contact['blueskyHandle'],
                                fetlifeID=contact['fetlifeID'],
                                associatedEvent=event['name'],
                                designatedContact=True)
            contact_data.execute()
        return None

    @staticmethod
    @Database
    def UpdateLink(event: EventDetails, 
                    link: str,
                    linkType: Literal['Telegram', 
                                      'Fetlife', 
                                      'Other social', 
                                      'Other non-social']) -> None:
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
    @Database
    def VenueChange(event: EventDetails, 
                    new_venue: str) -> None:
        row = Event.get(Event.name==event['name'])
        row.venue = new_venue
        row.save()
        return None

class ManagePerson:
    
    @staticmethod
    @Database
    def New(event_name: str, person: PersonDetails, designated_contact: bool=False) -> None:
        data = Person(**person,
                      associatedEvent=event_name,
                      designatedContact=designated_contact)
        data.save()
        return None
    
    @staticmethod
    @Database
    def UpdatePronouns(person: PersonDetails, newPronouns: str) -> None:
        data = Person(name = person['name'],
                      pronouns = newPronouns)
        data.save()
        return None