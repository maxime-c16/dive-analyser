"""Core Detection V1 P0/P1 protocol constants.

All evaluation-relevant constants are PRE-REGISTERED here before final
evaluation. Values are frozen at protocol freeze time and must not be
tuned after looking at final event-level performance.

Product north star (P1): spot every actual dive in a long raw session with
very high event recall and extract a rough clip containing the complete dive.
Missing a real dive is much worse than an extra candidate clip, so metrics
optimize EVENT RECALL first and report false positives explicitly.
"""

# --- session scanning representation ---------------------------------------
SCAN_FPS = 2.0                 # thumbnails per second for the full-session scan
SCAN_WIDTH = 480               # 360p-class scanning representation (16:9)
SCAN_HEIGHT = 270
SIGNATURE_SIZE = (64, 36)      # grayscale signature for clip alignment

# --- GT authority ------------------------------------------------------------
# DIRECT_HUMAN_GT: athlete captioned the clip in Photos (dive code present in
#   the Dive Analyzer DB) -> the clip contains exactly one real dive.
# DETERMINISTICALLY_RECOVERED_GT: clip window in the raw session recovered by
#   the strict alignment verifier (unique NCC peak + multi-frame consistency).
# WEAK_LABEL: uncaptioned clip assumed to contain a dive, or alignment that
#   passes a relaxed check. Diagnostics only, never primary GT.
GT_DIRECT = "DIRECT_HUMAN_GT"
GT_RECOVERED = "DETERMINISTICALLY_RECOVERED_GT"
GT_WEAK = "WEAK_LABEL"
GT_UNLABELED = "UNLABELED"

# --- alignment verifier v2 (deterministic GT recovery) ----------------------
# v1 matched raw thumbnails; in the static pool scene raw NCC is nearly
# undiscriminating (median ~0.99) and produced false peaks in empty segments
# (verified visually). v2 matches temporal-derivative signatures with robust-z
# prominence, then applies a raw-signature NCC floor at the consensus offset.
# Registered before any event-level evaluation; supersedes v1 thresholds.
ALIGN_DERIV_Z_MIN = 6.0         # robust-z prominence of a frame's best peak
ALIGN_DERIV_NCC_MIN = 0.10      # derivative NCC floor for a frame to vote
ALIGN_DERIV_EXCLUDE_IDX = 15    # +- thumbnails excluded around the peak
ALIGN_CLUSTER_TOL_S = 1.0       # offset clustering tolerance
ALIGN_MIN_CLUSTER = 4           # min cluster votes (uncaptioned clips)
ALIGN_MIN_CLUSTER_CAPTIONED = 3  # min cluster votes (captioned clips)
ALIGN_PATH_MIN = 0.45           # min path score of the accepted cluster
ALIGN_PATH_MARGIN = 0.05        # path margin over runner-up cluster
ALIGN_RAW_BLOCK = 9             # consecutive raw signatures per block sample
ALIGN_RAW_NCC_MIN = 0.97        # raw-signature block NCC floor at consensus
ALIGN_MAX_OFFSET_SPREAD_S = 1.0  # max spread of per-frame offsets to accept

# --- event semantics / matching (pre-registered) -----------------------------
EVENT_MATCH_TOL_S = 2.0        # predicted event time must fall inside
                               # [gt_start - tol, gt_end + tol]
REFRACTORY_S = 15.0            # min spacing between emitted candidates

# --- rough clip extraction (pre-registered) ---------------------------------
ROUGH_PRE_ROLL_S = 8.0
ROUGH_POST_ROLL_S = 6.0

# --- eventness threshold rule (pre-registered, data-derived, no tuning) -----
EVENTNESS_Z_K = 4.0            # robust z threshold (median + k * MAD-sigma)
EVENTNESS_SMOOTH_S = 1.0       # smoothing half-window in seconds

# --- pre-registered development target (NOT a production SLA) ---------------
PRE_REGISTERED_EVENT_RECALL_TARGET = 0.90

# --- P1 statuses -------------------------------------------------------------
P1_PROMISING = "CORE_DETECTION_P1_PROMISING"
P1_PARTIAL = "CORE_DETECTION_P1_PARTIAL"
P1_NOT_READY = "CORE_DETECTION_P1_NOT_READY"

FAILURE_CATEGORIES = [
    "VISUAL_ENTRY_NOT_SALIENT",
    "UNRELATED_SPLASH",
    "OTHER_PERSON",
    "CAMERA_MOTION",
    "AUDIO_FALSE_POSITIVE",
    "MULTIPLE_CLOSE_EVENTS",
    "REPRESENTATION_LIMIT",
    "UNKNOWN",
]
