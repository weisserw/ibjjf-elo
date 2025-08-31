import { t } from "../translate"
import { useAppContext } from "../AppContext";

function About() {
  useAppContext();

  return (
    <section className="section">
      <div className="container">
        <h1 className="title">{t("About This App")}</h1>
        <p className="content">{t("IBJJFRankings.com ranks competitors and provides a comprehensive database of matches in events run by the")}{' '}
          <a href="https://ibjjf.com/" target="_blank" rel="noopener noreferrer">{t("International Brazilian Jiu-Jitsu Federation")}</a>
          {t(". We are an independant site and are not affiliated with the IBJJF.")}
        </p>
        <p className="content">{t("Competitors are rated using the")}{' '}
          <a href="https://en.wikipedia.org/wiki/Elo_rating_system" target="_blank" rel="noopener noreferrer">{t("Elo rating system")}</a>
          {t(", which is a method for calculating the relative skill levels of players in competitive games. We allow users to search for competitors, view their ratings, and see their match history.")}
        </p>
        <p className="content">{t("This app is a work in progress and is being developed by")}{' '}
          <a href="https://www.facebook.com/Trumpetdanbjj" target="_blank" rel="noopener noreferrer">Dan Lukehart</a>{' '}{t("and")}{' '}
          <a href="https://www.instagram.com/weisserwill/" target="_blank" rel="noopener noreferrer">Will Weisser</a>
          {t(". The source code is available on ")}{' '}
          <a href="https://github.com/weisserw/ibjjf-elo">GitHub</a>.{' '}
          {t("Ratings may be subject to change as the app is developed and improved.")}
        </p>
        <p className="content">{t("We host and maintain this app as a free service to the jiu-jitsu community. If you would like to support us, please consider")}{' '}
          <a href="https://ko-fi.com/ibjjfrankings" target="_blank" rel="noopener noreferrer">{t("donating")}</a>.
        </p>
        <p className="content">{t("If you would like a copy of our source data for research purposes, ")}{' '}
          <a href="https://www.instagram.com/ibjjfrankings/" target="_blank" rel="noopener noreferrer">{t("contact us")}</a>{' '}
          {t("and we'll be happy to help. You have permission to use data or screenshots from this site in articles, blog posts, and other media, but we ask that you credit IBJJFRankings.com. Because of our free and open nature and the work put into this app, we ask that you refrain from using our data for other purposes without asking, especially the custom jiu-jitsu Elo ratings we calculate.")}
        </p>
        <h1 className="title">{t("FAQ")}</h1>
        <p className="content"><strong>{t("Q: Why do we need an IBJJF ranking app when the IBJJF has its own ranking system?")}</strong></p>
        <p className="content">{t("A: There are two primary reasons why this site exists:")}
          <ul>
            <li>{t("The IBJJF's ranking system is based on medals won in IBJJF tournaments. While we applaud the IBJJF for adopting an objective ranking system to seed their tournaments, there are some drawbacks to their current system; for example, in divisions with fewer average competitors where default medals are common, an athlete's ranking is more reflective of their willingness to compete than their actual skill. We hope that this app encourages the IBJJF to adopt some sort of skill-based ranking system, which will be fairer and provide more useful information to competitors.")}</li>
            <li>{t("The IBJJF has adopted the practice of deleting all individual match results (other than podium finishes) from its database soon after events end. These results contain a wealth of information of interest to competitors, coaches, and fans. This app aims to preserve this information and make it accessible to the public.")}</li>
          </ul>
        </p>
        <p className="content"><strong>{t("Q: Will you support jiu-jitsu competitions other than the IBJJF?")}</strong></p>
        <p className="content">{t("A: We would like to support other competitions in the future, but we are starting with the IBJJF because it is the largest and most prestigious jiu-jitsu organization in the world.")}</p>
        <p className="content"><strong>{t("Q: Why use the Elo system when other skill-based rating systems exist?")}</strong></p>
        <p className="content">{t("A: The main reason we use the Elo system is its simplicity, which makes it easy to understand. This aligns with our goal of keeping our data and processes as transparent as possible.")}</p>
        <p className="content"><strong>{t("Q: I see a problem with one of my match results or my rating. What should I do?")}</strong></p>
        <p className="content">{t("A: Please DM")}{' '}
          <a href="https://www.instagram.com/ibjjfrankings/" target="_blank" rel="noopener noreferrer">{t("ibjjfrankings on Instagram")}</a>{' '}
          {t("and we will investigate the issue and make a fix if one is warranted.")}
        </p>
        <p className="content"><strong>{t("Q: How far back in time does your database go?")}</strong></p>
        <p className="content">{t("A: Unfortunately, we don't have access to full historical data, but we have managed to collect over 150,000 match results covering the period from 2022-2024. Full match data will accumulate starting from December 2024, and we hope to keep a comprehensive record of matches from that point forward. Although the rating system won't be as accurate until more data is accumulated, it will become more reliable over time.")}</p>
        <p className="content"><strong>{t("Q: How do you determine the ratings for each belt?")}</strong></p>
        <p className="content">{t("A: We assign an initial rating to new competitors based on their belt level and age division. These initial ratings are estimates based on our statistical analysis of results as competitors progress through the belts. Regardless of your initial rating, your rating will change over time based on your wins and losses, until it converges to a value that reflects your skill level relative to other competitors.")}</p>
        <p className="content">{t("To help this process along, we use a dynamic K-factor system that increases the speed of your rating changes when you have fewer matches recorded in the system. As you accumulate more matches, the system becomes more confident and your rating will change more slowly.")}</p>
        <p className="content"><strong>{t("Q: I lost to a competitor without many recorded matches who was under-rated, and I lost a bunch of rating points!")}</strong></p>
        <p className="content">{t("A: This is a feature of the system working as intended. The solution is to compete more; as you yourself may now be under-rated, you will gain more rating points on average when you win.")}</p>
        <p className="content"><strong>{t("Q: Will my rating get reset when I change my weight, rank or age division?")}</strong></p>
        <p className="content">{t("A: Your rating stays with you regardless of weight, rank, or age. Gi and no-gi are given separate ratings.")}</p>
        <p className="content">{t("We make some adjustments to our scoring algorithm when we detect athletes have changed rank or age divisions. This is intended to keep the ratings of infrequent competitors in line with the overall skill level of their new division. We're happy to answer questions about our methodology or a particular athlete's rating if you")}{' '}
          <a href="https://www.instagram.com/ibjjfrankings/" target="_blank" rel="noopener noreferrer">{t("contact us")}</a>.{' '}
        </p>
        <p className="content"><strong>{t("Q: What about open class?")}</strong></p>
        <p className="content">{t("A: Open class is a special case. In any other weight division, a match is, in theory, a fair test of skill because both competitors are required to make weight. If we rated open class matches the same as any other match, we would introduce bias into the system because the advantage of being a heavier weight would not be accounted for.")}</p>
        <p className="content">{t("For this reason, for most open class matches we apply a handicap when calculating ratings. The handicap is based on the weight difference between the competitors and may change over time as we gather more data. With the handicap applied, a larger competitor will gain fewer rating points for a win and lose more for a loss, and vice versa for the smaller competitor.")}</p>
        <p className="content"><strong>{t("Q: Why are some highly rated competitors not shown on the front page?")}</strong></p>
        <p className="content">{t("The rating system is less accurate when a competitor has not competed in a long time. To prevent stale ratings from appearing on the front page, we only show competitors who have competed in the last year. If these competitors compete again, they will reappear on the front page and the system will temporarily increase their K factor to reflect the uncertainty in their rating.")}</p>
        <p className="content"><strong>{t("Q: I keep losing rating points and it makes me feel like I shouldn't be at my current rank.")}</strong></p>
        <p className="content">{t("A: Your rating and your rank are two different things. Your rating is a reflection of your ability to win competition matches. Your rank is a reflection of your progress in jiu-jitsu as determined by your instructor. The two are not necessarily related.")}</p>
        <p className="content"><strong>{t("Q: Are you going to track kids divisions?")}</strong></p>
        <p className="content">{t("A: We have decided to store a searchable list of teen matches as some of these athletes are beginning their serious competitive journey in the sport. However, we do not compute ratings for teens and we do not track younger divisions in order to promote a healthy competitive environment for children.")}</p>
      </div>
    </section>
  );

}

export default About
