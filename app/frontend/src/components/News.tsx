import { useEffect, useState } from "react";
import useNewsPosts, { WPPost } from "../useNewsPosts";
import { fixNewsTitle } from "../utils";

export default function NewsList() {
  const [page, setPage] = useState<number>(1);
  const [allPosts, setAllPosts] = useState<WPPost[]>([]);
  const { posts, loading, error, hasMore } = useNewsPosts(page);

  useEffect(() => {
    if (loading || error) {
      return;
    }
    setAllPosts((prev) => {
      if (page === 1) {
        return posts;
      }
      const seen = new Set(prev.map((post) => post.ID));
      const next = [...prev];
      posts.forEach((post) => {
        if (!seen.has(post.ID)) {
          next.push(post);
        }
      });
      return next;
    });
  }, [posts, loading, error, page]);

  if (loading && page === 1) {
    return (
      <section className="section">
        <div className="container">
          <div className="loader"/>
        </div>
      </section>
    );
  }

  if (error && page === 1) {
    return (
      <section className="section">
        <div className="container">
          <p className="has-text-danger">{error}</p>
        </div>
      </section>
    );
  }

  return (
    <section className="section">
      <div className="container">
        <h1 className="title">News</h1>

        {allPosts.map((post: WPPost) => {
          return (
            <article key={post.slug} className="box mb-5">
              <h2 className="title is-4">
                <a href={`/news/${post.ID}/${post.slug}`}>{fixNewsTitle(post.title)}</a>
              </h2>

              <p className="is-size-7 has-text-grey mb-3">
                {new Date(post.date).toLocaleDateString()}
                {' '}by {post.author.name}
              </p>

              <div
                className="content"
                dangerouslySetInnerHTML={{
                  __html: post.excerpt
                }}
              />
            </article>
          );
        })}

        {error ? (
          <p className="has-text-danger mt-4">{error}</p>
        ) : null}

        {hasMore ? (
          <div className="has-text-centered mt-5">
            <button
              className="button is-link is-light"
              onClick={() => setPage((prev) => prev + 1)}
              disabled={loading}
            >
              {loading ? "Loading..." : "Older posts"}
            </button>
          </div>
        ) : null}
      </div>
    </section>
  );
}
