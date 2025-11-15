BLACK = "BLACK"
BROWN = "BROWN"
PURPLE = "PURPLE"
BLUE = "BLUE"
GREEN = "GREEN"
GREEN_ORANGE = "GREEN-ORANGE"
ORANGE = "ORANGE"
YELLOW = "YELLOW"
YELLOW_GREY = "YELLOW-GREY"
GREY = "GREY"
WHITE = "WHITE"

NON_ELITE_BELTS = {WHITE, GREY, YELLOW_GREY, YELLOW, ORANGE, GREEN_ORANGE, GREEN}

belt_order = [
    WHITE,
    GREY,
    YELLOW_GREY,
    YELLOW,
    ORANGE,
    GREEN_ORANGE,
    GREEN,
    BLUE,
    PURPLE,
    BROWN,
    BLACK,
]


def translate_belt(belt: str) -> str:
    if belt == "CINZA":
        return GREY
    if belt == "AMARELA":
        return YELLOW
    if belt == "AMARELA-CINZA":
        return YELLOW_GREY
    if belt == "LARANJA":
        return ORANGE
    if belt == "VERDE":
        return GREEN
    if belt == "VERDE-LARANJA":
        return GREEN_ORANGE
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
    if belt not in belt_order:
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


TEEN_1 = "Teen 1"
TEEN_2 = "Teen 2"
TEEN_3 = "Teen 3"
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
    TEEN_1,
    TEEN_2,
    TEEN_3,
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

age_order_adult_first = [
    ADULT,
    JUVENILE,
    MASTER_1,
    MASTER_2,
    MASTER_3,
    MASTER_4,
    MASTER_5,
    MASTER_6,
    MASTER_7,
    TEEN_1,
    TEEN_2,
    TEEN_3,
]

age_order_all = [
    TEEN_1,
    TEEN_2,
    TEEN_3,
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

rated_ages = [
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

rated_ages_in = ", ".join(f"'{age}'" for age in rated_ages)


def translate_age(age: str) -> str:
    if age == "Infanto Juvenil 1":
        return TEEN_1
    if age == "Infanto Juvenil 2":
        return TEEN_2
    if age == "Infanto Juvenil 3":
        return TEEN_3
    if age in ("Juvenil", "Juvenile 1", "Juvenile 2", "Juvenil 1", "Juvenil 2"):
        return JUVENILE
    if age == "Adulto":
        return ADULT
    if age not in [
        TEEN_1,
        TEEN_2,
        TEEN_3,
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
    if age == "Infanto Juvenil 1":
        return TEEN_1
    if age == "Infanto Juvenil 2":
        return TEEN_2
    if age == "Infanto Juvenil 3":
        return TEEN_3
    if age == "Juvenil":
        return JUVENILE
    if age == "Juvenil 1":
        return JUVENILE_1
    if age == "Juvenil 2":
        return JUVENILE_2
    if age == "Adulto":
        return ADULT
    if age not in [
        TEEN_1,
        TEEN_2,
        TEEN_3,
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
