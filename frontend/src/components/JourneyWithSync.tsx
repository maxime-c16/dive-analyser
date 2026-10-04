import React from "react";
import { useSyncStatus } from "../hooks/useSyncStatus";

interface JourneyWithSyncProps {
  children: React.ReactNode;
  onSyncComplete?: () => void;
}

/**
 * JourneyWithSync Component
 * Keeps Journey data fresh when a background sync completes. Operational
 * connection state belongs in System and must not consume reading space here.
 */
export const JourneyWithSync: React.FC<JourneyWithSyncProps> = ({
  children,
  onSyncComplete,
}) => {
  const { currentSync } = useSyncStatus();

  // Notify when sync completes
  React.useEffect(() => {
    if (currentSync?.status === "complete" && onSyncComplete) {
      onSyncComplete();
    }
  }, [currentSync?.status, onSyncComplete]);

  return <>{children}</>;
};

export default JourneyWithSync;
