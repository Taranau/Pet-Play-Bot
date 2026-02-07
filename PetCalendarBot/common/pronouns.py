# This file defines many common pronoun combinations as constants. 
# Pronouns can be combined as a list, and custom pronouns can be entered, 
# so we only implement the common combinations.

# Single pronouns
SHE = 'She'
HE = 'He'
THEY = 'They'
IT = 'It'
XE = 'Xe'
ZE = 'Ze'
SIE = 'Sie'
FAE = 'Fae'
ALL_PRONOUNS = 'Any'

def PronounFactory(pronounList: list[str]) -> str:
    if len(pronounList) == 1:
        pronoun = pronounList[0]
        match pronoun.capitalize():
            case 'He':
                return "He/Him"
            case 'She':
                return "She/Her"
            case 'They':
                return "They/Them"
            case 'It':
                return "It/Its"
            case 'Fae':
                return "Fae/Faer"
            case 'Xe':
                return "Xe/Xem"
            case 'Ze':
                return "Ze/Zim"
            case 'Sie':
                return "Sie/Hir"
            case 'Any':
                return "Any/All"
            case _:
                return 'Pronoun error' 
    pronouns: str = pronounList[0]
    for pronoun in pronounList:
        pronouns += f'/{pronoun.capitalize()}'
    return pronouns