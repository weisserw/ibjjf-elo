#!/usr/bin/env node
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const WP_API =
  "https://public-api.wordpress.com/rest/v1.1/sites/ibjjfrankings.wordpress.com/posts";
const OUTPUT_DIR = path.resolve(__dirname, "..", "..", "seo_snippets");
const OUTPUT_FILE = path.resolve(OUTPUT_DIR, "news.html");

function errorDetails(err) {
  const cause = err?.cause;
  const causeMsg =
    cause?.code || cause?.message || (typeof cause === "string" ? cause : "");
  return causeMsg ? `${err.message} (${causeMsg})` : err.message;
}

async function fetchJson(url, timeoutMs = 10000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const resp = await fetch(url, {
    signal: controller.signal,
    headers: { "user-agent": "ibjjfrankings-seo-news/1.0" },
  });
  clearTimeout(timeout);

  if (!resp.ok) {
    throw new Error(`Failed to fetch news: ${resp.status} ${await resp.text()}`);
  }
  return resp.json();
}

async function fetchNews() {
  const wpComUrl = new URL(WP_API);
  wpComUrl.searchParams.set("number", "10");
  wpComUrl.searchParams.set("order", "desc");
  wpComUrl.searchParams.set("orderby", "date");

  const attempts = [];

  try {
    const body = await fetchJson(wpComUrl.toString());
    return (body.posts || []).map((post) => ({
      title: post.title || "Untitled",
      link: post.URL || "#",
      date: post.date,
      excerpt: post.excerpt || "",
    }));
  } catch (err) {
    attempts.push(`wp.com API: ${errorDetails(err)}`);
  }

  try {
    const wpJsonUrl =
      "https://ibjjfrankings.wordpress.com/wp-json/wp/v2/posts?per_page=10&order=desc&orderby=date&_fields=date,link,title,excerpt";
    const posts = await fetchJson(wpJsonUrl);
    return (posts || []).map((post) => ({
      title: post?.title?.rendered || "Untitled",
      link: post?.link || "#",
      date: post?.date,
      excerpt: post?.excerpt?.rendered || "",
    }));
  } catch (err) {
    attempts.push(`wp-json API: ${errorDetails(err)}`);
  }

  throw new Error(`All news sources failed. ${attempts.join(" | ")}`);
}

function formatDate(dateStr) {
  try {
    return new Date(dateStr).toISOString().split("T")[0];
  } catch {
    return "";
  }
}

function buildHtml(posts) {
  const items = posts
    .map((post) => {
      const title = post.title || "Untitled";
      const link = post.link || "#";
      const date = formatDate(post.date);
      const excerpt = (post.excerpt || "").replace(/<[^>]*>?/gm, "").trim();
      return `<li style="margin-bottom:10px;">
        <a href="${link}" style="font-weight:bold;">${title}</a>
        <div style="font-size:12px;color:#555;">${date}</div>
        <div style="font-size:14px;color:#333;">${excerpt}</div>
      </li>`;
    })
    .join("");

  return `<section style="padding:24px;font-family:Arial,Helvetica,sans-serif;">
    <h1 style="font-size:24px;margin:0 0 12px;">IBJJF News</h1>
    <p style="margin:0 0 12px;font-size:14px;color:#444;">Latest News Posts</p>
    <ul style="list-style:disc;padding-left:18px;margin:0;">${items || "<li>No recent posts available.</li>"}</ul>
  </section>`;
}

async function main() {
  try {
    const posts = await fetchNews();
    const html = buildHtml(posts);
    await fs.promises.mkdir(OUTPUT_DIR, { recursive: true });
    await fs.promises.writeFile(OUTPUT_FILE, html, "utf-8");
    console.log(`Wrote news snippet to ${OUTPUT_FILE}`);
  } catch (err) {
    console.error("seo:news failed, writing fallback snippet:", err.message);
    const fallback = `<section style="padding:24px;font-family:Arial,Helvetica,sans-serif;">
      <h1 style="font-size:24px;margin:0 0 12px;">IBJJF News</h1>
      <p style="margin:0;font-size:14px;color:#444;">News is temporarily unavailable. Please check back soon.</p>
    </section>`;
    await fs.promises.mkdir(OUTPUT_DIR, { recursive: true });
    await fs.promises.writeFile(OUTPUT_FILE, fallback, "utf-8");
    // Do not fail the build on news fetch issues
  }
}

main();
