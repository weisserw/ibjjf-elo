import useNewsPosts, { WPPost } from "../useNewsPosts";
import { fixNewsTitle } from "../utils";

export default function NewsList() {
  const { posts, loading, error } = useNewsPosts();

  if (loading) {
    return (
      <section className="section">
        <div className="container">
          <div className="loader"/>
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
      </div>
    </section>
  );
}
