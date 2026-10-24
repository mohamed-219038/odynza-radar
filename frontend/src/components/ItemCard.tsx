/* One social-media draft (text, hashtags, picture, reel kit) with approve, reject, posted and edit. */
import { useEffect, useRef, useState } from "react";
import { request, send } from "../api";
import { safePath } from "../format";
import type { ContentItem, ItemStatus } from "../types";
import { useToast } from "./Toast";

const FORMAT_LABEL: Record<ContentItem["format"], string> = { post: "Image post", carousel: "Carousel", document: "Document (PDF carousel)", reel: "Reel", story: "Story" };
const STATUS_LABEL: Record<ItemStatus, [string, string]> = {
  draft: ["Draft · needs review", "running"],
  approved: ["Approved", ""],
  rejected: ["Rejected", "neutral"],
  posted: ["Posted", ""],
};

export const runActive = (status: string) => ["queued", "running"].includes(status);

const caption = (item: ContentItem) => [item.content.text, item.content.hashtags.join(" ")].filter(Boolean).join("\n\n");

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function ItemCard({ item, canEdit, onChange }: { item: ContentItem; canEdit: boolean; onChange: (item: ContentItem) => void }) {
  const toast = useToast();
  const c = item.content;
  const [text, setText] = useState(c.text);
  const [hashtags, setHashtags] = useState(c.hashtags.join(" "));
  const [imagePrompt, setImagePrompt] = useState(c.image_prompt || "");
  const [busy, setBusy] = useState("");
  const imageInput = useRef<HTMLInputElement>(null);
  const videoInput = useRef<HTMLInputElement>(null);
  const edited = text !== c.text || hashtags !== c.hashtags.join(" ") || imagePrompt !== (c.image_prompt || "");
  const reel = item.format === "reel";

  useEffect(() => {
    setText(c.text);
    setHashtags(c.hashtags.join(" "));
    setImagePrompt(c.image_prompt || "");
  }, [c.text, c.hashtags, c.image_prompt]);

  async function act(label: string, path: string, init: RequestInit, done?: string) {
    setBusy(label);
    try {
      onChange(await request<ContentItem>(path, init));
      if (done) toast(done);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  const patch = (body: object, done?: string) => act("save", `/content/items/${item.id}`, { method: "PATCH", body: JSON.stringify(body) }, done);
  const save = () =>
    patch({ text, hashtags: hashtags.split(/[\s,]+/).filter(Boolean), image_prompt: imagePrompt }, "Draft saved.");

  async function makeImage() {
    if (imagePrompt !== (c.image_prompt || "")) await patch({ image_prompt: imagePrompt });
    await act("image", `/content/items/${item.id}/image`, { method: "POST" });
  }

  async function upload(kind: "image" | "video", file: File | undefined) {
    if (!file) return;
    setBusy(kind + "-upload");
    try {
      const r = await send(`/content/items/${item.id}/media/${kind}`, { method: "PUT", body: file, headers: { "Content-Type": file.type || "application/octet-stream" } });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Upload failed (${r.status}).`);
      onChange(body as ContentItem);
      toast(kind === "image" ? "Image uploaded." : "Reel uploaded.");
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function copyText(value: string, what: string) {
    toast((await copy(value)) ? `${what} copied.` : "Copy failed: select the text and copy it by hand.");
  }

  const image = safePath(item.image_url);
  const video = safePath(item.video_url);
  const [statusLabel, statusStyle] = STATUS_LABEL[item.status];
  return (
    <article className={`content-item content-${item.status}`} data-item={item.id}>
      <header className="content-item-top">
        <span className={`platform-chip ${item.platform.toLowerCase()}`}>{item.platform}</span>
        <b>{new Date(item.date + "T00:00:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}</b>
        <span className="muted">
          {FORMAT_LABEL[item.format]}
          {c.campaign_name ? ` · ${c.campaign_name}` : ""}
        </span>
        <span className={`badge ${statusStyle}`}>{statusLabel}</span>
      </header>
      <div className="content-item-body">
        <div className="content-media">
          <div className={`media-frame aspect-${item.aspect.replace(":", "x")}`}>
            {image ? (
              <img src={image} alt={`${reel ? "Key frame" : "Image"} for the ${item.platform} post on ${item.date}`} loading="lazy" />
            ) : (
              <span className="media-empty">
                {item.image_status === "pending" || busy === "image" ? "Making the image…" : item.image_error || "No image yet."}
              </span>
            )}
          </div>
          {image && item.image_error ? <p className="report-error">{item.image_error}</p> : null}
          {canEdit ? (
            <div className="media-actions">
              <button className="button secondary small-button" disabled={Boolean(busy) || !imagePrompt.trim()} onClick={makeImage}>
                {busy === "image" ? "Making…" : image ? "Remake image" : "Make image"}
              </button>
              <button className="button secondary small-button" disabled={Boolean(busy)} onClick={() => imageInput.current?.click()}>
                Upload image
              </button>
              <input ref={imageInput} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => upload("image", e.target.files?.[0])} />
            </div>
          ) : null}
          {image ? (
            <a className="text-link" href={`${image}&download=true`}>
              Download {reel ? "key frame" : "image"} ↓
            </a>
          ) : null}
          <details className="prompt-box">
            <summary>Image prompt</summary>
            <textarea rows={5} maxLength={2000} value={imagePrompt} readOnly={!canEdit} onChange={(e) => setImagePrompt(e.target.value)}></textarea>
            <button type="button" className="text-link" onClick={() => copyText(imagePrompt, "Image prompt")}>
              Copy for the Gemini app
            </button>
          </details>
        </div>
        <div className="content-copy">
          {c.checks?.length ? (
            <ul className="content-checks" aria-label="Check before posting">
              {c.checks.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          ) : null}
          <label>
            Caption
            <textarea className="caption" rows={9} maxLength={6000} value={text} readOnly={!canEdit} onChange={(e) => setText(e.target.value)} dir="auto"></textarea>
          </label>
          <label>
            Hashtags
            <input value={hashtags} readOnly={!canEdit} onChange={(e) => setHashtags(e.target.value)} dir="auto" />
          </label>
          {c.on_image_text ? (
            <p className="muted">
              Text on the image: <b dir="auto">{c.on_image_text}</b>
            </p>
          ) : null}
          {c.slides.length ? (
            <ol className="content-slides">
              {c.slides.map((s, i) => (
                <li key={i} dir="auto">
                  <b>{s.headline}</b> {s.body}
                </li>
              ))}
            </ol>
          ) : null}
          {reel ? (
            <div className="reel-kit">
              <span className="eyebrow">REEL · {c.reel_seconds || 6} SECONDS · 9:16</span>
              <p className="reel-prompt">{c.higgsfield_prompt}</p>
              <ol>
                <li>Download the key frame above.</li>
                <li>
                  In Google Flow (Veo, included in your Google AI plan) start a new video from an image: upload the key frame as the first frame and
                  paste the prompt. Higgsfield (Image to Video) works the same way.
                </li>
                <li>Choose vertical 9:16, keep the clip short, then download the MP4 and upload it here.</li>
              </ol>
              <div className="media-actions">
                <button type="button" className="button secondary small-button" onClick={() => copyText(c.higgsfield_prompt || "", "Video prompt")}>
                  Copy prompt
                </button>
                <a className="button secondary small-button" href="https://labs.google/fx/tools/flow" target="_blank" rel="noopener noreferrer">
                  Open Google Flow ↗
                </a>
                <a className="button secondary small-button" href="https://higgsfield.ai" target="_blank" rel="noopener noreferrer">
                  Higgsfield ↗
                </a>
                {canEdit ? (
                  <button className="button secondary small-button" disabled={Boolean(busy)} onClick={() => videoInput.current?.click()}>
                    {busy === "video-upload" ? "Uploading…" : video ? "Replace video" : "Upload video"}
                  </button>
                ) : null}
                <input ref={videoInput} type="file" accept="video/mp4,video/quicktime,video/webm" hidden onChange={(e) => upload("video", e.target.files?.[0])} />
              </div>
              {video ? <video src={video} controls preload="metadata" className="reel-video"></video> : null}
            </div>
          ) : null}
          {c.why ? <p className="muted content-why">Why this post: {c.why}</p> : null}
        </div>
      </div>
      <footer className="content-item-actions">
        <button type="button" className="button secondary small-button" onClick={() => copyText(caption({ ...item, content: { ...c, text, hashtags: hashtags.split(/\s+/).filter(Boolean) } }), "Caption")}>
          Copy caption
        </button>
        {canEdit ? (
          <div>
            {edited ? (
              <button className="button secondary small-button" disabled={Boolean(busy)} onClick={save}>
                Save changes
              </button>
            ) : null}
            {item.status !== "rejected" && item.status !== "posted" ? (
              <button className="button secondary small-button" disabled={Boolean(busy)} onClick={() => patch({ status: "rejected" })}>
                Reject
              </button>
            ) : null}
            {item.status === "approved" ? (
              <button className="button secondary small-button" disabled={Boolean(busy)} onClick={() => patch({ status: "posted" }, "Marked as posted.")}>
                Mark posted
              </button>
            ) : null}
            {item.status === "draft" || item.status === "rejected" ? (
              <button className="button primary small-button" disabled={Boolean(busy) || edited} title={edited ? "Save your changes first" : undefined} onClick={() => patch({ status: "approved" }, "Approved.")}>
                Approve
              </button>
            ) : (
              <button className="button secondary small-button" disabled={Boolean(busy)} onClick={() => patch({ status: "draft" })}>
                Back to draft
              </button>
            )}
          </div>
        ) : null}
      </footer>
    </article>
  );
}
