import React from "react";
import { Link, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { chunkRecovery } from "../utils/chunkLoad";

/**
 * Route-level error boundary (UX fix 2026-11): a failed lazy chunk or any
 * other render error used to surface React Router's raw "Unexpected
 * Application Error!" with no recovery path. This boundary keeps the shell
 * and offers two explicit actions — reload the app (a manual action, never
 * automatic, so no reload loop) and return to the Library. The boundary
 * resets itself when the visited path changes, so a navigation away from
 * the broken page recovers normally.
 */
class RouteErrorPanel extends React.Component<
  {
    pathname: string;
    children: React.ReactNode;
    t: (key: string, options?: Record<string, unknown>) => string;
  },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("Route render failed", error, info);
  }

  componentDidUpdate(previous: { pathname: string }) {
    if (previous.pathname !== this.props.pathname && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div
        className="app-panel mx-auto mt-10 max-w-lg py-10 text-center"
        role="alert"
      >
        <h1 className="text-2xl font-semibold text-app-text">
          {this.props.t("routeError.title")}
        </h1>
        <p className="mt-2 text-sm leading-6 text-app-muted">
          {this.props.t("routeError.body")}
        </p>
        <div className="mt-6 flex items-center justify-center gap-3">
          <button
            type="button"
            onClick={chunkRecovery.reload}
            className="touch-target inline-flex items-center gap-2 border border-app-accent bg-app-panel px-4 text-sm text-app-accent"
          >
            {this.props.t("routeError.reload")}
          </button>
          <Link
            to="/dives"
            className="touch-target inline-flex items-center gap-2 border border-app bg-app-panel px-4 text-sm text-app-text"
          >
            {this.props.t("notFound.backToLibrary")}
          </Link>
        </div>
      </div>
    );
  }
}

export default function RouteErrorBoundary({
  children,
}: {
  children: React.ReactNode;
}) {
  const location = useLocation();
  const { t } = useTranslation();
  return (
    <RouteErrorPanel pathname={location.pathname} t={t}>
      {children}
    </RouteErrorPanel>
  );
}
