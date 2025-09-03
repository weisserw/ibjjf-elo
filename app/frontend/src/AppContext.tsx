import { createContext, useState, useContext, useCallback, ReactNode } from 'react';
import type { FilterValues, OpenFilters } from './components/DBFilters';
import type { TabName } from './components/GiTabs';
import type {
  Tabs as BracketTabs,
} from './components/Brackets';
import type {
  Event as BracketEvent,
} from './components/BracketLive';
import type {
  SortColumn as BracketSortColumn,
} from './components/BracketTable';
import type {
  Competitor as BracketCompetitor,
  Match as BracketMatch,
  Category as BracketCategory,
} from './components/BracketUtils';
import type {
  UpcomingLink as BracketRegistrationUpcomingLink,
} from './components/BracketRegistration';

interface AppContextProps {
  filters: FilterValues;
  setFilters: (filters: FilterValues) => void;
  openFilters: OpenFilters;
  setOpenFilters: (openFilters: OpenFilters) => void;
  activeTab: TabName;
  setActiveTab: (tab: TabName) => void;
  rankingGender: string;
  setRankingGender: (gender: string) => void;
  rankingAge: string;
  setRankingAge: (age: string) => void;
  rankingBelt: string;
  setRankingBelt: (belt: string) => void;
  rankingWeight: string;
  setRankingWeight: (weight: string) => void;
  rankingChanged: boolean;
  setRankingChanged: (changed: boolean) => void;
  rankingUpcoming: boolean;
  setRankingUpcoming: (upcoming: boolean) => void;
  rankingNameFilter: string;
  setRankingNameFilter: (nameFilter: string) => void;
  rankingPage: number;
  setRankingPage: (page: number) => void;
  dbPage: number;
  setDbPage: (page: number) => void;
  bracketEvents: BracketEvent[] | null;
  setBracketEvents: (events: BracketEvent[] | null) => void;
  bracketSelectedEvent: string | null;
  setBracketSelectedEvent: (event: string | null) => void;
  bracketCategories: BracketCategory[] | null;
  setBracketCategories: (categories: BracketCategory[] | null) => void;
  bracketSelectedCategory: string | null;
  setBracketSelectedCategory: (category: string | null) => void;
  bracketCompetitors: BracketCompetitor[] | null;
  setBracketCompetitors: (competitors: BracketCompetitor[] | null) => void;
  bracketMatches: BracketMatch[] | null;
  setBracketMatches: (matches: BracketMatch[] | null) => void;
  bracketSortColumn: BracketSortColumn;
  setBracketSortColumn: (column: BracketSortColumn) => void;
  bracketActiveTab: BracketTabs;
  setBracketActiveTab: (tab: BracketTabs) => void;
  bracketRegistrationEventName: string;
  setBracketRegistrationEventName: (name: string) => void;
  bracketRegistrationEventTotal: number | null;
  setBracketRegistrationEventTotal: (total: number | null) => void;
  bracketRegistrationEventUrl: string;
  setBracketRegistrationEventUrl: (url: string) => void;
  bracketRegistrationCategories: string[] | null;
  setBracketRegistrationCategories: (categories: string[] | null) => void;
  bracketRegistrationSelectedCategory: string | null;
  setBracketRegistrationSelectedCategory: (category: string | null) => void;
  bracketRegistrationCompetitors: BracketCompetitor[] | null;
  setBracketRegistrationCompetitors: (competitors: BracketCompetitor[] | null) => void;
  bracketRegistrationUpcomingLinks: BracketRegistrationUpcomingLink[];
  setBracketRegistrationUpcomingLinks: (links: BracketRegistrationUpcomingLink[]) => void;
  bracketRegistrationSelectedUpcomingLink: string;
  setBracketRegistrationSelectedUpcomingLink: (link: string) => void;
  bracketArchiveEventName: string;
  setBracketArchiveEventName: (name: string) => void;
  bracketArchiveEventNameFetch: string;
  setBracketArchiveEventNameFetch: (name: string) => void;
  bracketArchiveCategories: BracketCategory[] | null;
  setBracketArchiveCategories: (categories: BracketCategory[] | null) => void;
  bracketArchiveSelectedCategory: string | null;
  setBracketArchiveSelectedCategory: (category: string | null) => void;
  bracketArchiveCompetitors: BracketCompetitor[] | null;
  setBracketArchiveCompetitors: (competitors: BracketCompetitor[] | null) => void;
  bracketArchiveMatches: BracketMatch[] | null;
  setBracketArchiveMatches: (matches: BracketMatch[] | null) => void;
  calcGender: string;
  setCalcGender: (gender: string) => void;
  calcFirstAthlete: string;
  setCalcFirstAthlete: (athlete: string) => void;
  calcSecondAthlete: string;
  setCalcSecondAthlete: (athlete: string) => void;
  calcAge: string;
  setCalcAge: (age: string) => void;
  calcBelt: string;
  setCalcBelt: (belt: string) => void;
  calcFirstWeight: string;
  setCalcFirstWeight: (weight: string) => void;
  calcSecondWeight: string;
  setCalcSecondWeight: (weight: string) => void;
  calcCustomInfo: boolean;
  setCalcCustomInfo: (info: boolean) => void;
  language: 'en' | 'pt';
  setLanguage: (lang: 'en' | 'pt') => void;
}

export const AppContext = createContext<AppContextProps | undefined>(undefined);

export const useAppContext = () => {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useAppContext must be used within an AppProvider');
  }
  return context;
};

export const AppProvider = ({ children }: { children: ReactNode }) => {
  const [filters, setFilters] = useState<FilterValues>({});
  const [openFilters, setOpenFilters] = useState<OpenFilters>({ athlete: true, event: false, division: false });
  const [activeTab, setActiveTab] = useState<TabName>('Gi');
  const [rankingGender, setRankingGender] = useState('Male');
  const [rankingAge, setRankingAge] = useState('Adult');
  const [rankingBelt, setRankingBelt] = useState('BLACK');
  const [rankingWeight, setRankingWeight] = useState('');
  const [rankingChanged, setRankingChanged] = useState(false);
  const [rankingUpcoming, setRankingUpcoming] = useState(false);
  const [rankingNameFilter, setRankingNameFilter] = useState('');
  const [rankingPage, setRankingPage] = useState(1);
  const [dbPage, setDbPage] = useState(1);
  const [bracketEvents, setBracketEvents] = useState<BracketEvent[] | null>(null)
  const [bracketSelectedEvent, setBracketSelectedEvent] = useState<string | null>(null)
  const [bracketCategories, setBracketCategories] = useState<BracketCategory[] | null>(null)
  const [bracketSelectedCategory, setBracketSelectedCategory] = useState<string | null>(null)
  const [bracketCompetitors, setBracketCompetitors] = useState<BracketCompetitor[] | null>(null)
  const [bracketMatches, setBracketMatches] = useState<BracketMatch[] | null>(null)
  const [bracketSortColumn, setBracketSortColumn] = useState<BracketSortColumn>('rating')
  const [bracketActiveTab, setBracketActiveTab] = useState<BracketTabs>('Live')
  const [bracketRegistrationEventName, setBracketRegistrationEventName] = useState('')
  const [bracketRegistrationEventTotal, setBracketRegistrationEventTotal] = useState<number | null>(null)
  const [bracketRegistrationEventUrl, setBracketRegistrationEventUrl] = useState('')
  const [bracketRegistrationCategories, setBracketRegistrationCategories] = useState<string[] | null>(null)
  const [bracketRegistrationSelectedCategory, setBracketRegistrationSelectedCategory] = useState<string | null>(null)
  const [bracketRegistrationCompetitors, setBracketRegistrationCompetitors] = useState<BracketCompetitor[] | null>(null)
  const [bracketRegistrationUpcomingLinks, setBracketRegistrationUpcomingLinks] = useState<BracketRegistrationUpcomingLink[]>([])
  const [bracketRegistrationSelectedUpcomingLink, setBracketRegistrationSelectedUpcomingLink] = useState<string>('')
  const [bracketArchiveEventName, setBracketArchiveEventName] = useState('')
  const [bracketArchiveEventNameFetch, setBracketArchiveEventNameFetch] = useState('')
  const [bracketArchiveCategories, setBracketArchiveCategories] = useState<BracketCategory[] | null>(null)
  const [bracketArchiveSelectedCategory, setBracketArchiveSelectedCategory] = useState<string | null>(null)
  const [bracketArchiveCompetitors, setBracketArchiveCompetitors] = useState<BracketCompetitor[] | null>(null)
  const [bracketArchiveMatches, setBracketArchiveMatches] = useState<BracketMatch[] | null>(null)
  const [calcGender, setCalcGender] = useState('Male')
  const [calcFirstAthlete, setCalcFirstAthlete] = useState('')
  const [calcSecondAthlete, setCalcSecondAthlete] = useState('')
  const [calcAge, setCalcAge] = useState('Adult')
  const [calcBelt, setCalcBelt] = useState('BLACK')
  const [calcFirstWeight, setCalcFirstWeight] = useState('Heavy')
  const [calcSecondWeight, setCalcSecondWeight] = useState('Heavy')
  const [calcCustomInfo, setCalcCustomInfo] = useState(false)
  // Read initial language from localStorage, fallback to 'en'
  const getInitialLanguage = () => {
    try {
      const stored = localStorage.getItem('language');
      if (stored === 'pt' || stored === 'en') {
        return stored as 'en' | 'pt';
      }
    } catch (e) {}
    return 'en';
  };
  const [language, setLanguageState] = useState<'en' | 'pt'>(getInitialLanguage());

  // Save language to localStorage and update state
  const setLanguage = (lang: 'en' | 'pt') => {
    setLanguageState(lang);
    try {
      localStorage.setItem('language', lang);
    } catch (e) {}
  };

  const updateFilters = useCallback((newFilters: FilterValues) => {
    // Reset the page when filters change
    setDbPage(1);
    setFilters(newFilters);
  }, []);

  const updateRankingGender = useCallback((gender: string) => {
    setRankingPage(1);
    setRankingGender(gender);
  }, []);

  const updateRankingAge = useCallback((age: string) => {
    setRankingPage(1);
    setRankingAge(age);
  }, []);

  const updateRankingBelt = useCallback((belt: string) => {
    setRankingPage(1);
    setRankingBelt(belt);
  }, []);

  const updateRankingWeight = useCallback((weight: string) => {
    setRankingPage(1);
    setRankingWeight(weight);
  }, []);

  const updateRankingChanged = useCallback((changed: boolean) => {
    setRankingPage(1);
    setRankingChanged(changed);
  }, []);

  const updateRankingUpcoming = useCallback((upcoming: boolean) => {
    setRankingPage(1);
    setRankingUpcoming(upcoming);
  }, []);

  const updateRankingNameFilter = useCallback((nameFilter: string) => {
    setRankingPage(1);
    setRankingNameFilter(nameFilter);
  }, []);

  const updateActiveTab = useCallback((tab: TabName) => {
    setRankingPage(1);
    setDbPage(1);
    setActiveTab(tab);
  }, []);

  return (
    <AppContext.Provider value={{
      filters, setFilters: updateFilters,
      openFilters, setOpenFilters,
      activeTab, setActiveTab: updateActiveTab,
      rankingGender, setRankingGender: updateRankingGender,
      rankingAge, setRankingAge: updateRankingAge,
      rankingBelt, setRankingBelt: updateRankingBelt,
      rankingWeight, setRankingWeight: updateRankingWeight,
      rankingChanged, setRankingChanged: updateRankingChanged,
      rankingUpcoming, setRankingUpcoming: updateRankingUpcoming,
      rankingNameFilter, setRankingNameFilter: updateRankingNameFilter,
      rankingPage, setRankingPage,
      dbPage, setDbPage,
      bracketEvents, setBracketEvents,
      bracketSelectedEvent, setBracketSelectedEvent,
      bracketCategories, setBracketCategories,
      bracketSelectedCategory, setBracketSelectedCategory,
      bracketCompetitors, setBracketCompetitors,
      bracketMatches, setBracketMatches,
      bracketSortColumn, setBracketSortColumn,
      bracketActiveTab, setBracketActiveTab,
      bracketRegistrationEventName, setBracketRegistrationEventName,
      bracketRegistrationEventTotal, setBracketRegistrationEventTotal,
      bracketRegistrationEventUrl, setBracketRegistrationEventUrl,
      bracketRegistrationCategories, setBracketRegistrationCategories,
      bracketRegistrationSelectedCategory, setBracketRegistrationSelectedCategory,
      bracketRegistrationCompetitors, setBracketRegistrationCompetitors,
      bracketRegistrationUpcomingLinks, setBracketRegistrationUpcomingLinks,
      bracketRegistrationSelectedUpcomingLink, setBracketRegistrationSelectedUpcomingLink,
      bracketArchiveEventName, setBracketArchiveEventName,
      bracketArchiveEventNameFetch, setBracketArchiveEventNameFetch,
      bracketArchiveCategories, setBracketArchiveCategories,
      bracketArchiveSelectedCategory, setBracketArchiveSelectedCategory,
      bracketArchiveCompetitors, setBracketArchiveCompetitors,
      bracketArchiveMatches, setBracketArchiveMatches,
      calcGender, setCalcGender,
      calcFirstAthlete, setCalcFirstAthlete,
      calcSecondAthlete, setCalcSecondAthlete,
      calcAge, setCalcAge,
      calcBelt, setCalcBelt,
      calcFirstWeight, setCalcFirstWeight,
      calcSecondWeight, setCalcSecondWeight,
      calcCustomInfo, setCalcCustomInfo,
      language, setLanguage,
    }}>
      {children}
    </AppContext.Provider>
  );
};
