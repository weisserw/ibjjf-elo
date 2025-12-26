import { useMemo } from "react"
import { useAppContext } from "../AppContext"
import { ages, ageYears } from "../utils"
import classNames from "classnames"
import { t, type translationKeys } from "../translate"
import CustomSelect from "./CustomSelect"

import "./EloFilters.css"

const juvenileRanks = [
  'White',
  'Blue',
  'Purple',
]

const juvenileRanksValues = juvenileRanks.map(rank => rank.toUpperCase())

const adultRanks = [
  'White',
  'Blue',
  'Purple',
  'Brown',
  'Black',
]

const adultRanksValues = adultRanks.map(rank => rank.toUpperCase())

const femaleWeights = [{
  name: 'P4P',
  value: ''
}, {
  name: 'Rooster',
  value: 'Rooster'
}, {
  name: 'Light Feather',
  value: 'Light Feather'
}, {
  name: 'Feather',
  value: 'Feather'
}, {
  name: 'Light',
  value: 'Light'
}, {
  name: 'Middle',
  value: 'Middle'
}, {
  name: 'Medium Heavy',
  value: 'Medium Heavy'
}, {
  name: 'Heavy',
  value: 'Heavy'
}, {
  name: 'Super Heavy',
  value: 'Super Heavy'
}];

const maleWeights = femaleWeights.concat([{
  name: 'Ultra Heavy',
  value: 'Ultra Heavy'
}]);

const femaleJuvenileWeightValuesLbs = {
  'Rooster': "98.0 lbs",
  'Light Feather': "106.6 lbs",
  'Feather': "116.0 lbs",
  'Light': "125.0 lbs",
  'Middle': "133.6 lbs",
  'Medium Heavy': "143.6 lbs",
  'Heavy': "152.0 lbs",
  'Super Heavy': "No Limit",
}

const femaleJuvenileWeightValuesKgs = {
  "Rooster": "44,30 kg",
  "Light Feather": "48,30 kg",
  "Feather": "52,50 kg",
  "Light": "56,50 kg",
  "Middle": "60,50 kg",
  "Medium Heavy": "65,00 kg",
  "Heavy": "69,00 kg",
  "Super Heavy": "No Limit",
}

const femaleAdultWeightValuesLbs = {
  "Rooster": "107.0 lbs",
  "Light Feather": "118.0 lbs",
  "Feather": "129.0 lbs",
  "Light": "141.6 lbs",
  "Middle": "152.6 lbs",
  "Medium Heavy": "163.6 lbs",
  "Heavy": "175.0 lbs",
  "Super Heavy": "No Limit",
}

const femaleAdultWeightValuesKgs = {
  "Rooster": "48,50 kg",
  "Light Feather": "53,50 kg",
  "Feather": "58,50 kg",
  "Light": "64,00 kg",
  "Middle": "69,00 kg",
  "Medium Heavy": "74,00 kg",
  "Heavy": "79,30 kg",
  "Super Heavy": "No Limit",
}

const maleJuvenile1WeightValuesLbs = {
  "Rooster": "107.0 lbs",
  "Light Feather": "118.0 lbs",
  "Feather": "129.0 lbs",
  "Light": "141.0 lbs",
  "Middle": "152.0 lbs",
  "Medium Heavy": "163.0 lbs",
  "Heavy": "175.0 lbs",
  "Super Heavy": "186.0 lbs",
  "Ultra Heavy": "No Limit",
}

const maleJuvenile1WeightValuesKgs = {
  "Rooster": "48,50 kg",
  "Light Feather": "53,50 kg",
  "Feather": "58,50 kg",
  "Light": "64,00 kg",
  "Middle": "69,00 kg",
  "Medium Heavy": "74,00 kg",
  "Heavy": "79,30 kg",
  "Super Heavy": "84,30 kg",
  "Ultra Heavy": "No Limit",
}

/*
const maleJuvenile2WeightValuesLbs = {
  "Rooster": "118.0 lbs",
  "Light Feather": "129.0 lbs",
  "Feather": "141.6 lbs",
  "Light": "152.6 lbs",
  "Middle": "163.6 lbs",
  "Medium Heavy": "175.0 lbs",
  "Heavy": "186.0 lbs",
  "Super Heavy": "197.0 lbs",
  "Ultra Heavy": "No Limit",
}

const maleJuvenile2WeightValuesKgs = {
  "Rooster": "53,50 kg",
  "Light Feather": "58,50 kg",
  "Feather": "64,00 kg",
  "Light": "69,00 kg",
  "Middle": "74,00 kg",
  "Medium Heavy": "79,30 kg",
  "Heavy": "84,30 kg",
  "Super Heavy": "89,30 kg",
  "Ultra Heavy": "No Limit",
}*/

const maleAdultWeightValuesLbs = {
  "Rooster": "127.0 lbs",
  "Light Feather": "141.6 lbs",
  "Feather": "154.6 lbs",
  "Light": "168.0 lbs",
  "Middle": "181.6 lbs",
  "Medium Heavy": "195.0 lbs",
  "Heavy": "208.0 lbs",
  "Super Heavy": "222.0 lbs",
  "Ultra Heavy": "No Limit",
}

const maleAdultWeightValuesKgs = {
  "Rooster": "57,50 kg",
  "Light Feather": "64,00 kg",
  "Feather": "70,00 kg",
  "Light": "76,00 kg",
  "Middle": "82,30 kg",
  "Medium Heavy": "88,30 kg",
  "Heavy": "94,30 kg",
  "Super Heavy": "100,50 kg",
  "Ultra Heavy": "No Limit",
}

function EloFilters() {
  const {
    language,
    rankingGender: gender,
    rankingAge: age,
    rankingBelt: belt,
    rankingWeight: weight,
    rankingChanged: changed,
    rankingUpcoming: upcoming,
    setRankingGender: setGender,
    setRankingAge: setAge,
    setRankingBelt: setBelt,
    setRankingWeight: setWeight,
    setRankingChanged: setChanged,
    setRankingUpcoming: setUpcoming,
  } = useAppContext();

  const isJuvenileAge = (age: string) => {
    return age === 'Juvenile'
  }

  const isAdultAge = (age: string) => {
    return !isJuvenileAge(age)
  }

  const onGenderChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    setGender(event.target.value)

    if (event.target.value === 'Female' && weight === 'Ultra Heavy') {
      setWeight('')
    }
  }

  const defaultBelt = (age: string) => {
    if (isAdultAge(age)) {
      return 'BLACK';
    } else {
      return 'BLUE';
    }
  }

  const onAgeChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    setAge(event.target.value)

    if ((isJuvenileAge(event.target.value) && juvenileRanksValues.indexOf(belt) !== -1)
      || (isAdultAge(event.target.value) && adultRanksValues.indexOf(belt) === -1)) {
        setBelt(defaultBelt(event.target.value))
    }
  }

  const onBeltChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    setBelt(event.target.value)
  }

  const onWeightChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    setWeight(event.target.value)
  }

  const ranks = isJuvenileAge(age) ? juvenileRanks : adultRanks;

  const weights = gender === 'Male' ? maleWeights : femaleWeights;

  const ageOptions = useMemo(() => {
    return ages.map(age => ({
      value: age,
      label: t(age as translationKeys) + ' (' + ageYears[ages.indexOf(age)] + ')',
      selectedLabel: t(age as translationKeys),
    }))
  }, [language]);

  const weightOptions = useMemo(() => {
    let weightValues: { [key: string]: string } = {};

    if (gender === 'Female') {
      if (isJuvenileAge(age)) {
        weightValues = language === 'pt' ? femaleJuvenileWeightValuesKgs : femaleJuvenileWeightValuesLbs;
      } else {
        weightValues = language === 'pt' ? femaleAdultWeightValuesKgs : femaleAdultWeightValuesLbs;
      }
    } else {
      if (isJuvenileAge(age)) {
        // For Juvenile, use Juvenile1 values
        weightValues = language === 'pt' ? maleJuvenile1WeightValuesKgs : maleJuvenile1WeightValuesLbs;
      } else {
        weightValues = language === 'pt' ? maleAdultWeightValuesKgs : maleAdultWeightValuesLbs;
      }
    }

    return weights.map(({ name, value }) => ({
      value: value,
      label: t(name as translationKeys) + (value ? ` (${weightValues[name]})` : ''),
      selectedLabel: t(name as translationKeys),
    }));
  }, [gender, age, language]);

  return (
    <div className="columns is-mobile is-multiline">
      <div className="column is-third-mobile">
        <div className="field mobile-margin">
          <label className="label">{t("Gender")}</label>
          <div className="select">
            <select value={gender} onChange={onGenderChange}>
              <option value="Male">{t("Male")}</option>
              <option value="Female">{t("Female")}</option>
            </select>
          </div>
        </div>
      </div>
      <div className="column is-third-mobile">
        <div className="field">
          <label className="label">{t("Age")}</label>
          <CustomSelect className="select"
            value={age}
            onChange={onAgeChange}
            width="115px"
            options={ageOptions} />
        </div>
      </div>
      <div className="column is-third-mobile">
        <div className={classNames("field", {"small-mobile-margin": language === 'pt'})}>
          <label className="label">{t("Belt")}</label>
          <div className="select">
            <select value={belt} onChange={onBeltChange}>
              {
                ranks.map(rank => (
                  <option key={rank} value={rank.toUpperCase()}>{t(rank as translationKeys)}</option>
                ))
              }
            </select>
          </div>
        </div>
      </div>
      <div className="column is-half-mobile">
        <div className="field mobile-margin">
          <label className="label">{t("Weight")}</label>
          <CustomSelect className="select"
            value={weight}
            onChange={onWeightChange}
            width="165px"
            options={weightOptions} />
        </div>
      </div>
      <div className="column is-half-mobile">
        <div className={classNames("field", "checkbox-margin", {"small-mobile-margin": language === 'pt'})}>
          <div className="control">
            <label className="checkbox">
              <input type="checkbox" checked={upcoming} onChange={() => setUpcoming(!upcoming)} />
              &nbsp;{t("Upcoming")}
            </label>
          </div>
          <div className="control mt-3">
            <label className="checkbox">
              <input type="checkbox" checked={changed} onChange={() => setChanged(!changed)} />
              &nbsp;{t("Changed")}
            </label>
          </div>
        </div>
      </div>
    </div>
  );
}

export default EloFilters;