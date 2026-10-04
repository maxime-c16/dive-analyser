"""BMC-G: greedy ballistic chaining of micro-tracklets (see fsr_search_v4)."""
from fsr_search_v4 import *  # noqa
import fsr_search_v4 as _b
SEARCH_VERSION = 'FLIGHT_SEARCH_RECOVERY_V1_BMCG'
PROTOCOL_CONSTANTS = dict(_b.PROTOCOL_CONSTANTS, SEARCH_VERSION=SEARCH_VERSION)
search = _b.search_greedy
