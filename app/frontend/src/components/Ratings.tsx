import GiTabs from './GiTabs';
import EloTable from './EloTable';
import useNewsPosts from '../useNewsPosts';
import { useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';

import "./Ratings.css";

function Ratings() {
  const { posts, loading, error } = useNewsPosts();

  const navigate = useNavigate();

  const handleNewsClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    e.preventDefault();
    const href = e.currentTarget.getAttribute('href');
    
    navigate(href || '/news');
  };

  return (
    <div className="container">
      {!loading && !error && posts.length > 0 &&
        <section className="news-section">
          <span className="news-badge">Latest News:</span>
          <div className="news-posts">
            {posts.slice(0, 3).map((post, index) => (
              <>
                {index > 0 && <span className="news-separator">•</span>}
                <a key={post.slug} href={`/news/${post.ID}/${post.slug}`} className="news-link" onClick={handleNewsClick}>
                  {
                    index === 0 && dayjs().diff(dayjs(post.date), 'day') <= 3 &&
                    <span className="new-post-marker">New</span>
                  }
                  {post.title}
                </a>
              </>
            ))}
          </div>
        </section>
      }
      <GiTabs />
      <EloTable />
    </div>
  )
}

export default Ratings;
