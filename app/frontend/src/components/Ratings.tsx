import { useState, useContext, useMemo, useEffect, type FormEvent } from 'react';
import GiTabs from './GiTabs';
import EloTable from './EloTable';
import useNewsPosts from '../useNewsPosts';
import { useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';
import Autosuggest from 'react-autosuggest';
import debounce from 'lodash/debounce';
import axios from 'axios';
import { fixNewsTitle, axiosErrorToast, renderAthleteSuggestion, type AthleteSuggestion } from "../utils";
import { AppContext } from '../AppContext';
import { t } from '../translate';

import "./Ratings.css";

type TeamSuggestion = {
  type: 'team';
  name: string;
  slug: string;
};

type RatingsSearchSuggestion =
  | ({ type: 'athlete' } & AthleteSuggestion)
  | TeamSuggestion;

function Ratings() {
  const { posts, loading, error } = useNewsPosts();

  const navigate = useNavigate();
  const [searchValue, setSearchValue] = useState('');
  const [searchSuggestions, setSearchSuggestions] = useState<RatingsSearchSuggestion[]>([]);
  const appContext = useContext(AppContext);
  const activeTab = appContext?.activeTab || 'Gi';

  const handleNewsClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    e.preventDefault();
    const href = e.currentTarget.getAttribute('href');
    
    navigate(href || '/news');
  };

  const debouncedGetSearchSuggestions = useMemo(
    () => debounce(async ({ value }: { value: string }) => {
      if (!value.trim()) {
        setSearchSuggestions([]);
        return;
      }

      try {
        const response = await axios.get(`/api/navbar-search?search=${encodeURIComponent(value)}`);
        setSearchSuggestions(response.data);
      } catch (searchError) {
        axiosErrorToast(searchError);
      }
    }, 300, { trailing: true }),
    []
  );

  useEffect(() => {
    return () => {
      debouncedGetSearchSuggestions.cancel();
    };
  }, [debouncedGetSearchSuggestions]);

  const onSearchSuggestionSelected = async (suggestion: RatingsSearchSuggestion) => {
    if (suggestion.type === 'team') {
      navigate(`/team/${encodeURIComponent(suggestion.slug)}`);
      return;
    }

    const slug = suggestion.slug;
    if (slug) {
      navigate(`/athlete/${encodeURIComponent(slug)}`);
      return;
    }

    try {
      const response = await axios.get('/api/athletes/ratings', {
        params: {
          name: suggestion.name,
          gi: activeTab === 'Gi' ? 'true' : 'false',
        },
      });
      if (response.data?.slug) {
        navigate(`/athlete/${encodeURIComponent(response.data.slug)}`);
      }
    } catch (searchError) {
      axiosErrorToast(searchError);
    }
  };

  const renderSearchSuggestion = (suggestion: RatingsSearchSuggestion) => {
    const label = suggestion.type === 'team'
      ? suggestion.name
      : renderAthleteSuggestion(suggestion);
    const typeLabel = suggestion.type === 'team' ? t('Team') : t('Athlete');

    return (
      <div className="ratings-search-suggestion">
        <span>{label}</span>
        <span className="ratings-search-suggestion-type">{typeLabel}</span>
      </div>
    );
  };

  return (
    <div className="container">
      {!loading && !error && posts.length > 0 &&
        <section className="news-section">
          <span className="news-badge">Latest News:</span>
          <div className="news-posts">
            {posts.slice(0, 3).map((post, index) => (
              <span key={post.ID}>
                {index > 0 && <span className="news-separator">•</span>}
                <a href={`/news/${post.ID}/${post.slug}`} className="news-link" onClick={handleNewsClick}>
                  {
                    index === 0 && dayjs().diff(dayjs(post.date), 'day') <= 3 &&
                    <span className="new-post-marker">New</span>
                  }
                  {fixNewsTitle(post.title)}
                </a>
              </span>
            ))}
          </div>
        </section>
      }
      <section className="ratings-search-section">
        <div className="control has-icons-left">
          <Autosuggest
            suggestions={searchSuggestions}
            onSuggestionsFetchRequested={debouncedGetSearchSuggestions}
            onSuggestionsClearRequested={() => setSearchSuggestions([])}
            multiSection={false}
            getSuggestionValue={(suggestion) => suggestion.name}
            renderSuggestion={renderSearchSuggestion}
            onSuggestionSelected={(_event: FormEvent<HTMLElement>, { suggestion }: { suggestion: RatingsSearchSuggestion }) => {
              setSearchValue('');
              setSearchSuggestions([]);
              void onSearchSuggestionSelected(suggestion);
            }}
            inputProps={{
              className: 'input ratings-search-input',
              value: searchValue,
              placeholder: t('Find Athlete or Team'),
              onChange: (_event: FormEvent<HTMLElement>, { newValue }: { newValue: string }) => setSearchValue(newValue),
            }}
          />
          <span className="icon is-small is-left">
            <i className="fas fa-search" aria-hidden="true"></i>
          </span>
        </div>
      </section>
      <GiTabs />
      <EloTable />
    </div>
  )
}

export default Ratings;
