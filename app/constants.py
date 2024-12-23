BLACK = 'BLACK'
BROWN = 'BROWN'
PURPLE = 'PURPLE'
BLUE = 'BLUE'
WHITE = 'WHITE'

def translate_belt(belt):
    if belt == 'AZUL':
        return BLUE
    if belt == 'BRANCA':
        return WHITE
    if belt == 'MARROM':
        return BROWN
    if belt == 'PRETA':
        return BLACK
    if belt == 'ROXA':
        return PURPLE
    if belt not in [BLACK, BROWN, PURPLE, BLUE, WHITE]:
        raise ValueError('Invalid belt')
    return belt

ROOSTER = 'Rooster'
LIGHT_FEATHER = 'Light Feather'
FEATHER = 'Feather'
LIGHT = 'Light'
MIDDLE = 'Middle'
MEDIUM_HEAVY = 'Medium Heavy'
HEAVY = 'Heavy'
SUPER_HEAVY = 'Super Heavy'
ULTRA_HEAVY = 'Ultra Heavy'
OPEN_CLASS = 'Open Class'
OPEN_CLASS_LIGHT = 'Open Class Light'
OPEN_CLASS_HEAVY = 'Open Class Heavy'

def translate_weight(weight):
    if weight == 'Absoluto':
        return OPEN_CLASS
    if weight == 'Absoluto Leve':
        return OPEN_CLASS_LIGHT
    if weight == 'Absoluto Pesado':
        return OPEN_CLASS_HEAVY
    if weight == 'Leve':
        return LIGHT
    if weight == 'Médio':
        return MIDDLE
    if weight == 'MeioPesado':
        return MEDIUM_HEAVY
    if weight == 'Pena':
        return FEATHER
    if weight == 'Pesadíssimo':
        return ULTRA_HEAVY
    if weight == 'Pesado':
        return HEAVY
    if weight == 'Pluma':
        return LIGHT_FEATHER
    if weight == 'Super Pesado':
        return SUPER_HEAVY
    if weight == 'Galo':
        return ROOSTER
    if weight not in [ROOSTER, LIGHT_FEATHER, FEATHER, LIGHT, MIDDLE,
                      MEDIUM_HEAVY, HEAVY, SUPER_HEAVY, ULTRA_HEAVY,
                      OPEN_CLASS, OPEN_CLASS_LIGHT, OPEN_CLASS_HEAVY]:
        raise ValueError('Invalid weight')
    return weight

weight_class_order = [
    ROOSTER,
    LIGHT_FEATHER,
    FEATHER,
    LIGHT,
    MIDDLE,
    MEDIUM_HEAVY,
    HEAVY,
    SUPER_HEAVY,
    ULTRA_HEAVY
]

JUVENILE_1 = 'Juvenile 1'
JUVENILE_2 = 'Juvenile 2'
JUVENILE_PREFIX = 'Juvenile'
ADULT = 'Adult'
MASTER_PREFIX = 'Master'
MASTER_1 = 'Master 1'
MASTER_2 = 'Master 2'
MASTER_3 = 'Master 3'
MASTER_4 = 'Master 4'
MASTER_5 = 'Master 5'
MASTER_6 = 'Master 6'
MASTER_7 = 'Master 7'

def translate_age(age):
    if age == JUVENILE_PREFIX or age == 'Juvenil':
        return JUVENILE_2
    if age == 'Adulto':
        return ADULT
    if age not in [JUVENILE_1, JUVENILE_2, ADULT, MASTER_1, MASTER_2, MASTER_3, MASTER_4, MASTER_5, MASTER_6, MASTER_7]:
        raise ValueError('Invalid age')

MALE = 'Male'
FEMALE = 'Female'

def check_gender(gender):
    if gender not in (MALE, FEMALE):
        raise ValueError('Invalid gender')