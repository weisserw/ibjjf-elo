import { useState } from 'react';
import igLogo from '/src/assets/instagram.png';
import { getCountryName } from '../utils';
import { useAppContext } from '../AppContext';
import { Tooltip } from 'react-tooltip';
import classNames from 'classnames';
import "/node_modules/flag-icons/css/flag-icons.min.css";

import "./NameInfo.css";

interface NameInfoProps {
  instagram_profile: string | null;
  country: string | null;
  country_note: string | null;
  country_note_pt: string | null;
  medal?: string | null;
  tree?: boolean;
}

const competitorMedal = (medal: string | null | undefined) => {
  if (medal === undefined) {
    return null;
  }
  if (medal === '1') {
    return <span title="First place"> 🥇</span>;
  } else if (medal === '2') {
    return <span title="Second place"> 🥈</span>;
  } else if (medal === '3') {
    return <span title="Third place"> 🥉</span>;
  } else {
    return null;
  }
}

function NameInfo({ instagram_profile, country, country_note, country_note_pt, medal, tree }: NameInfoProps) {
  const [uniqueId] = useState(() => Math.random().toString(36).substring(2, 9));

  const {
    language,
  } = useAppContext();
  
  if (!instagram_profile && !country) {
    return null;
  }
  return (
    <div className="name-subinfo">
      <Tooltip id={uniqueId} className="tooltip-normal" />
      {country && (
        <span className={classNames(`fi fi-${country.trim().toLowerCase().substring(0, 2)} country-flag`, {'country-flag-border': country === 'jp'})} data-tooltip-place="top" data-tooltip-id={uniqueId} data-tooltip-content={getCountryName(country, country_note, country_note_pt, language)} />
      )}
      {instagram_profile && (
        <a className={tree ? "instagram-profile-tree" : "instagram-profile"} href={`https://www.instagram.com/${instagram_profile}`} target="_blank" rel="noopener noreferrer">
          <img src={igLogo} alt="Instagram" title={`@${instagram_profile}`} />
        </a>
      )}
      {medal && competitorMedal(medal)}
    </div>
  );
}

export default NameInfo;