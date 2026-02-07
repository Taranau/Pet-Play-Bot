from typing import (
    TypedDict,
    TypeAlias,
    Optional
    )

MarkdownString: TypeAlias = str


class EventLinks(TypedDict):
    telegramChatLink: Optional[str]
    fetlifeLink: Optional[str]
    otherSocialLink: Optional[str]
    ticketLink: Optional[str]
    otherLink: Optional[str]

class PersonDetails(TypedDict):
    name: str
    pronouns: str
    telegramHandle: Optional[str]
    blueskyHandle: Optional[str]
    fetlifeID: Optional[str]

class EventDetails(TypedDict):
    name: str
    acronym: Optional[str]

    city: str
    venue: Optional[str]
    addressLink: Optional[str]

    contact: Optional[PersonDetails]
    organisers: Optional[list[PersonDetails]]
    
    ticketPrice: Optional[str]

    links: Optional[EventLinks]
