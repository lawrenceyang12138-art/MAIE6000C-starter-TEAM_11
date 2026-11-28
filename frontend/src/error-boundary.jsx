import React from "react";

/**
 * Last-resort boundary: a render-time exception (malformed URL segment, an
 * unexpected adapter payload) must not leave the user with a blank page and no
 * way back. It never retries a request; it only offers a deliberate reload.
 */
export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("Render failed", error, info?.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="app-shell" role="alert">
        <main className="page-wrap" style={{ display: "grid", placeItems: "center" }}>
          <section className="workspace-panel glass-card" style={{ maxWidth: 640 }}>
            <h1>This view could not be rendered</h1>
            <p className="muted-copy">
              No request was replayed and no file was changed. Return to the directory selector and try again.
            </p>
            <code>{String(this.state.error?.message || this.state.error)}</code>
            <button className="primary-button" onClick={() => window.location.assign("/select")}>
              Back to directories
            </button>
          </section>
        </main>
      </div>
    );
  }
}
