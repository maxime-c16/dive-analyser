# Comment mentions (community PR 2/3)

Type @ in a signed-in dive comment or reply, search the existing member directory,
and select a person by mouse or keyboard. Selected identities render as profile
links. Spans store member IDs and Unicode code-point offsets; editing a label
removes its identity and edits before it shift the span. Names may change without
retargeting already published comments. Guests can still write plain comments,
but cannot search the member directory or submit structured mentions.

The composer, renderer and validation service are shared with the later messaging
PR. This PR adds no message inbox or mention-specific notifications.

Apply `backend/migrations/add_comment_mentions.sql` before backend deployment.
It is additive and repeatable; existing comments retain plain text.

Screenshots use Fouiny's real public dive footage and the existing FANNY owner
binding, copied into the isolated local preview described in PR 1. The comment
was created only in that preview; no production comment or member was changed.
No original media files, private metadata or credentials are committed.

Verification: API tests for Unicode/trim offsets, durable links after renaming,
invalid/inactive identities, overlapping spans and private-dive access; UI tests
for autocomplete selection, editing, stable profile links and guest restrictions.
Browser verification searched Fanny, selected Fouiny, posted a linked mention,
and opened the real member profile from that mention.
