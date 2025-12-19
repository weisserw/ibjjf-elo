
import { useEffect } from "react";
import useNewsPosts, { WPPost } from "../useNewsPosts";

export default function NewsList() {
  const { posts, loading, error } = useNewsPosts();

  // Scroll to anchor if hash is present, after posts are loaded
  useEffect(() => {
    const scrollToHash = () => {
      if (window.location.hash) {
        const id = window.location.hash.slice(1);
        const el = document.getElementById(id);
        if (el) {
          el.scrollIntoView({ behavior: "instant", block: "start" });
        }
      }
    };
    scrollToHash();
    window.addEventListener("hashchange", scrollToHash);
    return () => window.removeEventListener("hashchange", scrollToHash);
  }, [posts]);

  if (loading) {
    return (
      <section className="section">
        <div className="container">
          <p>Loading news…</p>
        </div>
      </section>
    );
  }

  if (error) {
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

        {posts.map((post: WPPost) => {
          return (
            <article key={post.ID} id={`${post.ID}`} className="box mb-5">
              <h2 className="title is-4">{post.title}</h2>

              <p className="is-size-7 has-text-grey mb-3">
                {new Date(post.date).toLocaleDateString()}
              </p>

              <div
                className="content"
                dangerouslySetInnerHTML={{
                  __html: post.content
                }}
              />
            </article>
          );
        })}
      </div>
    </section>
  );
}
