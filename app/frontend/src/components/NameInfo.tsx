import { useState, useRef } from 'react';
import igLogo from '/src/assets/instagram.png';
import igLogoColor from '/src/assets/instagram-color.png';
import { getCountryName } from '../utils';
import { useAppContext } from '../AppContext';
import { Tooltip, type TooltipRefProps } from 'react-tooltip';
import "/node_modules/flag-icons/css/flag-icons.min.css";

import "./NameInfo.css";

interface NameInfoProps {
  instagram_profile: string | null;
  instagram_profile_personal_name: string | null;
  profile_image_url: string | null;
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

function NameInfo({ instagram_profile, instagram_profile_personal_name, profile_image_url, country, country_note, country_note_pt, medal, tree }: NameInfoProps) {
  const [uniqueId] = useState(() => Math.random().toString(36).substring(2, 9));
  const igTooltipRef = useRef<TooltipRefProps>(null);

  const {
    language,
  } = useAppContext();
  
  if (!instagram_profile && !country && !medal) {
    return null;
  }
  return (
    <div className="name-subinfo">
      <Tooltip id={uniqueId} className="tooltip-normal" />
      {country && (
        <span className={`fi fi-${country.trim().toLowerCase().substring(0, 2)} country-flag`} data-tooltip-place="top" data-tooltip-id={uniqueId} data-tooltip-content={getCountryName(country, country_note, country_note_pt, language)} />
      )}
      {
        instagram_profile && profile_image_url &&
          <Tooltip id={`${uniqueId}-ig`} className="tooltip-ig" clickable place="top" ref={igTooltipRef}>
            <div className="ig-tooltip-content" onMouseLeave={
              () => {
                igTooltipRef.current?.close();
              }
            }>
              <a href={`https://www.instagram.com/${instagram_profile}`} target="_blank" rel="noopener noreferrer" className="ig-tooltip-username">
                <img src={profile_image_url ?? ''} alt={`@${instagram_profile}`} className="ig-tooltip-photo" />
                <div className="ig-tooltip-name">
                  {instagram_profile_personal_name ?? `@${instagram_profile}`} <img src={igLogoColor} alt="Instagram" className="ig-tooltip-instagram-logo" />
                </div>
              </a>
            </div>
          </Tooltip>
      }
      {
        instagram_profile && profile_image_url &&
        <span className={tree ? "instagram-profile-tree" : "instagram-profile"} data-tooltip-id={`${uniqueId}-ig`}>
          <img src={igLogo} alt="Instagram" title={`@${instagram_profile}`} />
        </span>
      }
      {instagram_profile && !profile_image_url && (
        <a className={tree ? "instagram-profile-tree" : "instagram-profile"} href={`https://www.instagram.com/${instagram_profile}`} target="_blank" rel="noopener noreferrer">
          <img src={igLogo} alt="Instagram" title={`@${instagram_profile}`} />
        </a>
      )}
      {medal && competitorMedal(medal)}
    </div>
  );
}

export default NameInfo;