import { useEffect, useRef, useState } from "react";
import { AdapterError } from "./api/errors.js";
import { evidenceMatchesHit } from "./lib/search.js";
import { isSourceUnavailable } from "./lib/scan.js";

const labels = { candidate: "Candidate", confirmed: "Confirmed", corrected: "Corrected", rejected: "Rejected" };

function Notice({ error }) {
  return error ? <div className="notice notice-danger" role="alert"><div><strong>{error.message}</strong><span>{error.code || "request_failed"}</span></div></div> : null;
}

function RelationCard({ relation, file, adapter, review, onReload, onSaved }) {
  const [source, setSource] = useState(null);
  const [error, setError] = useState(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [receipt, setReceipt] = useState(null);
  const [uncertain, setUncertain] = useState(false);
  const [actor, setActor] = useState("");
  const [reason, setReason] = useState("");
  const [decision, setDecision] = useState("confirmed");
  const [target, setTarget] = useState("");
  const alive = useRef(true);
  const posting = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const state = receipt?.decision || relation.decision || "candidate";
  const revision = receipt?.decision_revision ?? relation.decision_revision;
  const invalidSource = isSourceUnavailable(file, error);

  async function openSource() {
    setSource(null); setError(null); setSourceLoading(true);
    try {
      // The frozen relation contract provides a quote/page, not a chunk ID.
      // Resolve through scoped search and verify the full quote against evidence.
      const result = await adapter.search({ query: relation.quote.slice(0, 60), rootId: file.root_id,
        fileId: file.file_id, mode: "keyword", topK: 50 });
      const hit = result.results.find((item) => item.file_id === file.file_id &&
        item.version_id === file.version_id && item.page === relation.page_number);
      if (!hit) throw new AdapterError("The candidate could not be resolved to its current source page. Reload or ask the parser owner to check its evidence.", { code: "source_unavailable", status: 409 });
      const evidence = await adapter.getEvidenceByChunk(hit.chunk_id);
      const compact = (value) => value.replace(/\s+/gu, " ").trim();
      if (!evidenceMatchesHit(evidence, hit) || !compact(evidence.text).includes(compact(relation.quote))) {
        throw new AdapterError("The current source does not contain this candidate quote. Reload before reviewing.", { code: "version_superseded", status: 409 });
      }
      if (alive.current) setSource(evidence);
    } catch (caught) { if (alive.current) setError(caught); }
    finally { if (alive.current) setSourceLoading(false); }
  }

  async function save(event) {
    event.preventDefault();
    if (posting.current || !source || receipt || uncertain || invalidSource || sourceLoading ||
      !actor.trim() || (decision === "corrected" && !target.trim())) return;
    posting.current = true; setSaving(true); setError(null);
    try {
      const result = await adapter.recordReview(relation.relationship_id, { decision, expectedRevision: revision,
        actor, reason, correctedEntityId: decision === "corrected" ? target.trim() : null });
      if (alive.current) {
        const saved = { ...result, decision, corrected_entity_id: decision === "corrected" ? target.trim() : null };
        setReceipt(saved);
        onSaved(saved);
      }
    } catch (caught) {
      if (alive.current) {
        setError(caught);
        // A failed response can follow a successful write. Require a read before another POST.
        setUncertain(["review_conflict", "REQUEST_TIMEOUT", "NETWORK_ERROR", "CONTRACT_MISMATCH"].includes(caught.code) || caught.status >= 500);
      }
    } finally {
      posting.current = false;
      if (alive.current) setSaving(false);
    }
  }

  return <article className="relation-card">
    <div className="relation-title"><div><span className="meta-label">{relation.entity_type} · {relation.relation_type}</span><h2>{relation.label}</h2></div><span className={"relation-state relation-" + state}>{labels[state]}</span></div>
    <p className="relation-provenance">{relation.origin === "rule" ? "Rule-derived candidate" : relation.origin ? "Origin: " + relation.origin : "Provenance not supplied by service"}{relation.producer_revision ? " · " + relation.producer_revision : ""} · Revision {revision}</p>
    <blockquote>{relation.evidence_missing
      ? "Supporting evidence is missing. This candidate cannot be reviewed."
      : invalidSource || (!source && error)
        ? "Stored quote hidden because the current source could not be verified."
        : source
          ? "Verified candidate quote: " + (relation.quote || "No supporting quote.")
          : "Unverified candidate quote: " + (relation.quote || "No supporting quote.")}</blockquote>
    <p className="relation-locator">{file.relative_path} · {relation.page_number == null ? "Page unknown" : "Page " + relation.page_number}<br /><code>Version {file.version_id}</code></p>
    <button className="secondary-button" onClick={openSource} disabled={sourceLoading || relation.evidence_missing || !relation.quote || uncertain || saving}>{sourceLoading ? "Reading source…" : source ? "Recheck source passage" : "Open source passage"}</button>
    <Notice error={error} />
    {source && !invalidSource && <div className="verified-passage" role="status"><strong>Source verified · {source.page_number == null ? "Page unknown" : "Page " + source.page_number}</strong><p>{source.text}</p><code>Chunk {source.chunk_id}</code><code>SHA-256 {source.content_sha256}</code></div>}
    {receipt && <div className="notice notice-success" role="status">Decision saved by service: {labels[receipt.decision]} · Revision {receipt.decision_revision}. <button className="text-button" onClick={onReload}>Reload latest candidates</button></div>}
    {uncertain && <div className="notice notice-info" role="status">Submission is locked until the latest server revision is read. <button className="text-button" onClick={onReload}>Reload latest candidates</button></div>}
    {review && !receipt && <form className="review-form" onSubmit={save} aria-label={"Review " + relation.label}>
      <fieldset disabled={!source || saving || uncertain || relation.evidence_missing || invalidSource}>
        <legend>Human decision</legend>
        <p>Check the source before recording a decision. The original file stays read-only.</p>
        <label>Decision<select aria-label={"Decision for " + relation.label} value={decision} onChange={(event) => { setDecision(event.target.value); setTarget(""); }}><option value="confirmed">Confirm</option><option value="corrected">Correct</option><option value="rejected">Reject</option></select></label>
        {decision === "corrected" && <label>Existing replacement entity ID<input value={target} onChange={(event) => setTarget(event.target.value)} required maxLength={36} /></label>}
        <label>Reviewer<input value={actor} onChange={(event) => setActor(event.target.value)} required maxLength={120} autoComplete="off" /></label>
        <label>Reason<textarea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={1000} rows={2} /></label>
        <button className="primary-button" type="submit" disabled={!actor.trim() || (decision === "corrected" && !target.trim())}>{saving ? "Saving decision…" : "Save decision"}</button>
      </fieldset>
      {!source && <p className="muted-copy">Open and verify the source passage to enable review.</p>}
    </form>}
    {relation.corrected_entity_id && <p>Corrected entity: <code>{relation.corrected_entity_id}</code></p>}
  </article>;
}

export function RelationsPage({ adapter, review = false }) {
  const rootId = window.sessionStorage.getItem("lastRootId");
  const [files, setFiles] = useState([]);
  const [versionId, setVersionId] = useState("");
  const [relations, setRelations] = useState([]);
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState(null);
  const [reload, setReload] = useState(0);
  const [catalogReload, setCatalogReload] = useState(0);
  useEffect(() => {
    if (!rootId) return;
    let cancelled = false;
    setCatalogLoading(true); setCatalogError(null); setFiles([]); setVersionId("");
    adapter.listFiles(rootId).then((items) => {
      if (cancelled) return;
      const available = items.filter((file) => file.version_id && ["basic_ready", "enriched"].includes(file.status) && !isSourceUnavailable(file));
      setFiles(available);
      const stored = window.sessionStorage.getItem("lastRelationVersion");
      setVersionId(available.some((file) => file.version_id === stored) ? stored : available[0]?.version_id || "");
    }).catch((caught) => { if (!cancelled) setCatalogError(caught); })
      .finally(() => { if (!cancelled) setCatalogLoading(false); });
    return () => { cancelled = true; };
  }, [adapter, rootId, catalogReload]);
  useEffect(() => {
    let cancelled = false;
    setRelations([]); setError(null); setLoading(Boolean(versionId));
    if (versionId) {
      window.sessionStorage.setItem("lastRelationVersion", versionId);
      adapter.listRelations(versionId).then((items) => { if (!cancelled) setRelations(items); })
        .catch((caught) => { if (!cancelled) setError(caught); })
        .finally(() => { if (!cancelled) setLoading(false); });
    }
    return () => { cancelled = true; };
  }, [adapter, versionId, reload]);
  const file = files.find((item) => item.version_id === versionId);
  const shown = relations.filter((item) => filter === "all" || (item.decision || "candidate") === filter);
  return <>
    <div className="page-heading"><div className="heading-copy"><p className="meta-label">EVIDENCE & HUMAN JUDGMENT</p><h1>{review ? "Review candidate relations" : "Explore source relations"}</h1><p className="lede">Up to 20 candidates per version. A mention is a candidate until a human decision is saved.</p></div></div>
    <div className="notice notice-info" role="note">Relations are suggestions. Verify the source passage before recording a human decision.</div>
    {!rootId ? <div className="empty-state"><h2>Choose an authorized directory first</h2><a href="/select">Open directories and jobs</a></div> : <>
      <div className="relation-toolbar"><label>Current document version<select aria-label="Relation document" value={versionId} disabled={catalogLoading || !files.length} onChange={(event) => setVersionId(event.target.value)}>{!files.length && <option value="">{catalogLoading ? "Loading files…" : "No searchable current versions"}</option>}{files.map((item) => <option key={item.file_id + item.version_id} value={item.version_id}>{item.relative_path}</option>)}</select></label><button className="secondary-button" disabled={catalogLoading || loading} onClick={() => setCatalogReload((value) => value + 1)}>Refresh current versions</button></div>
      <Notice error={catalogError} />
      <Notice error={error} />
      {error && <button className="secondary-button" onClick={() => setReload((value) => value + 1)}>Retry relation read</button>}
      {!catalogLoading && !catalogError && !files.length && <div className="empty-state"><h2>No searchable versions</h2><p>Complete parsing before loading relation candidates.</p></div>}
      {catalogLoading || loading ? <div className="results-loading" role="status">Loading current candidates…</div> : !catalogError && !error && file && <>
        <div className="filter-row" aria-label="Relation status filters">{["all", "candidate", "confirmed", "corrected", "rejected"].map((key) => <button key={key} className={"filter-chip " + (filter === key ? "selected" : "")} aria-pressed={filter === key} onClick={() => setFilter(key)}>{key === "all" ? "All" : labels[key]}</button>)}</div>
        {!shown.length ? <div className="empty-state"><h2>No {filter === "all" ? "relation" : filter} candidates</h2><p>{relations.length ? "Choose another status filter." : "The service returned an empty candidate list for this version."}</p></div> : <div className="relation-list">{shown.map((item) => <RelationCard key={[versionId, reload, item.relationship_id].join(":")} relation={item} file={file} adapter={adapter} review={review} onReload={() => setReload((value) => value + 1)} onSaved={(saved) => setRelations((current) => current.map((candidate) => candidate.relationship_id === item.relationship_id ? { ...candidate, ...saved } : candidate))} />)}</div>}
      </>}
    </>}
  </>;
}
