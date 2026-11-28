import { useSetup } from "./lib/use-setup.js";

const stages = {
  pending: "Preparing local AI",
  checking_environment: "Checking the local AI environment",
  installing_dependencies: "Installing local AI dependencies",
  checking_model: "Checking local model files",
  downloading: "Downloading the local PPLX model",
  verifying: "Verifying model files",
  loading: "Loading the local model",
  warming_up: "Warming up local AI",
  ready: "Local AI is ready",
  error: "Local AI preparation stopped",
  disabled: "Local AI is disabled",
  unavailable: "Local AI service is unavailable",
};

function bytes(value) {
  if (value >= 1024 ** 3) return (value / 1024 ** 3).toFixed(2) + " GiB";
  if (value >= 1024 ** 2) return (value / 1024 ** 2).toFixed(1) + " MiB";
  if (value >= 1024) return (value / 1024).toFixed(1) + " KiB";
  return value + " B";
}

export function SetupProgress({ adapter }) {
  const { status, readError, retrying, retry } = useSetup(adapter);
  if (adapter.mode === "mock") return null;
  const state = readError ? "unavailable" : status?.state || "pending";
  const ready = state === "ready" && status?.ready;
  const failed = ["error", "unavailable"].includes(state);
  const preparing = !["ready", "error", "disabled", "unavailable"].includes(state);
  const overall = preparing && status?.progress != null ? status.progress : null;
  const stage = preparing && status?.stage_progress != null ? status.stage_progress : null;
  const percent = overall ?? stage;
  return <section className={"setup-progress notice " + (ready ? "notice-success" : failed ? "notice-danger" : "notice-info")} aria-label="Local AI preparation" data-state={state}>
    <div className="setup-progress-content">
      <strong role="status" aria-live="polite">{retrying ? "Retrying local AI preparation…" : stages[state]}</strong>
      {ready ? <span>Model verified and warmed up. Semantic search is available for indexed files.</span>
        : <span>{state === "disabled" ? "Enable local AI in the service configuration to prepare the model." : "Keyword search and original source evidence remain available."}</span>}
      {preparing && !retrying && <>
        <progress aria-label={overall == null && stage != null ? "Current preparation stage progress" : "Local AI preparation progress"} max="100" {...(percent == null ? {} : { value: percent })} />
        <span className="setup-progress-detail">
          {overall != null ? Math.floor(overall) + "% overall" : stage != null ? Math.floor(stage) + "% of this stage" : "Preparation progress is not yet known"}
          {overall != null && stage != null && " · " + Math.floor(stage) + "% of this stage"}
          {state === "downloading" && status && " · " + bytes(status.downloaded_bytes) + (status.total_bytes == null ? " downloaded" : " / " + bytes(status.total_bytes))}
          {status?.total_files > 0 && " · " + status.completed_files + " / " + status.total_files + " files"}
        </span>
      </>}
      {state === "error" && status?.error_code && <span>Error code: {status.error_code}</span>}
      {readError && <span>Preparation status could not be read. Reconnecting automatically.</span>}
    </div>
    {status?.state === "error" && status.retryable && !readError && <button className="secondary-button" disabled={retrying} onClick={retry}>{retrying ? "Retry requested…" : "Retry AI preparation"}</button>}
  </section>;
}
