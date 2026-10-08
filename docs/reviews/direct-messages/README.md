# Direct messages (community PR 3/3)

Private conversations open from member profiles or the Messages inbox. Signed-in
members can send text with the shared mention composer and share an accessible
dive directly from the existing player. Hearts toggle by double tap or an
accessible button. The inbox shows unread counts and newest conversations first.

Every messaging route requires active conversation membership, including for
administrators. Sending a dive checks every participant's access and never grants
access. Cards resolve metadata/posters per viewer on each fetch and become
unavailable after privacy changes or deletion; message text remains in the
conversation. Push notifications contain generic text and a conversation link,
not message contents. Existing notification preferences control message alerts.

Receipts are explicit recipient acknowledgements: Sent follows the server commit;
Delivered follows browser receipt; Read at requires a visible message in a focused,
visible conversation. Fetching an inbox or messages alone does not write receipts.
Times are server acknowledgement times, not proof a person comprehended the text.
The UI polls visible conversations every three seconds and the inbox every five
seconds; this implementation does not add a WebSocket or typing indicator.

Conversation rows, participant rows, per-recipient receipts and per-user reactions
are separate. Direct pairs have a unique canonical key. The model supports group
conversations; group creation, membership changes and group UI are future work.
Client UUID retry keys prevent duplicate messages and notifications after a failed
response. Message and inbox reads are paginated and batched.

Apply `backend/migrations/add_direct_messages.sql` after the profile and comment
mention migrations, before deploying the backend. The SQL is additive/repeatable.
No production migration or deployment was performed during development.

Screenshots use real public Fouiny/FANNY dive footage and real member identities
in the isolated local preview from PR 1. Messages, reactions and notifications were
created only in that preview; no production member was contacted or modified.
Media originals and preview credentials are not committed.

Verification: membership/outsider denial, retry idempotency, notification privacy,
delivery/read acknowledgements, repeated reactions, dive revocation, pagination,
and Origin tests; UI focus/visibility receipts, failed-send retry and reactions;
two-account browser flow with actual dive posters and video playback; migration
applied twice in isolated Postgres and full Linux backend validation.
