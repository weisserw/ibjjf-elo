import { useEffect, useState } from 'react';
import igLogo from '/src/assets/instagram.png';
import igLogoColor from '/src/assets/instagram-color.png';
import { getCountryName } from '../utils';
import { useAppContext } from '../AppContext';
import { Tooltip } from 'react-tooltip';
import "/node_modules/flag-icons/css/flag-icons.min.css";

import "./NameInfo.css";

interface NameInfoProps {
  instagram_profile: string | null;
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

function NameInfo({ instagram_profile, profile_image_url, country, country_note, country_note_pt, medal, tree }: NameInfoProps) {
  const [uniqueId] = useState(() => Math.random().toString(36).substring(2, 9));

  // manage hover state for instagram tooltip because of react-tooltip bug that doesn't close it sometimes
  const [linkHover, setLinkHover] = useState(false);
  const [tooltipHover, setTooltipHover] = useState(false);

  const {
    language,
  } = useAppContext();

  useEffect(() => {
    // clicking anywhere other than the tooltip should close it
    const handleClickOutside = (event: MouseEvent) => {
      if (!tooltipHover && !linkHover) return;

      const target = event.target as HTMLElement
      if (!target.isConnected) {
        return
      }

      const span = document.querySelector<HTMLElement>(`[id='${uniqueId}-ig-span']`);
      const tooltip = document.querySelector<HTMLElement>(`[id='${uniqueId}-ig']`);
      const anchors = [span, tooltip]
      if (anchors.some((anchor) => anchor?.contains(target))) {
        return
      }

      setTooltipHover(false);
      setLinkHover(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);
  
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
        instagram_profile && profile_image_url && (tooltipHover || linkHover) &&
          <Tooltip id={`${uniqueId}-ig`} className="tooltip-ig" clickable place="top" isOpen={true}>
            <div className="ig-tooltip-content" onMouseEnter={() => setTooltipHover(true)} onMouseLeave={() => setTooltipHover(false)}>
              <a href={`https://www.instagram.com/${instagram_profile}`} target="_blank" rel="noopener noreferrer" className="ig-tooltip-username">
                <img src={profile_image_url ?? ''} alt={`@${instagram_profile}`} className="ig-tooltip-photo" />
                <div className="ig-tooltip-name">
                  <img src={igLogoColor} alt="Instagram" className="ig-tooltip-instagram-logo" /> {instagram_profile}
                </div>
              </a>
            </div>
          </Tooltip>
      }
      {
        instagram_profile && profile_image_url &&
        <span id={`${uniqueId}-ig-span`} className={tree ? "instagram-profile-tree" : "instagram-profile"} data-tooltip-id={`${uniqueId}-ig`}
              onMouseEnter={() => setLinkHover(true)} onMouseDown={() => setLinkHover(true)} onMouseLeave={() => setTimeout(() => setLinkHover(false), 200)}>
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