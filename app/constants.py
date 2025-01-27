BLACK = "BLACK"
BROWN = "BROWN"
PURPLE = "PURPLE"
BLUE = "BLUE"
WHITE = "WHITE"

belt_order = [WHITE, BLUE, PURPLE, BROWN, BLACK]


def translate_belt(belt: str) -> str:
    if belt == "AZUL":
        return BLUE
    if belt == "BRANCA":
        return WHITE
    if belt == "MARROM":
        return BROWN
    if belt == "PRETA":
        return BLACK
    if belt == "ROXA":
        return PURPLE
    if belt not in [BLACK, BROWN, PURPLE, BLUE, WHITE]:
        raise ValueError("Invalid belt " + belt)
    return belt


ROOSTER = "Rooster"
LIGHT_FEATHER = "Light Feather"
FEATHER = "Feather"
LIGHT = "Light"
MIDDLE = "Middle"
MEDIUM_HEAVY = "Medium Heavy"
HEAVY = "Heavy"
SUPER_HEAVY = "Super Heavy"
ULTRA_HEAVY = "Ultra Heavy"
OPEN_CLASS = "Open Class"
OPEN_CLASS_LIGHT = "Open Class Light"
OPEN_CLASS_HEAVY = "Open Class Heavy"


def translate_weight(weight: str) -> str:
    if weight == "Absoluto":
        return OPEN_CLASS
    if weight == "Absoluto Leve":
        return OPEN_CLASS_LIGHT
    if weight == "Absoluto Pesado":
        return OPEN_CLASS_HEAVY
    if weight == "Leve":
        return LIGHT
    if weight == "Médio":
        return MIDDLE
    if weight == "MeioPesado":
        return MEDIUM_HEAVY
    if weight == "Meio-Pesado":
        return MEDIUM_HEAVY
    if weight == "Pena":
        return FEATHER
    if weight == "Pesadíssimo":
        return ULTRA_HEAVY
    if weight == "Pesado":
        return HEAVY
    if weight == "Pluma":
        return LIGHT_FEATHER
    if weight == "Super Pesado":
        return SUPER_HEAVY
    if weight == "Galo":
        return ROOSTER
    if weight == "Super-Heavy":
        return SUPER_HEAVY
    if weight == "Medium-Heavy":
        return MEDIUM_HEAVY
    if weight == "Light-Feather":
        return LIGHT_FEATHER
    if weight == "Ultra-Heavy":
        return ULTRA_HEAVY
    if weight not in [
        ROOSTER,
        LIGHT_FEATHER,
        FEATHER,
        LIGHT,
        MIDDLE,
        MEDIUM_HEAVY,
        HEAVY,
        SUPER_HEAVY,
        ULTRA_HEAVY,
        OPEN_CLASS,
        OPEN_CLASS_LIGHT,
        OPEN_CLASS_HEAVY,
    ]:
        raise ValueError("Invalid weight " + weight)
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
    ULTRA_HEAVY,
]

weight_class_order_all = [
    ROOSTER,
    LIGHT_FEATHER,
    FEATHER,
    LIGHT,
    MIDDLE,
    MEDIUM_HEAVY,
    HEAVY,
    SUPER_HEAVY,
    ULTRA_HEAVY,
    OPEN_CLASS_LIGHT,
    OPEN_CLASS_HEAVY,
    OPEN_CLASS,
]


JUVENILE = "Juvenile"
JUVENILE_1 = "Juvenile 1"
JUVENILE_2 = "Juvenile 2"
ADULT = "Adult"
MASTER_PREFIX = "Master"
MASTER_1 = "Master 1"
MASTER_2 = "Master 2"
MASTER_3 = "Master 3"
MASTER_4 = "Master 4"
MASTER_5 = "Master 5"
MASTER_6 = "Master 6"
MASTER_7 = "Master 7"


age_order = [
    JUVENILE,
    ADULT,
    MASTER_1,
    MASTER_2,
    MASTER_3,
    MASTER_4,
    MASTER_5,
    MASTER_6,
    MASTER_7,
]

age_order_all = [
    JUVENILE_1,
    JUVENILE_2,
    JUVENILE,
    ADULT,
    MASTER_1,
    MASTER_2,
    MASTER_3,
    MASTER_4,
    MASTER_5,
    MASTER_6,
    MASTER_7,
]


def translate_age(age: str) -> str:
    if age == "Juvenil" or age == "Juvenile 1" or age == "Juvenile 2":
        return JUVENILE
    if age == "Adulto":
        return ADULT
    if age not in [
        JUVENILE,
        ADULT,
        MASTER_1,
        MASTER_2,
        MASTER_3,
        MASTER_4,
        MASTER_5,
        MASTER_6,
        MASTER_7,
    ]:
        raise ValueError("Invalid age " + age)
    return age


def translate_age_keep_juvenile(age: str) -> str:
    if age == "Juvenil":
        return JUVENILE
    if age == "Adulto":
        return ADULT
    if age not in [
        JUVENILE,
        JUVENILE_1,
        JUVENILE_2,
        ADULT,
        MASTER_1,
        MASTER_2,
        MASTER_3,
        MASTER_4,
        MASTER_5,
        MASTER_6,
        MASTER_7,
    ]:
        raise ValueError("Invalid age " + age)
    return age


MALE = "Male"
FEMALE = "Female"


def translate_gender(gender: str) -> None:
    if gender == "Masculino":
        return MALE
    if gender == "Feminino":
        return FEMALE
    if gender not in (MALE, FEMALE):
        raise ValueError("Invalid gender " + gender)

    return gender


gender_order = [MALE, FEMALE]
