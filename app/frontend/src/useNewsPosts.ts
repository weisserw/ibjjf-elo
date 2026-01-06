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
  author: {
    name: string;
  }
  categories: Record<string, {name: string;}>;
}

interface CachedPosts {
  timestamp: number;
  data: WPPost[];
}

interface PostsResponse {
  posts?: WPPost[];
  error?: string;
}

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

const SINGLE_POST_CACHE_PREFIX = "wp_news_single_";

interface CachedSinglePost {
  timestamp: number;
  data: WPPost;
}

export function useSingleNewsPost(id: string) {
  const [post, setPost] = useState<WPPost | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // First, check the list cache
    const now = Date.now();
    const cachedListRaw = localStorage.getItem(CACHE_KEY);
    if (cachedListRaw) {
      try {
        const cachedList: CachedPosts = JSON.parse(cachedListRaw);
        if (now - cachedList.timestamp < CACHE_TTL) {
          const found = cachedList.data.find((p) => String(p.ID) === id);
          if (found) {
            setPost(found);
            setLoading(false);
            setError(null);
            return;
          }
        }
      } catch {}
    }

    // Next, check and clean single post cache
    const cleanAndGetCached = (): WPPost | null => {
      let found: WPPost | null = null;
      for (let i = localStorage.length - 1; i >= 0; i--) {
        const key = localStorage.key(i);
        if (key && key.startsWith(SINGLE_POST_CACHE_PREFIX)) {
          try {
            const cached: CachedSinglePost = JSON.parse(localStorage.getItem(key)!);
            if (now - cached.timestamp > CACHE_TTL) {
              localStorage.removeItem(key);
            } else if (key === SINGLE_POST_CACHE_PREFIX + id) {
              found = cached.data;
            }
          } catch {
            localStorage.removeItem(key!);
          }
        }
      }
      return found;
    };

    const loadPost = async () => {
      setLoading(true);
      setError(null);
      const cached = cleanAndGetCached();
      if (cached) {
        setPost(cached);
        setLoading(false);
        return;
      }
      try {
        const res = await axios.get<{ post?: WPPost; error?: string }>(`/api/news/${id}`);
        if (res.data.error || !res.data.post) {
          setError(res.data.error || "Post not found");
          setLoading(false);
          return;
        }
        setPost(res.data.post);
        const cache: CachedSinglePost = {
          timestamp: Date.now(),
          data: res.data.post
        };
        localStorage.setItem(SINGLE_POST_CACHE_PREFIX + id, JSON.stringify(cache));
        setLoading(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : "An unknown error occurred");
        setLoading(false);
      }
    };
    if (id) {
      loadPost();
    } else {
      setPost(null);
      setLoading(false);
    }
  }, [id]);

  return { post, loading, error };
}
