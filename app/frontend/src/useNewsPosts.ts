import { useEffect, useState } from "react";
import axios from "axios";

const CACHE_KEY = "wp_news_cache";
const CACHE_TTL = 10 * 60 * 1000; // 10 minutes

export interface WPPost {
  ID: number;
  date: string;
  slug: string;
  URL: string;
  title: string;
  excerpt: string;
  content: string;
}

interface CachedPosts {
  timestamp: number;
  data: WPPost[];
}

interface PostsResponse {
  posts?: WPPost[];
  error?: string;
}

// ---- Hook ----

export default function useNewsPosts() {
  const [posts, setPosts] = useState<WPPost[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadPosts = async () => {
      try {
        const cachedRaw = localStorage.getItem(CACHE_KEY);

        if (cachedRaw) {
          const cached: CachedPosts = JSON.parse(cachedRaw);

          if (Date.now() - cached.timestamp < CACHE_TTL) {
            setPosts(cached.data);
            setLoading(false);
            return;
          }
        }

        const res = await axios.get<PostsResponse>("/api/news");

        if (res.data.error) {
          setError(res.data.error);
          setLoading(false);
          return;
        }

        setPosts(res.data.posts || []);

        const cache: CachedPosts = {
          timestamp: Date.now(),
          data: res.data.posts || []
        };

        localStorage.setItem(CACHE_KEY, JSON.stringify(cache));
        setLoading(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : "An unknown error occurred");
        setLoading(false);
      }
    };

    loadPosts();
  }, []);

  return { posts, loading, error };
}
