import { useEffect, useState } from "react";
import axios from "axios";

const CACHE_KEY_PREFIX = "wp_news_cache_page_";
const CACHE_TIMESTAMP_KEY = "wp_news_cache_timestamp";
const CACHE_TTL = 10 * 60 * 1000; // 10 minutes
const PER_PAGE = 10;

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
  found?: number;
}

interface PostsResponse {
  posts?: WPPost[];
  found?: number;
  error?: string;
}

export default function useNewsPosts(page = 1) {
  const [posts, setPosts] = useState<WPPost[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState<boolean>(false);

  useEffect(() => {
    const loadPosts = async () => {
      try {
        const now = Date.now();
        const cacheTimestampRaw = localStorage.getItem(CACHE_TIMESTAMP_KEY);
        const cacheTimestamp = cacheTimestampRaw ? Number(cacheTimestampRaw) : 0;
        if (!cacheTimestamp || now - cacheTimestamp > CACHE_TTL) {
          for (let i = localStorage.length - 1; i >= 0; i--) {
            const key = localStorage.key(i);
            if (key && key.startsWith(CACHE_KEY_PREFIX)) {
              localStorage.removeItem(key);
            }
          }
          localStorage.removeItem(CACHE_TIMESTAMP_KEY);
        }

        const cacheKey = `${CACHE_KEY_PREFIX}${page}`;
        const cachedRaw = localStorage.getItem(cacheKey);

        if (cachedRaw) {
          const cached: CachedPosts = JSON.parse(cachedRaw);
          setPosts(cached.data);
          setHasMore(
            cached.found !== undefined
              ? page * PER_PAGE < cached.found
              : cached.data.length === PER_PAGE
          );
          setLoading(false);
          return;
        }

        const res = await axios.get<PostsResponse>("/api/news", {
          params: { page }
        });

        if (res.data.error) {
          setError(res.data.error);
          setLoading(false);
          return;
        }

        setPosts(res.data.posts || []);
        setHasMore(
          res.data.found !== undefined
            ? page * PER_PAGE < res.data.found
            : (res.data.posts || []).length === PER_PAGE
        );

        const cache: CachedPosts = {
          timestamp: Date.now(),
          data: res.data.posts || [],
          found: res.data.found
        };

        localStorage.setItem(cacheKey, JSON.stringify(cache));
        localStorage.setItem(CACHE_TIMESTAMP_KEY, String(Date.now()));
        setLoading(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : "An unknown error occurred");
        setLoading(false);
      }
    };

    loadPosts();
  }, [page]);

  return { posts, loading, error, hasMore };
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
    const cacheTimestampRaw = localStorage.getItem(CACHE_TIMESTAMP_KEY);
    const cacheTimestamp = cacheTimestampRaw ? Number(cacheTimestampRaw) : 0;
    if (cacheTimestamp && now - cacheTimestamp < CACHE_TTL) {
      for (let i = localStorage.length - 1; i >= 0; i--) {
        const key = localStorage.key(i);
        if (key && key.startsWith(CACHE_KEY_PREFIX)) {
          try {
            const cachedList: CachedPosts = JSON.parse(localStorage.getItem(key)!);
            const found = cachedList.data.find((p) => String(p.ID) === id);
            if (found) {
              setPost(found);
              setLoading(false);
              setError(null);
              return;
            }
          } catch {}
        }
      }
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
