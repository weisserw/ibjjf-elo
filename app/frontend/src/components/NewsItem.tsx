import { useEffect } from "react";
import axios from "axios";
import { useParams, Link } from "react-router-dom";
import { useSingleNewsPost } from "../useNewsPosts";
import { fixNewsTitle } from "../utils";

export default function NewsItem() {
	const { id } = useParams<{ id: string }>();
	const { post, loading, error } = useSingleNewsPost(id || "");

	useEffect(() => {
		if (id) {
			axios.post(`/api/news/${id}/view`).catch(() => {});
    }
  }, [id]);  

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
						<h1 className="title is-4">{fixNewsTitle(post.title)}</h1>
						<p className="is-size-7 has-text-grey mb-3">
							Posted on {new Date(post.date).toLocaleDateString()} by {post.author.name}
						</p>
						{
							Object.values(post.categories).some(cat => cat.name === "IG Story Summaries") && (
								<p className="is-size-7 has-text-grey mb-5">
									<em>This article was summarized from <a href="https://www.instagram.com/ibjjfrankings/" target="_blank" rel="noopener noreferrer">IG stories</a> posted by Dan Lukehart</em>
								</p>
							)
						}
						<div
							className="wordpress content"
							dangerouslySetInnerHTML={{ __html: post.content }}
						/>
					</article>
				)}

				<Link to="/news" className="mt-4">Recent Article List</Link>
			</div>
		</section>
	);
}
