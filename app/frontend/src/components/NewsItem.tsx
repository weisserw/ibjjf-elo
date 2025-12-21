
import { useParams, Link } from "react-router-dom";
import { useSingleNewsPost } from "../useNewsPosts";

export default function NewsItem() {
	const { id } = useParams<{ id: string }>();
	const { post, loading, error } = useSingleNewsPost(id || "");

	return (
		<section className="section">
			<div className="container">
				{loading && (
					<div className="loader" />
				)}

				{error && (
					<p className="has-text-danger">{error}</p>
				)}

				{post && (
					<article className="box mb-5">
						<h1 className="title is-4">{post.title}</h1>
						<p className="is-size-7 has-text-grey mb-3">
							{new Date(post.date).toLocaleDateString()} by {post.author.name}
						</p>
						<div
							className="content"
							dangerouslySetInnerHTML={{ __html: post.content }}
						/>
					</article>
				)}

				<Link to="/news" className="mt-4">Recent Article List</Link>
			</div>
		</section>
	);
}
