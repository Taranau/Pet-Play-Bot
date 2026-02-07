import peewee as pw

DATABASE: str = 'event_database.db'

db = pw.SqliteDatabase(DATABASE)

class Event(pw.Model):
    name = pw.CharField(primary_key=True)
    acronym = pw.CharField(null=True)

    city = pw.CharField()
    venue = pw.CharField(null=True)
    addressLink = pw.CharField(null=True)

    ticket_price = pw.CharField(null=True)

    class Meta:
        database = db

class Links(pw.Model):
    event = pw.ForeignKeyField(Event, backref='links')
    telegramChatLink = pw.CharField(null=True)
    fetlifeLink = pw.CharField(null=True)
    otherSocialLink = pw.CharField(null=True)
    ticketLink = pw.CharField(null=True)
    otherLink = pw.CharField(null=True)

    class Meta:
        database = db

class Person(pw.Model):
    name = pw.CharField(primary_key=True)
    pronouns = pw.CharField()

    telegramHandle = pw.CharField(null=True)
    blueskyHandle = pw.CharField(null=True)
    fetlifeID = pw.CharField(null=True)

    associatedEvent = pw.ForeignKeyField(Event, backref='organiser')
    designatedContact = pw.BooleanField()

    class Meta:
        database = db
