import { useMemo } from "react"
import { useAppContext } from "../AppContext"
import { ages, ageYears, juvenileRanks, juvenileRanksValues, adultRanks, adultRanksValues,
  femaleWeights, maleWeights, femaleJuvenileWeightValuesKgs, femaleJuvenileWeightValuesLbs,
  femaleAdultWeightValuesKgs, femaleAdultWeightValuesLbs, maleJuvenile1WeightValuesKgs,
  maleJuvenile1WeightValuesLbs, maleAdultWeightValuesKgs, maleAdultWeightValuesLbs,
  femaleNoGiJuvenileWeightValuesKgs, femaleNoGiJuvenileWeightValuesLbs,
  femaleNoGiAdultWeightValuesKgs, femaleNoGiAdultWeightValuesLbs,
  maleNoGiJuvenileWeightValuesKgs, maleNoGiJuvenileWeightValuesLbs,
  maleNoGiAdultWeightValuesKgs, maleNoGiAdultWeightValuesLbs
 } from "../constants"
import classNames from "classnames"
import { t, type translationKeys } from "../translate"
import CustomSelect from "./CustomSelect"

import "./EloFilters.css"

function EloFilters() {
  const {
    language,
    activeTab,
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
      if (activeTab === 'Gi') {
        if (isJuvenileAge(age)) {
          weightValues = language === 'pt' ? femaleJuvenileWeightValuesKgs : femaleJuvenileWeightValuesLbs;
        } else {
          weightValues = language === 'pt' ? femaleAdultWeightValuesKgs : femaleAdultWeightValuesLbs;
        }
      } else {
        if (isJuvenileAge(age)) {
          weightValues = language === 'pt' ? femaleNoGiJuvenileWeightValuesKgs : femaleNoGiJuvenileWeightValuesLbs;
        } else {
          weightValues = language === 'pt' ? femaleNoGiAdultWeightValuesKgs : femaleNoGiAdultWeightValuesLbs;
        }
      }
    } else {
      if (activeTab === 'Gi') {
        if (isJuvenileAge(age)) {
          // For Juvenile, use Juvenile1 values
          weightValues = language === 'pt' ? maleJuvenile1WeightValuesKgs : maleJuvenile1WeightValuesLbs;
        } else {
          weightValues = language === 'pt' ? maleAdultWeightValuesKgs : maleAdultWeightValuesLbs;
        }
      } else {
        if (isJuvenileAge(age)) {
          weightValues = language === 'pt' ? maleNoGiJuvenileWeightValuesKgs : maleNoGiJuvenileWeightValuesLbs;
        } else {
          weightValues = language === 'pt' ? maleNoGiAdultWeightValuesKgs : maleNoGiAdultWeightValuesLbs;
        }
      }
    }

    return weights.map(({ name, value }) => ({
      value: value,
      label: t(name as translationKeys) + (value ? ` (${weightValues[name]})` : ''),
      selectedLabel: t(name as translationKeys),
    }));
  }, [gender, age, language, activeTab]);

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