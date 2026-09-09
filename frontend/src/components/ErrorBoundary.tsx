import { Component, type ErrorInfo, type ReactNode } from "react";

interface State { error: Error | null }

/** Render-error boundary; keyed by page so switching remounts and recovers (T&C pattern). */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };
  static getDerivedStateFromError(error: Error): State { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo): void { console.error("render error", error, info); }
  render() {
    if (this.state.error) return <div className="errbox">UI error: {this.state.error.message} <button className="secondary" onClick={() => this.setState({ error: null })}>retry</button></div>;
    return this.props.children;
  }
}
