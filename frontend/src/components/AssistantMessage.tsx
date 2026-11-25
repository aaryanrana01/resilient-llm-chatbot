import type { ChatMetadata } from "../types";
import { Markdown } from "./Markdown";

interface Props {
  content: string;
  metadata: ChatMetadata;
}

/** One assistant reply plus the metadata of *that* request (never conversation totals). */
export function AssistantMessage({ content, metadata }: Props) {
  const cached = metadata.resolution_source === "LLM_CACHE";
  return (
    <article className="msg msg--assistant" data-testid="assistant-message">
      <div className="msg__avatar" aria-hidden="true">
        AI
      </div>
      <div className="msg__body">
        <div className="msg__text msg__text--md" data-testid="assistant-reply">
          <Markdown text={content} />
        </div>
        <dl className="meta" aria-label="Request metadata">
          <div className={`meta__item meta__source ${cached ? "is-cache" : "is-live"}`} title="Resolution source">
            <dt className="sr-only">Source</dt>
            <dd data-testid="meta-source">{metadata.resolution_source}</dd>
          </div>
          <div className="meta__item" title="Model that answered">
            <dt>model</dt>
            <dd data-testid="meta-model">{metadata.model}</dd>
          </div>
          <div className="meta__item" title="Server-measured latency for this request">
            <dt>latency</dt>
            <dd data-testid="meta-latency">{metadata.latency_ms} ms</dd>
          </div>
          <div className="meta__item" title="Prompt tokens of this request (system + history + new message)">
            <dt>in</dt>
            <dd data-testid="meta-input-tokens">{metadata.input_tokens}</dd>
          </div>
          <div className="meta__item" title="Completion tokens of this reply">
            <dt>out</dt>
            <dd data-testid="meta-output-tokens">{metadata.output_tokens}</dd>
          </div>
          <div className="meta__item" title="API key that answered (null on cache hits)">
            <dt>key</dt>
            <dd data-testid="meta-key-id">{metadata.key_id ?? "—"}</dd>
          </div>
          <div
            className={`meta__item ${metadata.fallback_attempts > 0 ? "is-warn" : ""}`}
            title="Keys that failed before one succeeded"
          >
            <dt>failovers</dt>
            <dd data-testid="meta-fallback-attempts">{metadata.fallback_attempts}</dd>
          </div>
        </dl>
      </div>
    </article>
  );
}
