function About() {
  return (
    <section className="section">
      <div className="container">
        <h1 className="title">About This App</h1>
        <p className="content">
          IBJJFRankings.com ranks competitors and provides a comprehensive database of matches in events run by the <a href="https://ibjjf.com/" target="_blank" rel="noopener noreferrer">International Braziliation Jiu-Jitsu Federation</a>.
        </p>
        <p className="content">
          Competitors are rated using the <a href="https://en.wikipedia.org/wiki/Elo_rating_system" target="_blank" rel="noopener noreferrer">Elo rating system</a>, which is a method for calculating the relative skill levels of players in two-player games such as chess. The app allows users to search for competitors, view their ratings, and see their match history.
        </p>
        <p className="content">
          The app is a work in progress and is being developed by <a href="https://www.facebook.com/Trumpetdanbjj" target="_blank" rel="noopener noreferrer">Dan Lukehart</a> and <a href="https://www.instagram.com/weisserwill/" target="_blank" rel="noopener noreferrer">Will Weisser</a>. The source code is available on <a href="https://github.com/weisserw/ibjjf-elo">GitHub</a>.
          Ratings may be subject to change as the app is developed and improved.
        </p>
        <h1 className="title">FAQ</h1>
        <p className="content">
          <strong>Q: Why do we need an IBJJF ranking app when the IBJJF has its own ranking system?</strong>
        </p>
        <p className="content">
          A: There are two primary reasons why this site exists:

          <ul>
            <li>The IBJJF's ranking system is based on medals won in IBJJF tournaments. While we applaud the IBJJF for adopting
              and using an objective ranking system to seed their tournaments, there are some drawbacks to the current system; for example,
              in divisions with fewer average competitors where default medals are common, an athlete's ranking is more reflective of their
              willingness to compete than their actual skill. We hope that this app encourages the IBJJF to adopt some sort of skill-based
              ranking system, which will be both fairer and provide more useful information to competitors.</li>
            <li>The IBJJF has adopted the practice of deleting all individual match results from its database soon after events end.
              These results contain a wealth of information of interest to competitors, coaches, and fans. This app aims to preserve
              this information and make it accessible to the public.
            </li>
          </ul>
        </p>
        <p className="content">
          <strong>Q: Will you support other jiu-jitsu competitions other than the IBJJF?</strong>
        </p>
        <p className="content">
          A: We would like to support other competitions in the future, but we are starting with the IBJJF because it is the largest and most prestigious jiu-jitsu organization in the world.
        </p>
        <p className="content">
          <strong>Q: Why use the Elo system when better rating systems exist?</strong>
        </p>
        <p className="content">
          A: Since Elo invented his rating system, many statisticians have developed alternate systems with additional features.
          However, some of these features are not necessary for our purposes. For example, because the IBJJF does not normally
          record how a match was decided (points, submission, etc.), we cannot use a feature of a rating system that takes into account
          a margin of victory.
        </p>
        <p className="content">
          The main reason we use the Elo system is its simplicity, which makes it easy to understand. This aligns with our goal of keeping
          our data and processes as transparent as possible.
        </p>
        <p className="content">
          <strong>Q: I see a problem with one of my match results or my rating. What should I do?</strong>
        </p>
        <p className="content">
          A: Please contact us at <strong>???</strong> and we will investigate the issue and make a fix if one is warranted.
        </p>
        <p className="content">
          <strong>Q: How far back in time does your database go?</strong>
        </p>
        <p className="content">
          A: Unfortunately, since we are starting from scratch, we only have access to historical data for a limited number of competitors.
          For most competitors, match data will accumulate starting in December 2024, and we hope to keep a comprehensive record of matches
          from that point forward. Although the rating system won't be as accurate until more data is accumulated, over time it will become
          more reliable.
        </p>
        <p className="content">
          <strong>Q: How do you determine the ratings for each belt?</strong>
        </p>
        <p className="content">
          A: We don't determine ratings for each belt per se. We do assign an initial rating to new competitors based on their belt level.
          These initial ratings are estimates and we may modify them as we gather more data. But regardless of your initial rating, your rating will change over
          time based on your match results, until it converges to a value that reflects your skill level relative to other competitors.
        </p>
        <p className="content">
          To help this process along, we use a dynamic K-factor system that increases the speed of your rating changes when you have fewer
          matches recorded in the system. As you accumulate more matches, the system becomes more confident and your rating
          will change more slowly.
        </p>
        <p className="content">
          <strong>Q: I lost to a competitor without many recorded matches who was under-rated, and I lost a bunch of rating points!</strong>
        </p>
        <p className="content">
          A: This is a feature of the system working as intended. The solution is to compete more; as you yourself may now be under-rated,
          you will gain more rating points on average when you win.
        </p>
        <p className="content">
          <strong>Q: Will my rating get reset when I change my weight, rank or age division?</strong>
        </p>
        <p className="content">
          A: Your rating stays with you regardless of weight or rank. Different age divisions are treated as separate pools of competitors,
          so your rating will not carry over from one age division to another. Gi and no-gi are also given separate ratings.
        </p>
        <p className="content">
          <strong>Q: What about open class?</strong>
        </p>
        <p className="content">
          A: Open class is a special case. In any other weight division, a match is, in theory, a fair test of skill because both competitors are
          required to make weight. If we rated open class matches the same as any other match, we would introduce bias into the system
          because the advantage of being a heavier weight would not be accounted for.
        </p>
        <p className="content">
          For this reason, we rate open class matches thusly:
          <ul>
            <li>When two competitors meet in the open class, we look at the last weight division they competed in and made weight for.</li>
            <li>If the weight divisions are less than two divisions apart, we rank the match like any other.</li>
            <li>If the weight divisions are further apart, we still record the match but do not change the competitor's ratings.</li>
          </ul>
        </p>
        <p className="content">
           This system is a compromise until we have more data and can confidently modify the algorithm to correct for weight differences.
        </p>
        <p className="content">
          <strong>Q: Why are some highly rated competitors not shown on the front page?</strong>
        </p>
        <p className="content">
          The rating system is less accurate when a competitor has not competed in a long time. To prevent stale ratings from appearing on the front page,
          we only show competitors who have competed in the last three years. If these competitors compete again, they will reappear on the front page
          and the system will temporarily increase their K factor to reflect the uncertainty in their rating.
        </p>
        <p className="content">
          <strong>Q: I keep losing rating points and it makes me feel like I shouldn't be at my current rank.</strong>
        </p>
        <p className="content">
          A: Your rating and your rank are two different things. Your rating is a reflection of your ability to win competition matches. 
          Your rank is a reflection of your progress in jiu-jitsu as determined by your instructor. The two are not necessarily related.
        </p>
        <p className="content">
          <strong>Q: Are you going to track kids divisions?</strong>
        </p>
        <p className="content">
          A: We have decided not to track age divisions below Juvenile 1 at this time.
        </p>
      </div>
    </section>
  );
}

export default About
