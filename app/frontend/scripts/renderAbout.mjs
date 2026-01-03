#!/usr/bin/env node
import fs from "fs";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";
import { build } from "esbuild";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const projectRoot = path.resolve(__dirname, "..");
const tmpDir = path.resolve(projectRoot, ".tmp");
const bundleFile = path.resolve(tmpDir, "about.bundle.mjs");
const outputDir = path.resolve(projectRoot, "..", "seo_snippets");
const outputFile = path.resolve(outputDir, "about.html");

async function bundleComponent() {
  await fs.promises.mkdir(tmpDir, { recursive: true });
  await build({
    entryPoints: [path.resolve(projectRoot, "src/components/About.tsx")],
    outfile: bundleFile,
    bundle: true,
    platform: "node",
    format: "esm",
    jsx: "automatic",
    sourcemap: false,
    logLevel: "silent",
    external: [
      "react",
      "react-dom",
      "@uidotdev/usehooks",
      "react-router-dom",
    ],
    plugins: [
      {
        name: "alias-appcontext",
        setup(build) {
          const target = path.resolve(projectRoot, "scripts/seoAppContext.js");
          build.onResolve({ filter: /^\.\.\/AppContext(\.tsx)?$/ }, () => ({
            path: target,
          }));
        },
      },
    ],
    define: { "process.env.NODE_ENV": '"production"' },
  });
}

function buildMockContext() {
  const noop = () => {};
  return {
    filters: {},
    setFilters: noop,
    openFilters: { athlete: true, event: false, division: false },
    setOpenFilters: noop,
    activeTab: "Gi",
    setActiveTab: noop,
    rankingGender: "Male",
    setRankingGender: noop,
    rankingAge: "Adult",
    setRankingAge: noop,
    rankingBelt: "BLACK",
    setRankingBelt: noop,
    rankingWeight: "",
    setRankingWeight: noop,
    rankingChanged: false,
    setRankingChanged: noop,
    rankingUpcoming: false,
    setRankingUpcoming: noop,
    rankingNameFilter: "",
    setRankingNameFilter: noop,
    rankingPage: 1,
    setRankingPage: noop,
    dbPage: 1,
    setDbPage: noop,
    bracketEvents: null,
    setBracketEvents: noop,
    bracketSelectedEvent: null,
    setBracketSelectedEvent: noop,
    bracketCategories: null,
    setBracketCategories: noop,
    bracketSelectedCategory: null,
    setBracketSelectedCategory: noop,
    bracketCompetitors: null,
    setBracketCompetitors: noop,
    bracketEventTotal: null,
    setBracketEventTotal: noop,
    bracketMatches: null,
    setBracketMatches: noop,
    bracketMatLinks: null,
    setBracketMatLinks: noop,
    bracketSortColumn: "rating",
    setBracketSortColumn: noop,
    bracketRegistrationEventName: "",
    setBracketRegistrationEventName: noop,
    bracketRegistrationEventTotal: null,
    setBracketRegistrationEventTotal: noop,
    bracketRegistrationEventUrl: "",
    setBracketRegistrationEventUrl: noop,
    bracketRegistrationCategories: null,
    setBracketRegistrationCategories: noop,
    bracketRegistrationSelectedCategory: null,
    setBracketRegistrationSelectedCategory: noop,
    bracketRegistrationCompetitors: null,
    setBracketRegistrationCompetitors: noop,
    bracketRegistrationUpcomingLinks: [],
    setBracketRegistrationUpcomingLinks: noop,
    bracketRegistrationSelectedUpcomingLink: "",
    setBracketRegistrationSelectedUpcomingLink: noop,
    bracketRegistrationViewMode: "all",
    setBracketRegistrationViewMode: noop,
    bracketArchiveEventName: "",
    setBracketArchiveEventName: noop,
    bracketArchiveEventNameFetch: "",
    setBracketArchiveEventNameFetch: noop,
    bracketArchiveCategories: null,
    setBracketArchiveCategories: noop,
    bracketArchiveSelectedCategory: null,
    setBracketArchiveSelectedCategory: noop,
    bracketArchiveCompetitors: null,
    setBracketArchiveCompetitors: noop,
    bracketArchiveMatches: null,
    setBracketArchiveMatches: noop,
    bracketArchiveEventTotal: null,
    setBracketArchiveEventTotal: noop,
    calcGender: "Male",
    setCalcGender: noop,
    calcFirstAthlete: "",
    setCalcFirstAthlete: noop,
    calcSecondAthlete: "",
    setCalcSecondAthlete: noop,
    calcAge: "Adult",
    setCalcAge: noop,
    calcBelt: "BLACK",
    setCalcBelt: noop,
    calcFirstWeight: "Heavy",
    setCalcFirstWeight: noop,
    calcSecondWeight: "Heavy",
    setCalcSecondWeight: noop,
    calcCustomInfo: false,
    setCalcCustomInfo: noop,
    language: "en",
    setLanguage: noop,
    athletePage: 1,
    setAthletePage: noop,
    medalCaseOpen: false,
    setMedalCaseOpen: noop,
  };
}

async function render() {
  await bundleComponent();
  const React = await import("react");
  const { renderToStaticMarkup } = await import("react-dom/server");
  const { AppContext } = await import("./seoAppContext.js");
  const { default: About } = await import(pathToFileURL(bundleFile).href);

  const markup = renderToStaticMarkup(
    React.createElement(
      AppContext.Provider,
      { value: buildMockContext() },
      React.createElement(About)
    )
  );

  await fs.promises.mkdir(outputDir, { recursive: true });
  await fs.promises.writeFile(outputFile, markup, "utf-8");
  // Best-effort cleanup, ignore errors
  try {
    await fs.promises.rm(bundleFile, { force: true });
  } catch (err) {
    console.warn("Warning: unable to remove temp bundle", err);
  }
  console.log(`Wrote SEO snippet to ${outputFile}`);
}

render().catch((err) => {
  console.error(err);
  process.exit(1);
});
